"""Command line for audits (on demand or triggered by an authorised external scheduler).

  python -m daia.orchestration.cli start --environment prod --source export:evidencias.json [--report]
  python -m daia.orchestration.cli start --environment prod --source sandbox:inc-014-partial-audit
  python -m daia.orchestration.cli start ... --mode preventive --trigger-id cron-diario --requested-by svc-daia-scheduler
  python -m daia.orchestration.cli resume <audit_id> --source <mesma fonte>
  python -m daia.orchestration.cli status <audit_id>
  python -m daia.orchestration.cli report <audit_id>      # relatório sob demanda em daia/reports/
  python -m daia.orchestration.cli list

Exit codes: 0 CONCLUÍDA · 4 INCOMPLETA · 1 erro de uso/política.
A scheduled run uses the same read-only credentials and policy; scheduling grants no extra permission.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .limits import LimitPolicy, LimitPolicyError, ScopeApproval
from .orchestrator import AuditOrchestrator, AuditRequest
from .presentation import human_summary, render_report
from .store import AUDITS_DIR, AuditStore, FindingRegistry, list_audits

DAIA_DIR = Path(__file__).resolve().parent.parent
PRODUCTION_POLICY = DAIA_DIR / "config" / "tool-allowlist.json"


def build_source(spec: str):
    """Return (tool_port, clock_now or None). Live MCP/API ports plug in here (see README)."""
    from daia.evals.framework.sandbox import POLICY_PATH, Sandbox
    kind, _, value = spec.partition(":")
    if kind == "sandbox":
        from daia.evals.framework.dataset import load_dataset
        scenario = load_dataset().by_id(value)
        now = datetime.strptime(scenario["input"]["now_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return Sandbox(scenario, policy_path=POLICY_PATH).call, now
    if kind == "export":
        data = json.loads(Path(value).read_text(encoding="utf-8"))
        telemetry = data.get("telemetry", data)
        now_s = data.get("collected_until_utc") or data.get("now_utc")
        if not now_s:
            raise SystemExit("exportação sem 'collected_until_utc': informe a janela da coleta (não há valor implícito)")
        scenario = {"scenario_id": Path(value).stem, "input": {"text": "", "now_utc": now_s, "environment": data.get("environment", "")},
                    "telemetry": telemetry, "faults": [], "limits": {}}
        now = datetime.strptime(now_s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return Sandbox(scenario, policy_path=PRODUCTION_POLICY).call, now
    raise SystemExit(f"fonte desconhecida: {spec} (use sandbox:<cenário> ou export:<arquivo.json>)")


def _approval(value: str | None) -> ScopeApproval | None:
    if not value:
        return None
    parts = [p.strip() for p in value.split(",", 3)]
    if len(parts) != 4:
        raise SystemExit("--approve-expansion espera 'aprovador,id-aprovacao,AAAA-MM-DDTHH:MM:SSZ,motivo'")
    return ScopeApproval(approver=parts[0], approval_id=parts[1], approved_at_utc=parts[2], reason=parts[3])


def _limits(values: list[str] | None) -> dict[str, float]:
    out = {}
    for v in values or []:
        k, _, n = v.partition("=")
        out[k.strip()] = float(n)
    return out


def _print(cp: dict[str, Any]) -> int:
    s = human_summary(cp)
    print(json.dumps({k: s[k] for k in ("audit_id", "status", "criteria_unmet", "pending", "next_steps")}, ensure_ascii=False, indent=1))
    print(f"\nachados: {len(s['identified'])} · não confirmados: {len(s['unconfirmed'])} · riscos futuros: {len(s['future_risks'])} · "
          f"propostas Jira: {len(s['jira_proposals'])} · consumo: {s['budget_used']}")
    return 0 if cp["status"] == "CONCLUÍDA" else 4


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="daia-audit")
    p.add_argument("--root", default=str(AUDITS_DIR), help="diretório de checkpoints")
    sub = p.add_subparsers(dest="cmd", required=True)
    st = sub.add_parser("start")
    st.add_argument("--environment", required=True)
    st.add_argument("--source", required=True)
    st.add_argument("--window-hours", type=float)
    st.add_argument("--domains")
    st.add_argument("--mode", choices=["on_demand", "preventive"], default="on_demand")
    st.add_argument("--trigger-id")
    st.add_argument("--requested-by")
    st.add_argument("--report", action="store_true")
    st.add_argument("--audit-id")
    st.add_argument("--limit", action="append", help="limite=valor (redução livre; ampliação exige --approve-expansion)")
    st.add_argument("--approve-expansion")
    rs = sub.add_parser("resume")
    rs.add_argument("audit_id")
    rs.add_argument("--source", required=True)
    rs.add_argument("--limit", action="append")
    rs.add_argument("--approve-expansion")
    for name in ("status", "report"):
        x = sub.add_parser(name)
        x.add_argument("audit_id")
    sub.add_parser("list")
    a = p.parse_args(argv)
    root = Path(a.root)
    try:
        if a.cmd == "start":
            port, now = build_source(a.source)
            req = AuditRequest(environment=a.environment, window_hours=a.window_hours,
                               domains=a.domains.split(",") if a.domains else None, mode=a.mode, report=a.report,
                               trigger={"type": "scheduler" if a.mode == "preventive" else "manual",
                                        "id": a.trigger_id, "requested_by": a.requested_by})
            policy = LimitPolicy.load()
            approval = _approval(a.approve_expansion)
            if a.limit:
                policy = policy.with_overrides(_limits(a.limit), approval)
            from .collector import utc_now
            audit_id = a.audit_id or AuditOrchestrator.new_audit_id(req, (now or utc_now()))
            orch = AuditOrchestrator(port, AuditStore(audit_id, root=root), policy=policy, registry=FindingRegistry(),
                                     now=(lambda: now) if now else utc_now)
            return _print(orch.start(req, approval))
        if a.cmd == "resume":
            port, now = build_source(a.source)
            from .collector import utc_now
            orch = AuditOrchestrator(port, AuditStore(a.audit_id, root=root), registry=FindingRegistry(),
                                     now=(lambda: now) if now else utc_now)
            return _print(orch.resume(policy_overrides=_limits(a.limit) or None, scope_approval=_approval(a.approve_expansion)))
        if a.cmd == "status":
            cp = AuditStore(a.audit_id, root=root).load_checkpoint()
            if not cp:
                raise SystemExit("auditoria não encontrada")
            return _print(cp)
        if a.cmd == "report":
            store = AuditStore(a.audit_id, root=root)
            cp = store.load_checkpoint()
            if not cp:
                raise SystemExit("auditoria não encontrada")
            out = DAIA_DIR / "reports" / f"{cp['updated_at_utc'][:10]}_auditoria_{a.audit_id}.md"
            out.write_text(render_report(cp), encoding="utf-8")
            print(f"relatório gerado em {out}")
            return 0
        if a.cmd == "list":
            print(json.dumps(list_audits(root), ensure_ascii=False, indent=1))
            return 0
    except LimitPolicyError as exc:
        print(f"bloqueado pela política de limites: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
