"""DAIA autonomous audit orchestrator (V4 — Implementação 08).

Runs the 15 mandatory stages, checkpoints after every stage (and periodically
inside long stages), stops cleanly on any budget limit or interruption, and
resumes only what is pending. A global audit is CONCLUÍDA only when every
stage ran, every planned domain was fully read and every planned resource was
analysed; otherwise it stays INCOMPLETA with the unmet criteria listed.

The orchestrator never writes to Datadog or infrastructure. Jira issues are
only *proposed*, except for an explicit on-demand human approval (never in a
scheduled run).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

from daia.jira.client import JiraClientError, JiraTimeoutError
from daia.jira.controller import JiraController
from daia.jira.models import CreationApproval, JiraConfig, JiraIssueProposal, JiraIssueSearchResult

from .analyzers import Analyzer, metric_work_items, prioritize
from .collector import ExternalInterruption, ToolClient, ToolPort, iso, parse_iso, utc_now
from .guides import build_guide, navigation, procedure
from .limits import Budget, BudgetExceeded, LimitPolicy, LimitPolicyError, RateLimiter, ScopeApproval
from .store import CHECKPOINT_SCHEMA, AuditStore, FindingRegistry

ORCHESTRATOR_VERSION = "orchestrator-1.0.0"

STAGES = [
    ("01_discovery", "Discovery"),
    ("02_inventory", "Inventário"),
    ("03_coverage_validation", "Validação de cobertura"),
    ("04_health_check", "Health Check"),
    ("05_anomaly_detection", "Detecção de anomalias"),
    ("06_deep_investigation", "Investigação aprofundada"),
    ("07_correlation", "Correlação"),
    ("08_preventive_analysis", "Análise preventiva"),
    ("09_prioritization", "Priorização"),
    ("10_history_check", "Verificação de histórico"),
    ("11_jira_dedup", "Deduplicação Jira"),
    ("12_human_guides", "Guia de resolução humana"),
    ("13_activity_preparation", "Preparação das atividades"),
    ("14_report", "Relatório sob demanda"),
    ("15_progress_record", "Registro de progresso"),
]
COLLECTION_STAGES = {"01_discovery": ["metrics"], "02_inventory": ["inventory"],
                     "04_health_check": ["monitors", "events", "changes", "incidents", "logs"],
                     "05_anomaly_detection": ["metrics"], "06_deep_investigation": ["apm"], "11_jira_dedup": ["jira"]}
DONE = ("CONCLUÍDA", "NÃO SOLICITADO")
SATISFIED = ("CONCLUÍDO", "NÃO NECESSÁRIO")


@dataclass
class AuditRequest:
    environment: str
    window_hours: float | None = None
    domains: list[str] | None = None
    mode: str = "on_demand"                      # on_demand | preventive
    trigger: dict[str, Any] = field(default_factory=lambda: {"type": "manual"})
    report: bool = False
    create_approved_jira: bool = False
    jira_approval: dict[str, Any] | None = None
    task_text: str = ""

    def validate(self, policy: LimitPolicy, scope_approval: ScopeApproval | None) -> list[str]:
        notes = []
        if not self.environment:
            raise LimitPolicyError("ambiente é obrigatório (não há ambiente implícito)")
        if self.mode not in ("on_demand", "preventive"):
            raise LimitPolicyError(f"modo inválido: {self.mode}")
        default_window = policy.defaults.get("window_hours")
        if self.window_hours is None:
            self.window_hours = default_window
        default_domains = list(policy.defaults.get("domains", []))
        if self.domains is None:
            self.domains = default_domains
        extra = [d for d in self.domains if d not in default_domains]
        if (default_window is not None and self.window_hours > default_window) or extra:
            if scope_approval is None:
                raise LimitPolicyError(f"ampliação de escopo (janela {self.window_hours}h, domínios extras {extra}) exige aprovação humana")
            scope_approval.validate()
            notes.append(f"escopo ampliado aprovado por {scope_approval.approver} ({scope_approval.approval_id})")
        if self.mode == "preventive":
            if self.create_approved_jira or self.jira_approval:
                notes.append("modo preventivo: aprovações de criação Jira ignoradas — agendamento não concede permissões")
            self.create_approved_jira = False
            self.jira_approval = None
        return notes


class AuditOrchestrator:
    def __init__(self, port: ToolPort, store: AuditStore, *, policy: LimitPolicy | None = None,
                 registry: FindingRegistry | None = None, now: Callable[[], datetime] = utc_now,
                 monotonic: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 checkpoint_every: int = 10):
        self.port, self.store = port, store
        self.policy = policy or LimitPolicy.load()
        self.registry = registry or FindingRegistry()
        self.now, self.monotonic, self.sleep = now, monotonic, sleep
        self.checkpoint_every = checkpoint_every
        self.cp: dict[str, Any] = {}
        self._data: dict[str, Any] | None = None

    # ================================================================ entry
    @classmethod
    def new_audit_id(cls, request: AuditRequest, now: datetime) -> str:
        salt = uuid.uuid4().hex[:6]
        return f"AUD-{now.strftime('%Y%m%dT%H%M%SZ')}-{request.environment}-{salt}"

    def start(self, request: AuditRequest, scope_approval: ScopeApproval | None = None) -> dict[str, Any]:
        notes = request.validate(self.policy, scope_approval)
        if self.store.load_checkpoint():
            raise RuntimeError(f"auditoria {self.store.audit_id} já existe; use resume")
        at = self.now()
        self.cp = {
            "schema": CHECKPOINT_SCHEMA, "audit_id": self.store.audit_id, "orchestrator_version": ORCHESTRATOR_VERSION,
            "request": asdict(request) | {"scope_approval": asdict(scope_approval) if scope_approval else None},
            "window": {"start_utc": iso(at - timedelta(hours=request.window_hours)), "end_utc": iso(at), "hours": request.window_hours},
            "policy": self.policy.as_dict(), "status": "EM_ANDAMENTO", "created_at_utc": iso(at), "updated_at_utc": iso(at),
            "stages": {sid: {"name": name, "status": "PENDENTE", "started_at": None, "finished_at": None, "executions": 0} for sid, name in STAGES},
            "coverage": {d: _cov(planned=True) for d in request.domains},
            "planned_domains": list(request.domains), "tools_used": [], "queries": [], "pages_retrieved": 0,
            "limitations": list(notes), "findings": [], "unconfirmed": [], "notices": [], "jira": [], "proposals": [],
            "guides": {}, "data_index": {}, "budget_used": {}, "sessions": [], "interruption": None, "last_checkpoint": None,
            "criteria_unmet": [], "tool_errors": [],
        }
        self.store.event("audit_started", audit_id=self.store.audit_id, at=iso(at), mode=request.mode, trigger=request.trigger)
        return self._run()

    def resume(self, *, policy_overrides: Mapping[str, float] | None = None, scope_approval: ScopeApproval | None = None) -> dict[str, Any]:
        cp = self.store.load_checkpoint()
        if not cp:
            raise RuntimeError(f"auditoria {self.store.audit_id} não encontrada")
        if cp["status"] == "CONCLUÍDA":
            return cp
        self.cp = cp
        base = LimitPolicy(cp["policy"]["version"], dict(cp["policy"]["limits"]), cp["policy"]["staleness_ttl_s"],
                           self.policy.defaults, cp["policy"]["source"], tuple(cp["policy"].get("expansions", [])))
        self.policy = base.with_overrides(policy_overrides, scope_approval) if policy_overrides else base
        self.cp["policy"] = self.policy.as_dict()
        self._plan_resume()
        self.store.event("audit_resumed", at=iso(self.now()), from_checkpoint=cp.get("last_checkpoint"))
        return self._run()

    # ============================================================== driver
    def _run(self) -> dict[str, Any]:
        used = dict(self.cp.get("budget_used") or {})
        self.budget = Budget(self.policy, clock=self.monotonic)
        for k in ("queries", "data_bytes", "tokens", "cost_usd", "retries"):
            self.budget.used[k] = used.get(k, 0)
        self.budget.start()
        self.client = ToolClient(self.port, self.store, self.policy, self.budget, now=self.now, sleep=self.sleep,
                                 rate_limiter=RateLimiter(self.policy.limits["max_queries_per_second"], clock=self.monotonic, sleep=self.sleep))
        self.cp["status"] = "EM_ANDAMENTO"
        self.cp["interruption"] = None
        session = {"started_at": iso(self.now()), "ended_at": None, "dispatches": 0, "cache_hits": 0, "revalidations": 0, "outcome": None}
        self.cp["sessions"].append(session)
        executed_any = False
        try:
            for sid, _ in STAGES:
                st = self.cp["stages"][sid]
                if st["status"] in DONE and not executed_any:
                    continue
                self.budget.check_runtime()
                st.update(status="EM_ANDAMENTO", started_at=iso(self.now()), executions=st["executions"] + 1)
                self._save(sid)
                getattr(self, "_stage_" + sid.split("_", 1)[1])()
                if st["status"] == "EM_ANDAMENTO":
                    st["status"] = "CONCLUÍDA"
                st["finished_at"] = iso(self.now())
                executed_any = True
                self._save(sid)
            session["outcome"] = "fim do fluxo"
        except (BudgetExceeded, ExternalInterruption) as exc:
            if getattr(exc, "tool", None):
                self._tool_errors([{"tool": exc.tool, "code": exc.error.get("code"), "message": exc.error.get("message"),
                                    "http_status": exc.error.get("http_status")}])
            self._interrupt(type(exc).__name__, str(exc))
            session["outcome"] = f"interrompida: {exc}"
        except BaseException as exc:  # crash or KeyboardInterrupt: preserve progress, then propagate
            self._interrupt(type(exc).__name__, str(exc)[:300])
            session["outcome"] = f"interrompida por erro: {type(exc).__name__}"
            self._finalize(session)
            raise
        self._finalize(session)
        return self.cp

    def _interrupt(self, kind: str, message: str) -> None:
        running = next((sid for sid, st in self.cp["stages"].items() if st["status"] == "EM_ANDAMENTO"), None)
        if running:
            self.cp["stages"][running]["status"] = "INTERROMPIDA"
        self.cp["interruption"] = {"kind": kind, "message": message, "stage": running, "at_utc": iso(self.now())}
        self.cp["limitations"].append(f"Execução interrompida na etapa {running}: {message}")
        self.store.event("audit_interrupted", stage=running, kind=kind, message=message)

    def _finalize(self, session: dict[str, Any]) -> None:
        session.update(ended_at=iso(self.now()), dispatches=self.client.dispatches, cache_hits=self.client.cache_hits,
                       revalidations=self.client.revalidations)
        unmet = []
        for sid, st in self.cp["stages"].items():
            if st["status"] not in DONE:
                unmet.append(f"etapa {sid} {st['status']}")
        for d, c in self.cp["coverage"].items():
            if c["planned"] and c["status"] not in SATISFIED:
                unmet.append(f"domínio {d} {c['status']}" + (f": {c['reason']}" if c.get("reason") else ""))
        m = self.cp["coverage"].get("metrics")
        if m and m.get("resources_expected") is not None and m.get("resources_analyzed", 0) < m["resources_expected"]:
            unmet.append(f"métricas analisadas para {m.get('resources_analyzed', 0)} de {m['resources_expected']} consultas planejadas")
        if self.cp["interruption"]:
            unmet.append(f"interrupção: {self.cp['interruption']['message']}")
        self.cp["limitations"] = list(dict.fromkeys(self.cp["limitations"]))
        self.cp["criteria_unmet"] = unmet
        self.cp["status"] = "INCOMPLETA" if unmet else "CONCLUÍDA"
        if self.cp["request"].get("report"):
            from .presentation import render_report
            path = self.store.write_report("report.md", render_report(self.cp))
            self.cp["report_path"] = str(path) if path else None
        self._save(None)
        self.store.event("audit_status", status=self.cp["status"], unmet=len(unmet), at=iso(self.now()))

    def _save(self, stage: str | None) -> None:
        self.cp["budget_used"] = self.budget.snapshot() if hasattr(self, "budget") else self.cp.get("budget_used", {})
        log = self.client.log if hasattr(self, "client") else []
        known = {(q["key"], q["collected_at"], q["from_cache"]) for q in self.cp["queries"]}
        for q in log:
            if (q["key"], q["collected_at"], q["from_cache"]) not in known:
                self.cp["queries"].append(q)
                known.add((q["key"], q["collected_at"], q["from_cache"]))
        self.cp["tools_used"] = sorted({q["tool"] for q in self.cp["queries"]})
        self.cp["pages_retrieved"] = sum(1 for q in self.cp["queries"] if q["ok"] and not q["from_cache"])
        at = iso(self.now())
        self.cp["updated_at_utc"] = at
        if stage:
            self.cp["last_checkpoint"] = {"stage": stage, "at_utc": at}
        self.store.save_checkpoint(self.cp)

    def _plan_resume(self) -> None:
        """Decide what a resumed run must redo (and nothing more):
        - stages not finished (pending/interrupted) — always;
        - finished collection stages whose data exceeded the domain TTL (revalidation);
        - finished collection stages with partial reads that were not permanently blocked (retry).
        Every stage after the earliest redo point is recomputed from the query cache."""
        now = self.now()
        redo: dict[str, str] = {}
        for sid, domains in COLLECTION_STAGES.items():
            if self.cp["stages"][sid]["status"] not in DONE:
                continue
            for key in _keys(self.cp["data_index"].get(sid)):
                rec = self.store.get_query(key)
                if rec and rec["ok"] and (now - parse_iso(rec["collected_at"])).total_seconds() > self.policy.ttl(rec["domain"]):
                    redo.setdefault(sid, "dados expirados (TTL)")
                    break
        for d, cov in self.cp["coverage"].items():
            if cov.get("status") == "BLOQUEADO":
                continue
            for name, part in cov.get("parts", {}).items():
                if not part["complete"] and part.get("stage") and self.cp["stages"][part["stage"]]["status"] in DONE:
                    redo.setdefault(part["stage"], f"leitura parcial em {d}/{name}")
        if not redo:
            return
        first = min(redo)
        reset = False
        for sid, _ in STAGES:
            reset = reset or sid == first
            if reset and self.cp["stages"][sid]["status"] in DONE + ("INTERROMPIDA",):
                self.cp["stages"][sid]["status"] = "PENDENTE"
        for sid, why in sorted(redo.items()):
            self.cp["limitations"].append(f"Retomada: etapa {sid} refeita — {why}.")
            self.store.event("resume_redo", stage=sid, reason=why, at=iso(now))

    # ============================================================ helpers
    def _cov(self, domain: str) -> dict[str, Any]:
        return self.cp["coverage"].setdefault(domain, _cov(planned=False))

    def _collect(self, stage: str, name: str, tool: str, args: Mapping[str, Any], domain: str, item_key: str, style: str = "cursor"):
        coll = self.client.paginate(tool, {**args}, domain, item_key, style=style)
        self.cp["data_index"].setdefault(stage, {})[name] = coll.keys
        items = len(coll.items) if style == "cursor" else sum(len(v) for v in coll.extra.values() if isinstance(v, list))
        self._part(domain, name, stage=stage, queries=len(coll.keys), pages=coll.pages_read, items=items, complete=coll.complete, reason=coll.reason)
        if coll.errors:
            self._tool_errors(coll.errors)
        return coll

    def _part(self, domain: str, name: str, **stats: Any) -> None:
        cov = self._cov(domain)
        cov["parts"][name] = stats
        cov["last_collected_at"] = iso(self.now())

    def _tool_errors(self, errors: list[dict[str, Any]]) -> None:
        for e in errors:
            if not any(x["tool"] == e["tool"] and x["code"] == e["code"] for x in self.cp["tool_errors"]):
                self.cp["tool_errors"].append({"tool": e["tool"], "code": e["code"], "http_status": e.get("http_status"),
                                               "message": e.get("message"), "shown_to_human": True})

    def _close_domain(self, domain: str, *, needed: bool = True) -> None:
        cov = self._cov(domain)
        parts = cov["parts"].values()
        cov["queries"] = sum(p["queries"] for p in parts)
        cov["pages"] = sum(p["pages"] for p in parts)
        cov["items"] = sum(p["items"] for p in parts)
        cov["incomplete_parts"] = [f"{n}: {p['reason']}" for n, p in cov["parts"].items() if not p["complete"]]
        if not needed and cov["queries"] == 0:
            cov["status"] = "NÃO NECESSÁRIO"
        elif any(e["tool"] in _DOMAIN_TOOLS.get(domain, ()) and e["code"] in ("FORBIDDEN_BY_POLICY", "PERMISSION_DENIED", "UNAUTHENTICATED")
                 for e in self.cp["tool_errors"]):
            cov["status"] = "BLOQUEADO"
            cov["reason"] = "acesso negado pela política ou credencial"
        elif cov["incomplete_parts"]:
            cov["status"] = "PARCIAL" if cov["pages"] else "FALHOU"
            cov["reason"] = "; ".join(cov["incomplete_parts"][:3])
        else:
            cov["status"] = "CONCLUÍDO"
            cov["reason"] = None

    def data(self) -> dict[str, Any]:
        """Rebuild collected telemetry from the query cache (no dispatch)."""
        if self._data is not None:
            return self._data
        idx = self.cp["data_index"]
        d: dict[str, Any] = {"call_ids": {}, "metrics": {}}

        def records(keys):
            return [r for r in (self.store.get_query(k) for k in keys) if r and r["ok"]]

        cat = records((idx.get("01_discovery") or {}).get("catalog", []))
        d["metric_catalog"] = [m for r in cat for m in r["data"].get("metrics", [])]
        d["metric_catalog_complete"] = self.cp.get("catalog_complete", False)
        inv: dict[str, list] = {}
        for r in records((idx.get("02_inventory") or {}).get("inventory", [])):
            for k, v in (r["data"].get("items") or {}).items():
                inv.setdefault(k, []).extend(v)
        d["inventory"] = inv
        for name, key in (("monitors", "monitors"), ("events", "events"), ("changes", "changes"), ("incidents", "incidents"), ("logs", "logs")):
            recs = records((idx.get("04_health_check") or {}).get(name, []))
            d[name] = [x for r in recs for x in r["data"].get(key, [])]
            d["call_ids"][name] = recs[0]["call_id"] if recs else None
        for mk, keys in ((idx.get("05_anomaly_detection") or {}).items()):
            recs = records(keys)
            if recs and recs[0]["data"].get("series"):
                s = recs[0]["data"]["series"][0]
                d["metrics"][mk] = {"values": s["values"], "start": s["start"], "call_id": recs[0]["call_id"], "key": recs[0]["key"]}
        self._data = d
        return d

    def _analyzer(self) -> Analyzer:
        a = Analyzer(self.data(), self.cp["request"]["environment"], parse_iso(self.cp["window"]["end_utc"]))
        a.findings = self.cp["findings"]
        a.notices = self.cp["notices"]
        a.unconfirmed = self.cp["unconfirmed"]
        return a

    # ============================================================== stages
    def _stage_discovery(self) -> None:
        self._data = None
        coll = self._collect("01_discovery", "catalog", "search_datadog_metrics", {"query": ""}, "metrics", "metrics")
        self.cp["catalog_complete"] = coll.complete
        if not coll.complete:
            self.cp["limitations"].append("Catálogo de métricas incompleto: monitores em No Data não podem ser classificados como quebrados.")
        text = self.cp["request"].get("task_text") or ""
        if re.search(r"(?i)silenci|mute|ajuste o dashboard|apague|reinicie", text):
            self.cp["limitations"].append("Solicitação de alteração recusada: Datadog e infraestrutura são somente leitura para o agente; ver procedimento humano.")

    def _stage_inventory(self) -> None:
        self._data = None
        coll = self._collect("02_inventory", "inventory", "search_datadog_entities", {}, "inventory", "items", style="page")
        self._close_domain("inventory")
        if not coll.complete:
            self.cp["limitations"].append(f"Inventário incompleto ({coll.reason}); conclusão global impossível.")

    def _stage_coverage_validation(self) -> None:
        inv = self.data()["inventory"]
        items = metric_work_items(inv, self.cp["request"]["environment"])
        m = self._cov("metrics")
        m["resources_expected"] = len(items)
        self.cp["resource_plan"] = {k: len(v) for k, v in inv.items()}
        if self.cp["coverage"]["inventory"]["status"] != "CONCLUÍDO":
            self.cp["limitations"].append("Plano de cobertura baseado em inventário parcial: recursos fora das páginas lidas não serão auditados.")

    def _stage_health_check(self) -> None:
        self._data = None
        for name, tool, key in (("monitors", "search_datadog_monitors", "monitors"), ("events", "search_datadog_events", "events"),
                                ("changes", "get_change_stories", "changes"), ("incidents", "search_datadog_incidents", "incidents"),
                                ("logs", "search_datadog_logs", "logs")):
            if name in self.cp["planned_domains"]:
                self._collect("04_health_check", name, tool, {}, name, key)
                self._close_domain(name)

    def _stage_anomaly_detection(self) -> None:
        self._data = None
        items = metric_work_items(self.data()["inventory"], self.cp["request"]["environment"])
        self._data = None
        idx = self.cp["data_index"].setdefault("05_anomaly_detection", {})
        cov = self._cov("metrics")
        cov["resources_expected"] = len(items)
        workers = int(self.policy.limits["max_concurrency"])
        results: dict[str, Any] = {}
        errors: list[BaseException] = []
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(self.client.paginate, "get_datadog_metric", {"metric": it["metric"], "scope": it["scope"],
                                   "from": self.cp["window"]["start_utc"], "to": self.cp["window"]["end_utc"]}, "metrics", "series"):
                       f"{it['metric']}|{it['scope']}" for it in items}
            done = 0
            for fut in as_completed(futures):
                mk = futures[fut]
                try:
                    results[mk] = fut.result()
                except BaseException as exc:  # budget/interruption: let others finish, re-raise after
                    errors.append(exc)
                    continue
                coll = results[mk]
                idx[mk] = coll.keys
                done += 1
                if done % self.checkpoint_every == 0:
                    self._save("05_anomaly_detection")
        analyzed, no_data, failed = 0, [], []
        for mk, coll in results.items():
            if coll.errors:
                self._tool_errors(coll.errors)
            if coll.complete:
                analyzed += 1
                if not coll.items:
                    no_data.append(mk)
            else:
                failed.append(f"{mk}: {coll.reason}")
        self._part("metrics", "series", stage="05_anomaly_detection", queries=sum(len(c.keys) for c in results.values()),
                   pages=sum(c.pages_read for c in results.values()), items=sum(len(c.items) for c in results.values()),
                   complete=not failed and analyzed == len(items),
                   reason=(f"{len(failed)} consulta(s) incompleta(s): " + "; ".join(failed[:3])) if failed else None)
        cov["resources_analyzed"] = analyzed
        cov["no_data"] = no_data
        if errors:
            raise errors[0]
        self._data = None
        a = Analyzer(self.data(), self.cp["request"]["environment"], parse_iso(self.cp["window"]["end_utc"]))
        a.run()
        self.cp["findings"], self.cp["unconfirmed"], self.cp["notices"] = a.findings, a.unconfirmed, a.notices
        for mk in no_data:
            self.cp["unconfirmed"].append({"item": mk, "reason": "consulta sem série retornada (recurso sem dados ou métrica não coletada)"})
        self._close_domain("metrics")

    def _stage_deep_investigation(self) -> None:
        targets = sorted({f["service"] for f in self.cp["findings"] if f["state"] == "PROBLEMA_ATUAL" and f.get("service")
                          and f["problem_class"] in ("error_rate_regression", "latency_regression")})
        idx = self.cp["data_index"].setdefault("06_deep_investigation", {})
        for svc in targets:
            coll = self._collect("06_deep_investigation", f"spans:{svc}", "aggregate_spans", {"service": svc}, "apm", "aggregates")
            idx[f"spans:{svc}"] = coll.keys
            for f in self.cp["findings"]:
                if f.get("service") == svc and coll.items:
                    sampled = [a for a in coll.items if a.get("sample_rate", 1) < 1]
                    f.setdefault("investigation", []).append(
                        f"{len(coll.items)} agregação(ões) de spans; {len(sampled)} amostrada(s) — não usadas para taxa de erro (DAIA-001)")
        self._close_domain("apm", needed=bool(targets))

    def _stage_correlation(self) -> None:
        a = self._analyzer()
        for f in a.findings:
            if not f.get("cause_fixed"):
                f["cause"] = None  # recompute from current (possibly revalidated) changes/incidents
        a.correlate()

    def _stage_preventive_analysis(self) -> None:
        self.cp["future_risks"] = [{"resource": f["resource"], "problem_class": f["problem_class"], "summary": f["summary"]}
                                   for f in self.cp["findings"] if f["state"] == "RISCO_FUTURO"]

    def _stage_prioritization(self) -> None:
        self.cp["findings"] = prioritize(self.cp["findings"])

    def _stage_history_check(self) -> None:
        hist = self.registry.lookup(f["fingerprint"] for f in self.cp["findings"])
        for f in self.cp["findings"]:
            h = hist.get(f["fingerprint"])
            f["history"] = {"occurrences": h["occurrences"], "first_seen_utc": h["first_seen_utc"],
                            "last_seen_utc": h.get("last_seen_utc")} if h else None
            f["recurrent"] = bool(h and h["occurrences"] >= 1)

    def _stage_jira_dedup(self) -> None:
        self.cp["jira"] = []
        candidates = [f for f in self.cp["findings"] if f["severity"] in ("P0", "P1", "P2")]
        if "jira" not in self.cp["planned_domains"]:
            return
        idx = self.cp["data_index"].setdefault("11_jira_dedup", {})
        for f in candidates:
            res = self.client.query("search_jira_issues", {"fingerprint": f["fingerprint"]}, "jira")
            idx[f["fingerprint"]] = [res.key]
            if not res.ok:
                self._tool_errors([{"tool": "search_jira_issues", "code": (res.error or {}).get("code"),
                                    "message": (res.error or {}).get("message"), "http_status": (res.error or {}).get("http_status")}])
                self._part("jira", f"dedup:{f['fingerprint'][-8:]}", stage="11_jira_dedup", queries=1, pages=0, items=0, complete=False,
                           reason=f"busca de duplicata falhou: {(res.error or {}).get('code')}")
                f["jira_status"] = "NÃO VERIFICADO"
                continue
            self._part("jira", f"dedup:{f['fingerprint'][-8:]}", stage="11_jira_dedup", queries=1, pages=1, items=len(res.data.get("issues", [])), complete=True, reason=None)
            issues = res.data.get("issues", [])
            if issues:
                f["jira_status"] = f"DUPLICATA de {issues[0]['key']}"
                self.cp["jira"].append({"action": "linked_existing", "fingerprint": f["fingerprint"], "issue_key": issues[0]["key"]})
            else:
                f["jira_status"] = "SEM DUPLICATA"
        self._close_domain("jira", needed=bool(candidates))

    def _stage_human_guides(self) -> None:
        window = f"{self.cp['window']['start_utc']} → {self.cp['window']['end_utc']}"
        for f in self.cp["findings"]:
            f["procedure"] = procedure(f)
            f["manual_navigation"] = navigation(f)
            text, errors = build_guide(f, audit_id=self.cp["audit_id"], window=window, at_utc=iso(self.now()),
                                       history=f.get("history"), jira_status=f.get("jira_status", "PROPOSTA — AGUARDANDO APROVAÇÃO"))
            path = self.store.write_report(f"guides/{f['fingerprint']}.md", text)
            self.cp["guides"][f["fingerprint"]] = {"path": str(path) if path else None, "validation_errors": errors}
            if errors:
                self.cp["limitations"].append(f"Guia de {f['resource']} reprovado na validação estrutural: {errors[:2]}")

    def _stage_activity_preparation(self) -> None:
        self.cp["proposals"] = []
        req = self.cp["request"]
        approval = req.get("jira_approval")
        can_create = req["mode"] == "on_demand" and req.get("create_approved_jira") and approval and approval.get("approved")
        if req.get("create_approved_jira") and req["mode"] == "preventive":
            self.cp["limitations"].append("Criação Jira bloqueada: execução agendada não concede permissões adicionais.")
        linked = {j["fingerprint"] for j in self.cp["jira"] if j["action"] == "linked_existing"}
        controller = JiraController(JiraConfig(mode="NIVEL_2", configured=True,
                                               authorized_projects=(approval["project"],) if can_create else ()), _JiraPort(self))
        for f in self.cp["findings"]:
            if f["severity"] not in ("P0", "P1", "P2") or f["fingerprint"] in linked:
                continue
            proposal = _proposal(f, self.cp["audit_id"])
            entry = {"fingerprint": f["fingerprint"], "status": "PROPOSTA — AGUARDANDO APROVAÇÃO", "payload": proposal.payload()}
            if can_create and f.get("jira_status") == "SEM DUPLICATA":
                res = controller.create(proposal, approval["project"],
                                        CreationApproval(approval["approval_id"], True, f["fingerprint"], approval["project"],
                                                         approval.get("approver", "?"), approval.get("scope", "")))
                mapping = {"CRIADA": "created", "CRIADA_RECONCILIADA": "reconciled", "DUPLICATA": "linked_existing"}
                action = mapping.get(res.status, "indeterminate")
                entry["status"] = res.status
                self.cp["jira"].append({"action": action, "fingerprint": f["fingerprint"],
                                        "issue_key": res.issue.issue_key if res.issue else None, "note": res.reason})
            else:
                self.cp["jira"].append({"action": "proposed", "fingerprint": f["fingerprint"], "issue_key": None})
            self.cp["proposals"].append(entry)

    def _stage_report(self) -> None:
        if not self.cp["request"].get("report"):
            self.cp["stages"]["14_report"]["status"] = "NÃO SOLICITADO"
            return
        # Rendered in _finalize so the report reflects the final status and coverage.
        self.cp["report_requested"] = True

    def _stage_progress_record(self) -> None:
        confirmed = [f for f in self.cp["findings"] if f["classification"] in ("OBSERVADO", "INFERIDO")]
        self.registry.record(self.cp["audit_id"], iso(self.now()), confirmed)
        self.store.event("progress_recorded", findings=len(confirmed))


_DOMAIN_TOOLS = {"inventory": ("search_datadog_entities",), "metrics": ("get_datadog_metric", "search_datadog_metrics"),
                 "apm": ("aggregate_spans",), "logs": ("search_datadog_logs",), "monitors": ("search_datadog_monitors",),
                 "events": ("search_datadog_events",), "changes": ("get_change_stories",), "incidents": ("search_datadog_incidents",),
                 "jira": ("search_jira_issues",)}


def _cov(planned: bool) -> dict[str, Any]:
    return {"planned": planned, "status": "PENDENTE", "parts": {}, "queries": 0, "pages": 0, "items": 0, "incomplete_parts": [],
            "reason": None, "last_collected_at": None}


def _keys(section: Any) -> list[str]:
    if not section:
        return []
    out = []
    for v in section.values():
        out.extend(v)
    return out


def _proposal(f: Mapping[str, Any], audit_id: str) -> JiraIssueProposal:
    proc = f.get("procedure") or procedure(f)
    return JiraIssueProposal(
        title=f"[DAIA][{f['severity']}][{f['environment'].upper()}] {f['resource']} — {f['problem_class']}",
        problem=f["summary"], business_context="Não verificado", priority=f["severity"],
        evidence=tuple(f"{e.get('call_id')}: {e.get('note', '')}" for e in f["evidence"]),
        cause_or_hypotheses=(f"{f['cause']['status']}: {f['cause']['description']}",),
        observed_impact=f["impact"] if f["impact"] == "observado" else "Não verificado", potential_impact="ver achado",
        human_diagnosis=tuple(s["text"] for s in proc["diagnostic_steps"]),
        resolution_options=tuple(s["text"] for s in proc["resolution_steps"]),
        risks_and_rollback=tuple(r for s in proc["resolution_steps"] for r in s["risks"]),
        datadog_links=tuple(l["url"] for l in f["links"]),
        acceptance_criteria=tuple(s["validation"] for s in proc["resolution_steps"]),
        responsible_team="Não verificado", fingerprint=f["fingerprint"], audit_id=audit_id,
        environment=f["environment"], service=f.get("service") or f["resource"], resource=f["resource"])


class _JiraPort:
    """JiraClient over the tool port. Creation is never cached; searches use fresh queries."""

    def __init__(self, orch: AuditOrchestrator):
        self.o = orch

    def _search(self, fp: str) -> list[JiraIssueSearchResult]:
        res = self.o.client.query("search_jira_issues", {"fingerprint": fp}, "jira", use_cache=False)
        if not res.ok:
            raise JiraClientError((res.error or {}).get("code"))
        return [JiraIssueSearchResult(i["key"], i["key"], i.get("url", ""), i.get("fingerprint", ""), i.get("status", ""))
                for i in res.data.get("issues", [])]

    def search_by_fingerprint(self, fp): return self._search(fp)
    def get_issue_by_fingerprint(self, fp): return self._search(fp)
    def list_projects(self): return []
    def get_issue_metadata(self, project): return {}

    def create_issue(self, project, payload):
        approval = self.o.cp["request"]["jira_approval"]
        self.o.budget.charge_query()
        raw = self.o.port("create_jira_issue", {"project": project, "summary": payload["summary"],
                                                "fingerprint": payload["description"]["fingerprint"],
                                                "description": payload["description"]["problem"], "approval_id": approval["approval_id"]})
        self.o.store.event("jira_create_attempt", ok=raw.get("ok"), code=(raw.get("error") or {}).get("code"), call_id=raw.get("call_id"))
        if raw.get("ok"):
            i = raw["data"]["issue"]
            return JiraIssueSearchResult(i["key"], i["key"], i.get("url", ""), i.get("fingerprint", ""), i.get("status", ""))
        if (raw.get("error") or {}).get("code") == "TIMEOUT":
            raise JiraTimeoutError("timeout")
        raise JiraClientError((raw.get("error") or {}).get("code"))
