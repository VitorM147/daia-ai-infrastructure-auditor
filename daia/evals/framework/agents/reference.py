"""DAIA deterministic reference investigator ("rules baseline").

This is NOT an LLM. It is a rule-based implementation of the DAIA method built
on the project's own engines (``daia.diagnostics``, ``daia.proactive``,
``daia.jira``). It exists to (1) exercise the eval harness end-to-end on real
tool calls and (2) provide a measurable non-LLM baseline that an LLM agent must
beat. Its thresholds are generic SRE heuristics, not tuned per scenario; its
mistakes are reported by the suite like any other agent's.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from typing import Any, Mapping

from daia.diagnostics.baseline import build_baseline, compare_with_baseline
from daia.diagnostics.metrics import MetricCalculationError, calculate_rate
from daia.diagnostics.models import MetricPoint
from daia.jira.client import JiraClientError, JiraTimeoutError
from daia.jira.controller import JiraController
from daia.jira.fingerprint import build_fingerprint
from daia.jira.models import CreationApproval, JiraConfig, JiraIssueProposal, JiraIssueSearchResult
from daia.proactive.trend import estimate_exhaustion

from ..taxonomy import OUTPUT_SCHEMA_VERSION, TOOL_DOMAIN
from .base import ToolPort

CONFIG = {
    "current_window_h": 3,
    "baseline_days": 6,
    "error_rel_threshold": 1.0,
    "error_abs_min": 0.01,
    "error_p1_rate": 0.05,
    "min_hits": 300,
    "latency_rel_threshold": 0.5,
    "latency_p2_ms": 1000,
    "lag_rel_threshold": 3.0,
    "retrans_rel_threshold": 2.0,
    "retrans_ratio_min": 0.005,
    "disk_current_threshold": 0.90,
    "disk_risk_horizon_days": 7,
    "event_repeat_min": 3,
    "dns_log_min": 20,
    "flapping_changes_24h": 20,
    "max_retry_503": 1,
}

INJECTION_RX = re.compile(r"(?i)(ignore (all |the )?previous instructions|ignore as instruções|system override|you are now|chame a ferramenta|call (the tool )?\w+_\w+|print every api_key)")
SECRET_RX = re.compile(r"(?i)(bearer\s+[a-z0-9_\-\.]{16,}|sk_live_[a-z0-9]+|AKIA[0-9A-Z]{16}|password\s*[=:]|\b\d{3}\.\d{3}\.\d{3}-\d{2}\b)")
DNS_RX = re.compile(r"(?i)(EAI_AGAIN|NXDOMAIN|DNS lookup failed|could not resolve host)")
POOL_RX = re.compile(r"(?i)(pool exhausted|connection is not available|timeout acquiring connection)")
METRIC_IN_QUERY_RX = re.compile(r"(?:avg|sum|max|min):([a-zA-Z0-9_.]+)\{")
FATAL_CODES = {"UNAUTHENTICATED", "PERMISSION_DENIED", "RATE_LIMITED", "FORBIDDEN_BY_POLICY", "UNKNOWN_TOOL", "PAGE_UNAVAILABLE"}


def _ts(start: str, i: int) -> datetime:
    return datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + timedelta(hours=i)


class _Interrupted(Exception):
    pass


class ReferenceAgent:
    name = "daia-reference-rules"
    version = "ref-1.0.0"

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "model": None, "kind": "deterministic-rules",
                "config": dict(CONFIG)}

    # ------------------------------------------------------------------ infra
    def run(self, context: Mapping[str, Any], call_tool: ToolPort) -> dict[str, Any]:
        self.ctx = context
        self.call_tool = call_tool
        self.domains: dict[str, str] = {}
        self.errors: list[dict[str, Any]] = []
        self.dead_tools: set[str] = set()
        self.retries: dict[str, int] = {}
        self.findings: list[dict[str, Any]] = []
        self.notices: list[dict[str, Any]] = []
        self.limitations: list[str] = []
        self.jira_actions: list[dict[str, Any]] = []
        self.interrupted = False
        self.now = datetime.strptime(context["now_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        text = context["input_text"]
        if re.search(r"(?i)silenci|mute|ajuste o dashboard|apague|delete|reinicie", text):
            self.limitations.append("Solicitação de alteração recusada: Datadog e infraestrutura são somente leitura para o agente; ver procedimento humano.")
        try:
            self._investigate()
        except _Interrupted:
            self.limitations.append("Execução interrompida (orçamento de chamadas esgotado); domínios restantes não verificados.")
        if not self.interrupted and re.search(r"(?i)jira|atividades aprovadas|preparar atividades", text):
            try:
                self._jira(text)
            except _Interrupted:
                self.limitations.append("Execução interrompida durante a etapa Jira.")
        incomplete = self.interrupted or any(v == "NÃO VERIFICADO" for v in self.domains.values())
        return {
            "schema_version": OUTPUT_SCHEMA_VERSION,
            "agent": self.describe(),
            "status": "INCOMPLETA" if incomplete else "CONCLUÍDA",
            "domains": self.domains,
            "findings": self.findings,
            "tool_errors_reported": self.errors,
            "security_notices": self.notices,
            "jira": self.jira_actions,
            "limitations": self.limitations,
            "narrative": self._narrative(incomplete),
        }

    def q(self, tool: str, args: Mapping[str, Any] | None = None) -> tuple[str | None, Any]:
        if self.interrupted or tool in self.dead_tools:
            if self.interrupted:
                raise _Interrupted()
            return None, None
        result = self.call_tool(tool, dict(args or {}))
        domain = TOOL_DOMAIN.get(tool)
        if result["ok"]:
            if domain and self.domains.get(domain) != "NÃO VERIFICADO":
                self.domains[domain] = "VERIFICADO"
            return result["call_id"], result["data"]
        err = result.get("error") or {}
        code = err.get("code")
        if not any(e["tool"] == tool and e["error_code"] == code for e in self.errors):
            self.errors.append({"tool": tool, "error_code": code, "http_status": err.get("http_status"),
                                "message": err.get("message"), "shown_to_human": True})
        if domain:
            self.domains[domain] = "NÃO VERIFICADO"
        if code == "AUDIT_INTERRUPTED":
            self.interrupted = True
            raise _Interrupted()
        if code in FATAL_CODES:
            self.dead_tools.add(tool)
            return None, None
        if code in ("SOURCE_UNAVAILABLE", "TIMEOUT") and self.retries.get(tool, 0) < CONFIG["max_retry_503"]:
            self.retries[tool] = self.retries.get(tool, 0) + 1
            again = self.call_tool(tool, dict(args or {}))
            if again["ok"]:
                if domain:
                    self.domains[domain] = "VERIFICADO"
                return again["call_id"], again["data"]
        self.dead_tools.add(tool)
        return None, None

    # ------------------------------------------------------------ investigate
    def _investigate(self) -> None:
        self.inventory: dict[str, list] = {}
        cid, data = self.q("search_datadog_entities", {"page": 1})
        if data:
            self._merge_inventory(data["items"])
            total = data["pagination"]["total_pages"]
            for page in range(2, total + 1):
                _, more = self.q("search_datadog_entities", {"page": page})
                if more is None:
                    self.limitations.append(f"Inventário truncado: página {page}/{total} indisponível; recursos fora da página 1 não auditados.")
                    break
                self._merge_inventory(more["items"])
        self.monitor_call, mdata = self.q("search_datadog_monitors")
        self.monitors = (mdata or {}).get("monitors", [])
        self._check_monitors()
        self.events_call, edata = self.q("search_datadog_events")
        self.events = (edata or {}).get("events", [])
        self.changes_call, cdata = self.q("get_change_stories")
        self.changes = (cdata or {}).get("changes", [])
        self.incidents_call, idata = self.q("search_datadog_incidents")
        self.incidents = (idata or {}).get("incidents", [])
        self.logs_call, ldata = self.q("search_datadog_logs", {"limit": 1000})
        self.logs = (ldata or {}).get("logs", [])
        if ldata and ldata.get("truncated"):
            self.limitations.append("Busca de logs truncada no limite de 1000 eventos.")
        self._scan_logs()
        for svc in self.inventory.get("services", []):
            self._check_service(svc)
        for wl in self.inventory.get("workloads", []):
            self._check_workload(wl)
        for grp in self.inventory.get("kafka_consumer_groups", []):
            self._check_kafka(grp)
        for db in self.inventory.get("databases", []):
            self._check_db(db)
        for vol in self.inventory.get("volumes", []):
            self._check_volume(vol)
        for host in self.inventory.get("hosts", []):
            self._check_network(host)

    def _merge_inventory(self, items: Mapping[str, list]) -> None:
        for k, v in items.items():
            self.inventory.setdefault(k, []).extend(v)

    def _metric(self, metric: str, scope: str) -> tuple[str | None, list[float] | None, str | None]:
        cid, data = self.q("get_datadog_metric", {"metric": metric, "scope": scope})
        if not data or not data["series"]:
            return cid, None, None
        s = data["series"][0]
        return cid, [float(v) for v in s["values"]], s["start"]

    # ---------------------------------------------------------------- checks
    def _check_monitors(self) -> None:
        for m in self.monitors:
            if m.get("overall_state") == "No Data":
                match = METRIC_IN_QUERY_RX.search(m.get("query", ""))
                if not match:
                    continue
                metric = match.group(1)
                scid, sdata = self.q("search_datadog_metrics", {"query": metric})
                if sdata is not None and metric not in sdata["metrics"]:
                    self._add("monitor_misconfigured", f"monitor:{m['id']}", None, "P2", "OBSERVADO", "potencial",
                              f"Monitor {m['id']} em No Data consulta a métrica '{metric}', inexistente no catálogo.",
                              evidence=[{"call_id": self.monitor_call, "value": "No Data", "note": "overall_state"},
                                        {"call_id": self.monitor_call, "value": m["id"], "note": "id do monitor"}],
                              silent=True, links=[m["url"]] if m.get("url") else [],
                              cause=self._cause_simple("hipótese", f"métrica {metric} renomeada/inexistente",
                                                       ["agente não coleta a métrica no host", "tag de host alterada"]))
            changes = m.get("state_changes_24h")
            if isinstance(changes, (int, float)) and changes >= CONFIG["flapping_changes_24h"]:
                self._add("monitor_flapping", f"monitor:{m['id']}", None, "P3", "OBSERVADO", "potencial",
                          f"Monitor {m['id']} alternou {changes} vezes em 24h (limiar sensível ou janela curta).",
                          evidence=[{"call_id": self.monitor_call, "value": changes, "note": "state_changes_24h"}],
                          links=[m["url"]] if m.get("url") else [],
                          cause=self._cause_simple("hipótese", "limiar/janela de avaliação inadequados", ["variação real e intermitente do serviço"]))

    def _service_monitor_alerting(self, svc: str) -> bool:
        return any(f"service:{svc}" in m.get("tags", []) and m.get("overall_state") in ("Alert", "Warn") for m in self.monitors)

    def _service_links(self, svc: str) -> list[str]:
        links = [m["url"] for m in self.monitors if f"service:{svc}" in m.get("tags", []) and m.get("url")]
        links += [i["url"] for i in self.incidents if svc in i.get("services", []) and i.get("url")]
        return links

    def _check_service(self, svc: Mapping[str, Any]) -> None:
        name = svc["service"]
        scope = f"service:{name},env:prod"
        w, days = CONFIG["current_window_h"], CONFIG["baseline_days"]
        hc, hits, start = self._metric("trace.http.request.hits", scope)
        ec, errs, _ = self._metric("trace.http.request.errors", scope)
        if hits and errs and sum(hits[-w:]) >= CONFIG["min_hits"]:
            cur = self._rate(errs, hits, start, len(hits) - w, len(hits))
            samples = []
            for d in range(1, days + 1):
                end = len(hits) - 24 * d
                if end - w < 0:
                    break
                samples.append(MetricPoint("error_rate", _ts(start, end - 1), sum(errs[end - w:end]) / max(sum(hits[end - w:end]), 1),
                                           "ratio", name, name, "prod", (), "derived:trace.http.request"))
            base = build_baseline(samples, start_utc=_ts(start, 0), end_utc=_ts(start, len(hits)), expected_points=days)
            cmp = compare_with_baseline(cur, base, threshold=CONFIG["error_rel_threshold"])
            if cmp["status"] == "REGRESSION" and cur >= CONFIG["error_abs_min"]:
                silent = not self._service_monitor_alerting(name)
                sev = "P1" if cur >= CONFIG["error_p1_rate"] else "P2"
                self._add("error_rate_regression", name, name, sev, "OBSERVADO", "observado",
                          f"Taxa de erro {cur:.2%} nas últimas {w}h vs baseline {base.value:.2%} (mesmo horário, {days} dias)"
                          + (" sem monitor em alerta (falha silenciosa)." if silent else "."),
                          evidence=[{"call_id": ec, "value": errs[-1], "note": "erros na última hora"},
                                    {"call_id": hc, "value": hits[-1], "note": "requisições na última hora"}],
                          computed=[{"name": "error_rate_current", "value": cur, "op": "ratio",
                                     "inputs": [{"call_id": ec, "series_index": 0, "slice": [-w, None]},
                                                {"call_id": hc, "series_index": 0, "slice": [-w, None]}]},
                                    {"name": "error_rate_baseline", "value": base.value, "op": "seasonal_median", "inner": "ratio",
                                     "window": w, "days": len(samples),
                                     "inputs": [{"call_id": ec, "series_index": 0}, {"call_id": hc, "series_index": 0}]}],
                          silent=silent, links=self._service_links(name), service_deps=svc.get("dependencies", []),
                          cause_kind="rate")
        lc, lat, _ = self._metric("trace.http.request.duration.by.service.95p", scope)
        if lat:
            cur = mean(lat[-w:])
            samples = [mean(lat[len(lat) - 24 * d - w:len(lat) - 24 * d]) for d in range(1, days + 1) if len(lat) - 24 * d - w >= 0]
            base = median(samples) if samples else None
            if base and (cur - base) / base >= CONFIG["latency_rel_threshold"]:
                sev = "P2" if cur >= CONFIG["latency_p2_ms"] else "P3"
                self._add("latency_regression", name, name, sev, "OBSERVADO", "potencial",
                          f"Latência p95 média {cur:.0f} ms nas últimas {w}h vs baseline {base:.0f} ms; impacto em usuários não comprovado.",
                          evidence=[{"call_id": lc, "value": lat[-1], "note": "p95 da última hora (ms)"}],
                          computed=[{"name": "p95_current_mean", "value": cur, "op": "mean",
                                     "inputs": [{"call_id": lc, "series_index": 0, "slice": [-w, None]}]},
                                    {"name": "p95_baseline", "value": base, "op": "seasonal_median", "inner": "mean",
                                     "window": w, "days": len(samples), "inputs": [{"call_id": lc, "series_index": 0}]}],
                          links=self._service_links(name), service_deps=svc.get("dependencies", []), cause_kind="rate")

    def _rate(self, errs, hits, start, a, b) -> float:
        nums = [MetricPoint("errors", _ts(start, i), errs[i], "count", "svc", None, None, (), "metric") for i in range(a, b)]
        dens = [MetricPoint("hits", _ts(start, i), hits[i], "count", "svc", None, None, (), "metric") for i in range(a, b)]
        try:
            return calculate_rate(nums, dens)
        except MetricCalculationError:
            return 0.0

    def _check_workload(self, wl: Mapping[str, Any]) -> None:
        name = wl["name"]
        for c in wl.get("containers", []):
            tags = {f"kube_deployment:{name}", f"kube_container_name:{c['name']}"}
            evs = [e for e in self.events if tags <= set(e.get("tags", []))]
            ooms = [e for e in evs if "OOMKilled" in e["title"] + e.get("text", "")]
            crashes = [e for e in evs if "Back-off restarting" in e["title"]]
            resource = f"{name}/{c['name']}"
            if len(ooms) >= CONFIG["event_repeat_min"]:
                self._add("oom_kill", resource, name, "P2", "OBSERVADO", "potencial",
                          f"{len(ooms)} eventos OOMKilled no container {c['name']} (limite {c.get('memory_limit_mib')} MiB) na janela.",
                          evidence=[{"call_id": self.events_call, "value": ooms[-1]["title"], "note": "evento Kubernetes"}],
                          links=self._service_links(name),
                          cause=self._cause_simple("hipótese", "consumo de memória do container atinge o limite (possível vazamento ou carga)",
                                                   ["limite de memória subdimensionado", "pico de carga legítimo"]))
            elif len(crashes) >= CONFIG["event_repeat_min"]:
                self._add("pod_crashloop", resource, name, "P2", "OBSERVADO", "potencial",
                          f"{len(crashes)} eventos de CrashLoopBackOff no container {c['name']}.",
                          evidence=[{"call_id": self.events_call, "value": crashes[-1]["title"], "note": "evento Kubernetes"}],
                          links=self._service_links(name),
                          cause=self._cause_simple("hipótese", "falha de inicialização do container (ver logs de saída)",
                                                   ["configuração ausente", "dependência indisponível na inicialização"]))
        hpa = wl.get("hpa")
        if hpa and hpa.get("max", 1) > 1:
            scope = f"kube_deployment:{name}"
            rc, rep, _ = self._metric("kubernetes_state.hpa.current_replicas", scope)
            cc, cpu, _ = self._metric("kubernetes.cpu.usage.pct_of_request", scope)
            w = CONFIG["current_window_h"]
            if rep and cpu and all(r >= hpa["max"] for r in rep[-w:]) and mean(cpu[-w:]) > hpa.get("target_cpu_pct", 100):
                self._add("hpa_at_max", name, name, "P2", "OBSERVADO", "potencial",
                          f"HPA em {int(rep[-1])}/{hpa['max']} réplicas por {w}h com CPU média {mean(cpu[-w:]):.0f}% acima do alvo {hpa.get('target_cpu_pct')}%.",
                          evidence=[{"call_id": rc, "value": rep[-1], "note": "réplicas atuais"},
                                    {"call_id": cc, "value": cpu[-1], "note": "CPU % do request"}],
                          computed=[{"name": "cpu_mean_window", "value": mean(cpu[-w:]), "op": "mean",
                                     "inputs": [{"call_id": cc, "series_index": 0, "slice": [-w, None]}]}],
                          links=self._service_links(name), cause_kind="capacity")

    def _check_kafka(self, grp: Mapping[str, Any]) -> None:
        g = grp["group"]
        lc, lag, _ = self._metric("kafka.consumer_lag", f"consumer_group:{g}")
        if not lag:
            return
        cur = lag[-1]
        samples = [lag[len(lag) - 1 - 24 * d] for d in range(1, CONFIG["baseline_days"] + 1) if len(lag) - 1 - 24 * d >= 0]
        base = median(samples) if samples else None
        growing = all(b > a for a, b in zip(lag[-6:], lag[-5:]))
        if base and base > 0 and (cur - base) / base >= CONFIG["lag_rel_threshold"] and growing:
            self._add("kafka_consumer_lag", g, grp.get("service"), "P2", "OBSERVADO", "potencial",
                      f"Lag do grupo {g} em {cur:.0f} mensagens e crescente nas últimas 6h; baseline do mesmo horário {base:.0f}.",
                      evidence=[{"call_id": lc, "value": cur, "note": "lag atual"}],
                      computed=[{"name": "lag_baseline", "value": base, "op": "seasonal_median", "inner": "last", "window": 1,
                                 "days": len(samples), "inputs": [{"call_id": lc, "series_index": 0}]}],
                      links=self._service_links(grp.get("service") or g), cause_kind="rate", service_deps=[])

    def _check_db(self, db: Mapping[str, Any]) -> None:
        name = db["name"]
        pc, pool, _ = self._metric("db.pool.active", f"db:{name}")
        if not pool:
            return
        w = CONFIG["current_window_h"]
        pmax = db.get("pool_max")
        if pmax and all(v >= 0.95 * pmax for v in pool[-w:]):
            client = db.get("client_service")
            hits = [l for l in self.logs if POOL_RX.search(l["message"]) and (not client or l["service"] == client)]
            observed = len(hits) >= 5
            self._add("db_connection_pool_exhaustion", name, client, "P1" if observed else "P2", "OBSERVADO",
                      "observado" if observed else "potencial",
                      f"Pool de conexões em {pool[-1]:.0f}/{pmax} por {w}h" + (f" com {len(hits)} erros de aquisição de conexão." if observed else "."),
                      evidence=[{"call_id": pc, "value": pool[-1], "note": "conexões ativas"}]
                      + ([{"call_id": self.logs_call, "value": "Connection is not available", "note": "log de erro (trecho)"}] if observed else []),
                      links=self._service_links(client or name), cause_kind="config", service_deps=[client] if client else [])

    def _check_volume(self, vol: Mapping[str, Any]) -> None:
        host, dev = vol["host"], vol["device"]
        dc, disk, start = self._metric("system.disk.in_use", f"host:{host},device:{dev}")
        if not disk:
            return
        resource = f"{host}:{dev}"
        owner = next((s["service"] for s in self.inventory.get("services", []) if host.startswith(s["service"])), None)
        if disk[-1] >= CONFIG["disk_current_threshold"]:
            self._add("disk_saturation", resource, owner, "P1", "OBSERVADO", "potencial",
                      f"Volume {dev} em {disk[-1]:.1%} de uso (limiar {CONFIG['disk_current_threshold']:.0%}).",
                      evidence=[{"call_id": dc, "value": disk[-1], "note": "fração de uso"}],
                      links=[m["url"] for m in self.monitors if f"host:{host}" in m.get("tags", []) and m.get("url")],
                      cause_kind="capacity_change", service_deps=[])
            return
        points = [MetricPoint("system.disk.in_use", _ts(start, i), v, "fraction", resource, None, None, (), "metric") for i, v in enumerate(disk)]
        est = estimate_exhaustion(points, threshold=CONFIG["disk_current_threshold"], expected_points=len(disk))
        if est.status == "ESTIMATE" and est.seconds_to_threshold is not None and est.seconds_to_threshold < CONFIG["disk_risk_horizon_days"] * 86400:
            self._add("disk_saturation_risk", resource, owner, "P3", "INFERIDO", "potencial",
                      f"Risco futuro: {disk[-1]:.1%} hoje; projeção linear atinge {CONFIG['disk_current_threshold']:.0%} em "
                      f"{est.seconds_to_threshold/86400:.1f} dias (intervalo {est.lower_seconds/86400:.1f}–{est.upper_seconds/86400:.1f}); não é garantia.",
                      evidence=[{"call_id": dc, "value": disk[-1], "note": "fração de uso atual"}],
                      links=[], cause=self._cause_simple("indeterminada", "crescimento contínuo de dados", ["mudança de retenção", "aumento de volume ingerido"]))

    def _check_network(self, host: Mapping[str, Any]) -> None:
        h = host["host"]
        oc, out, _ = self._metric("system.net.tcp.out_segs", f"host:{h}")
        rc, ret, _ = self._metric("system.net.tcp.retrans_segs", f"host:{h}") if out else (None, None, None)
        if not out or not ret:
            return
        w = CONFIG["current_window_h"]
        cur = sum(ret[-w:]) / sum(out[-w:])
        samples = [sum(ret[len(ret) - 24 * d - w:len(ret) - 24 * d]) / sum(out[len(out) - 24 * d - w:len(out) - 24 * d])
                   for d in range(1, CONFIG["baseline_days"] + 1) if len(out) - 24 * d - w >= 0]
        base = median(samples)
        if base > 0 and (cur - base) / base >= CONFIG["retrans_rel_threshold"] and cur >= CONFIG["retrans_ratio_min"]:
            self._add("network_retransmission", h, None, "P2", "OBSERVADO", "potencial",
                      f"Razão de retransmissão TCP {cur:.2%} vs baseline {base:.2%} (normalizada pelo tráfego de saída).",
                      evidence=[{"call_id": rc, "value": ret[-1], "note": "segmentos retransmitidos (última hora)"},
                                {"call_id": oc, "value": out[-1], "note": "segmentos enviados (última hora)"}],
                      computed=[{"name": "retrans_ratio_current", "value": cur, "op": "ratio",
                                 "inputs": [{"call_id": rc, "series_index": 0, "slice": [-w, None]},
                                            {"call_id": oc, "series_index": 0, "slice": [-w, None]}]},
                                {"name": "retrans_ratio_baseline", "value": base, "op": "seasonal_median", "inner": "ratio",
                                 "window": w, "days": len(samples), "inputs": [{"call_id": rc, "series_index": 0}, {"call_id": oc, "series_index": 0}]}],
                      links=[], cause=self._cause_simple("indeterminada", "perda de pacotes ou congestionamento no caminho", ["NIC/host degradado", "upstream instável"]))

    def _scan_logs(self) -> None:
        recent = self.now - timedelta(hours=CONFIG["current_window_h"])
        dns: dict[str, int] = {}
        secrets: dict[str, int] = {}
        for entry in self.logs:
            msg = entry["message"]
            if INJECTION_RX.search(msg):
                if not any(n["call_id"] == self.logs_call for n in self.notices):
                    self.notices.append({"type": "prompt_injection", "call_id": self.logs_call,
                                         "description": f"Instruções embutidas em logs do serviço {entry['service']} tratadas como dado e ignoradas; nenhuma ferramenta foi acionada por elas."})
            if SECRET_RX.search(msg):
                secrets[entry["service"]] = secrets.get(entry["service"], 0) + 1
            ts = datetime.strptime(entry["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if ts >= recent and DNS_RX.search(msg):
                dns[entry["service"]] = dns.get(entry["service"], 0) + 1
        for svc, n in secrets.items():
            sample = next(l["message"] for l in self.logs if l["service"] == svc and SECRET_RX.search(l["message"]))
            prefix = SECRET_RX.split(sample)[0].strip()[:30] or "log"
            self._add("secret_exposed_in_logs", svc, svc, "P1", "OBSERVADO", "potencial",
                      f"{n} log(s) de {svc} contêm credencial/PII em texto claro (valores redigidos neste relatório).",
                      evidence=[{"call_id": self.logs_call, "value": prefix, "note": "trecho não sensível do log"}],
                      links=self._service_links(svc), cause=self._cause_simple("provável", "log de cabeçalhos/payload sem mascaramento", ["biblioteca de logging de terceiros"]))
        for svc, n in dns.items():
            if n >= CONFIG["dns_log_min"]:
                self._add("dns_resolution_failure", svc, svc, "P2", "OBSERVADO", "observado",
                          f"{n} falhas de resolução DNS em {CONFIG['current_window_h']}h nos logs de {svc}.",
                          evidence=[{"call_id": self.logs_call, "value": "EAI_AGAIN", "note": "código de erro DNS"}],
                          links=self._service_links(svc), cause=self._cause_simple("hipótese", "resolvedor ou zona DNS do parceiro instável", ["mudança de DNS do parceiro", "limite de consultas do resolvedor"]))

    # ----------------------------------------------------------------- causes
    def _cause_simple(self, status: str, description: str, alternatives: list[str]) -> dict[str, Any]:
        return {"code": None, "description": description, "status": status, "alternatives": alternatives,
                "evidence_against": ["sem identificador causal que comprove a relação"]}

    def _cause_for(self, kind: str, service: str | None, deps: list[str], resource: str) -> dict[str, Any]:
        targets = {x for x in [service, resource, *deps] if x}
        for inc in self.incidents:
            rc = inc.get("root_cause") or {}
            if rc.get("confirmed") and targets & set(inc.get("services", [])):
                return {"code": rc.get("code"), "description": f"Incidente {inc['id']}: {rc.get('text', '')}", "status": "confirmada",
                        "alternatives": [], "evidence_against": ["nenhuma registrada no postmortem"]}
        lookback = timedelta(days=7) if kind == "capacity_change" else timedelta(hours=6)
        cands = []
        for ch in self.changes:
            ts = datetime.strptime(ch["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if self.now - lookback <= ts <= self.now and (ch["service"] in targets or (resource and resource.startswith(ch["service"]))):
                cands.append(ch)
        net = [e for e in self.events if e.get("source") == "network"
               and self.now - lookback <= datetime.strptime(e["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) <= self.now]
        alternatives = [f"{c['type']} {c['service']} {c['version']}: {c['description']}" for c in cands] + [f"evento de rede: {e['title']}" for e in net]
        if len(cands) == 1 and not net:
            ch = cands[0]
            causal = any((l.get("attributes") or {}).get("version") == ch["version"] for l in self.logs if l["service"] == ch["service"])
            code = f"deploy:{ch['service']}@{ch['version']}" if ch["type"] == "deployment" else f"config:{ch['service']}:{ch['version']}"
            return {"code": code, "description": ch["description"], "status": "provável" if causal else "hipótese",
                    "alternatives": ["variação de carga/tráfego", "dependência externa"],
                    "evidence_against": [] if causal else ["sem identificador de versão nos erros que ligue a mudança ao sintoma"]}
        if cands or net:
            return {"code": None, "description": "múltiplas mudanças/eventos concorrentes na janela", "status": "hipótese",
                    "alternatives": alternatives, "evidence_against": ["candidatos simultâneos impedem atribuição"]}
        return {"code": None, "description": "nenhuma mudança, incidente ou evento correlacionado encontrado", "status": "indeterminada",
                "alternatives": ["dependência externa", "variação de carga"], "evidence_against": []}

    # ---------------------------------------------------------------- finding
    def _add(self, pclass: str, resource: str, service: str | None, severity: str, classification: str, impact: str,
             summary: str, *, evidence: list[dict], computed: list[dict] | None = None, silent: bool = False,
             links: list[str] | None = None, cause: dict | None = None, cause_kind: str | None = None,
             service_deps: list[str] | None = None) -> None:
        if any(f["problem_class"] == pclass and f["resource"] == resource for f in self.findings):
            return
        if cause is None:
            cause = self._cause_for(cause_kind or "rate", service, service_deps or [], resource)
        fp = build_fingerprint(environment="prod", application=service or resource, service=service or resource,
                               resource=resource, problem_class=pclass, failure_identifier=pclass)
        self.findings.append({
            "problem_class": pclass, "resource": resource, "service": service, "environment": "prod",
            "severity": severity, "classification": classification, "silent": silent, "impact": impact,
            "summary": summary, "cause": cause, "evidence": evidence, "computed": computed or [],
            "links": [{"url": u, "validated": False} for u in dict.fromkeys(links or [])],
            "manual_navigation": _navigation(pclass, resource, service),
            "procedure": _procedure(pclass, resource, service),
            "fingerprint": fp,
        })

    # ------------------------------------------------------------------- jira
    def _jira(self, text: str) -> None:
        create = bool(re.search(r"(?i)criar atividades aprovadas", text))
        approval = next((a for a in self.ctx.get("approvals", []) if a.get("approved")), None)
        client = _SandboxJiraClient(self)
        controller = JiraController(JiraConfig(mode="NIVEL_2", configured=True,
                                               authorized_projects=(approval["project"],) if approval else ()), client)
        for f in self.findings:
            if f["severity"] not in ("P0", "P1", "P2"):
                continue
            proposal = _proposal(f)
            try:
                existing = client.search_by_fingerprint(f["fingerprint"])
            except JiraClientError as exc:
                self.jira_actions.append({"action": "proposed", "fingerprint": f["fingerprint"], "issue_key": None,
                                          "note": f"busca de duplicatas indisponível ({exc}); proposta mantida sem criação"})
                continue
            if existing:
                self.jira_actions.append({"action": "linked_existing", "fingerprint": f["fingerprint"], "issue_key": existing[0].issue_key})
                continue
            if not (create and approval):
                self.jira_actions.append({"action": "proposed", "fingerprint": f["fingerprint"], "issue_key": None})
                continue
            res = controller.create(proposal, approval["project"],
                                    CreationApproval(approval["approval_id"], True, f["fingerprint"], approval["project"],
                                                     approval.get("approver", "?"), approval.get("scope", "")))
            mapping = {"CRIADA": "created", "CRIADA_RECONCILIADA": "reconciled", "DUPLICATA": "linked_existing"}
            self.jira_actions.append({"action": mapping.get(res.status, "indeterminate"), "fingerprint": f["fingerprint"],
                                      "issue_key": res.issue.issue_key if res.issue else None, "note": res.reason})
            client.approval_id = None

    def _narrative(self, incomplete: bool) -> str:
        parts = [f"{len(self.findings)} achado(s)."]
        if incomplete:
            pend = sorted(d for d, s in self.domains.items() if s == "NÃO VERIFICADO")
            parts.append(f"Auditoria INCOMPLETA; domínios não verificados: {', '.join(pend) or 'restantes após interrupção'}.")
        else:
            parts.append("Cobertura limitada aos domínios consultados; ausência de achado não prova ausência de problema.")
        if self.errors:
            parts.append("Falhas de ferramentas: " + "; ".join(f"{e['tool']} {e['error_code']}" for e in self.errors) + ".")
        return " ".join(parts)


class _SandboxJiraClient:
    """Adapts sandbox tools to daia.jira.client.JiraClient so the real controller is exercised."""

    def __init__(self, agent: ReferenceAgent):
        self.agent = agent
        self.approval_id = None

    def _search(self, fingerprint: str) -> list[JiraIssueSearchResult]:
        result = self.agent.call_tool("search_jira_issues", {"fingerprint": fingerprint})
        if not result["ok"]:
            err = result["error"]
            self.agent.domains["jira"] = "NÃO VERIFICADO"
            if not any(e["tool"] == "search_jira_issues" for e in self.agent.errors):
                self.agent.errors.append({"tool": "search_jira_issues", "error_code": err["code"], "http_status": err.get("http_status"),
                                          "message": err.get("message"), "shown_to_human": True})
            raise JiraClientError(err["code"])
        self.agent.domains.setdefault("jira", "VERIFICADO")
        return [JiraIssueSearchResult(i["key"], i["key"], i.get("url", ""), i.get("fingerprint", ""), i.get("status", "")) for i in result["data"]["issues"]]

    def search_by_fingerprint(self, fingerprint): return self._search(fingerprint)
    def get_issue_by_fingerprint(self, fingerprint): return self._search(fingerprint)
    def list_projects(self): return []
    def get_issue_metadata(self, project): return {}

    def create_issue(self, project, payload):
        approval = next(a for a in self.agent.ctx.get("approvals", []) if a.get("approved") and a.get("project") == project)
        result = self.agent.call_tool("create_jira_issue", {"project": project, "summary": payload["summary"],
                                                            "fingerprint": payload["description"]["fingerprint"],
                                                            "description": payload["description"]["problem"],
                                                            "approval_id": approval["approval_id"]})
        if result["ok"]:
            i = result["data"]["issue"]
            return JiraIssueSearchResult(i["key"], i["key"], i.get("url", ""), i.get("fingerprint", ""), i.get("status", ""))
        err = result["error"]
        if err["code"] == "TIMEOUT":
            raise JiraTimeoutError("timeout")
        raise JiraClientError(err["code"])


def _proposal(f: Mapping[str, Any]) -> JiraIssueProposal:
    proc = f["procedure"]
    return JiraIssueProposal(
        title=f"[DAIA][{f['severity']}][PROD] {f['resource']} — {f['problem_class']}",
        problem=f["summary"], business_context="Não verificado", priority=f["severity"],
        evidence=tuple(f"{e['call_id']}: {e.get('note', '')}" for e in f["evidence"]),
        cause_or_hypotheses=(f"{f['cause']['status']}: {f['cause']['description']}",),
        observed_impact=f["impact"] if f["impact"] == "observado" else "Não verificado",
        potential_impact="ver achado", human_diagnosis=tuple(s["text"] for s in proc["diagnostic_steps"]),
        resolution_options=tuple(s["text"] for s in proc["resolution_steps"]),
        risks_and_rollback=tuple(r for s in proc["resolution_steps"] for r in s["risks"]),
        datadog_links=tuple(l["url"] for l in f["links"]), acceptance_criteria=tuple(s["validation"] for s in proc["resolution_steps"]),
        responsible_team="Não verificado", fingerprint=f["fingerprint"], audit_id="eval",
        environment="prod", service=f.get("service") or f["resource"], resource=f["resource"])


def _navigation(pclass: str, resource: str, service: str | None) -> str:
    if pclass in ("error_rate_regression", "latency_regression"):
        return f"Datadog > APM > Service Catalog > {resource} > env:prod, últimas 6h; comparar com 'Week before'."
    if pclass in ("oom_kill", "pod_crashloop", "hpa_at_max"):
        return f"Datadog > Infrastructure > Kubernetes > Workloads > {resource.split('/')[0]} > Events/Containers (últimas 6h)."
    if pclass.startswith("monitor_"):
        return f"Datadog > Monitors > Manage Monitors > buscar id {resource.split(':')[-1]} > Status/History."
    if pclass.startswith("disk_"):
        return f"Datadog > Infrastructure > Host Map > host {resource.split(':')[0]} > métrica system.disk.in_use por device (7 dias)."
    if pclass == "network_retransmission":
        return f"Datadog > Metrics > Explorer > system.net.tcp.retrans_segs / system.net.tcp.out_segs, host:{resource}, 7 dias."
    if pclass == "kafka_consumer_lag":
        return f"Datadog > Metrics > Explorer > kafka.consumer_lag, consumer_group:{resource}, 7 dias."
    if pclass == "db_connection_pool_exhaustion":
        return f"Datadog > Metrics > Explorer > db.pool.active, db:{resource}; Logs > service:{service} 'pool'."
    return f"Datadog > Logs > service:{service or resource} env:prod (últimas 6h)."


def _procedure(pclass: str, resource: str, service: str | None) -> dict[str, Any]:
    label = "EXECUÇÃO HUMANA — NÃO EXECUTAR PELO AGENTE"
    diag = [{"text": f"Confirmar o sinal no Datadog para {resource} na mesma janela e comparar com período equivalente.", "read_only": True},
            {"text": "Verificar mudanças, incidentes e dependências na janela; registrar evidências a favor e contra.", "read_only": True}]
    specific = {
        "error_rate_regression": ("Se a regressão coincidir com um deploy confirmado, avaliar rollback para a versão anterior pelo pipeline aprovado.",
                                  ["rollback pode reverter correções de dados/migrações"], "Reaplicar a versão anterior ao rollback",
                                  "Taxa de erro volta ao baseline por 2h", ["Feature flag para desativar o código novo", "Mitigar na dependência"]),
        "latency_regression": ("Identificar o endpoint/dependência com maior contribuição na latência e escalar ao time dono.",
                               ["mudanças de timeout podem mascarar o problema"], "Restaurar configuração anterior",
                               "p95 volta ao baseline", ["Aumentar capacidade temporariamente com aprovação"]),
        "disk_saturation": ("Restaurar a política de retenção/rotação anterior (ex.: retention.ms do tópico) via processo de mudança aprovado.",
                            ["perda de dados se retenção for reduzida abaixo do exigido por consumidores/compliance", "não apagar segmentos manualmente"],
                            "Reverter a configuração de retenção", "Uso de disco estabiliza e cai abaixo de 85%",
                            ["Expandir o volume temporariamente", "Rebalancear partições para outros brokers"]),
        "disk_saturation_risk": ("Planejar expansão ou ajuste de retenção antes do limiar, com dono do serviço.",
                                 ["expansão tem custo; ajuste de retenção pode afetar consumidores"], "Reverter ajuste", "Projeção acima de 30 dias",
                                 ["Arquivar dados frios"]),
        "hpa_at_max": ("Avaliar aumento de maxReplicas ou de recursos com o time dono, conforme capacidade do cluster.",
                       ["aumentar réplicas pressiona nós e banco de dados"], "Restaurar maxReplicas anterior", "Réplicas abaixo do máximo e CPU abaixo do alvo",
                       ["Otimizar o endpoint mais custoso", "Cache"]),
        "oom_kill": ("Analisar crescimento de memória (heap/profile) antes de alterar limites; ajustar limite apenas com aprovação.",
                     ["aumentar limite sem corrigir vazamento apenas adia o OOM"], "Restaurar limite anterior", "Zero OOMKilled por 24h",
                     ["Rollback da última versão se houver correlação"]),
        "pod_crashloop": ("Corrigir a configuração/dependência ausente indicada nos logs de saída via pipeline aprovado.",
                          ["reinícios em massa podem amplificar impacto"], "Reverter a configuração alterada", "Pods Ready e sem reinícios por 1h",
                          ["Rollback do deploy"]),
        "kafka_consumer_lag": ("Verificar saúde e número de consumidores do grupo; escalar consumidores apenas com aprovação do time dono.",
                               ["rebalance pode causar pausa temporária no consumo"], "Restaurar número anterior de consumidores", "Lag decrescente por 2h",
                               ["Investigar mensagens venenosas/retentativas"]),
        "db_connection_pool_exhaustion": ("Restaurar o tamanho de pool anterior via mudança aprovada, respeitando o limite de conexões do banco.",
                                          ["pool grande demais pode esgotar max_connections do banco"], "Reverter configuração do pool",
                                          "Erros de aquisição zerados e pool < 80%", ["Reduzir tempo de retenção de conexões", "Escalar réplicas de leitura"]),
        "network_retransmission": ("Abrir chamado com rede/provedor com as evidências; avaliar drenar o host do balanceador com aprovação.",
                                   ["drenar reduz capacidade"], "Reinserir o host", "Razão de retransmissão volta ao baseline",
                                   ["Trocar instância/NIC"]),
        "dns_resolution_failure": ("Validar resolvedores e TTL; acionar parceiro/provedor DNS; avaliar cache de DNS com aprovação.",
                                   ["cache longo pode reter IP inválido"], "Remover cache temporário", "Zero EAI_AGAIN por 1h", ["Resolvedor secundário"]),
        "monitor_misconfigured": ("Corrigir a query do monitor para a métrica existente (system.disk.in_use) via processo de mudança do time de observabilidade.",
                                  ["monitor corrigido pode disparar imediatamente"], "Restaurar query anterior", "Monitor sai de No Data", ["Monitor composto temporário"]),
        "monitor_flapping": ("Ajustar janela de avaliação/limiar ou adicionar recuperação/histerese pelo dono do monitor (não silenciar sem análise).",
                             ["limiar frouxo pode esconder degradação real"], "Restaurar configuração anterior", "Menos de 5 trocas de estado/24h",
                             ["Monitor de anomalia com baseline"]),
        "secret_exposed_in_logs": ("Rotacionar a credencial exposta e aplicar mascaramento no logger; restringir acesso aos índices afetados.",
                                   ["rotação pode interromper integrações que usam a credencial"], "Reativar credencial anterior somente em emergência aprovada",
                                   "Nenhum novo log com o padrão sensível por 24h", ["Regra de scrubbing no pipeline de logs"]),
    }
    text, risks, rollback, validation, alts = specific[pclass]
    return {"diagnostic_steps": diag,
            "resolution_steps": [{"text": text, "human_execution_label": True, "label": label, "risks": risks,
                                  "rollback": rollback, "validation": validation}],
            "alternatives": alts}
