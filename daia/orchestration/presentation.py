"""What the human sees: real coverage, findings, unconfirmed items, risks,
pending work, Jira proposals, limitations and next steps."""
from __future__ import annotations

from typing import Any, Mapping

DOMAIN_VIEW = {"CONCLUÍDO": "VERIFICADO", "NÃO NECESSÁRIO": None}
INTERNAL = {"cause_kind", "cause_fixed", "deps", "state", "priority_rank", "history", "recurrent", "jira_status", "investigation"}


def human_summary(cp: Mapping[str, Any]) -> dict[str, Any]:
    findings = cp.get("findings", [])
    current = [f for f in findings if f["state"] == "PROBLEMA_ATUAL" and f["classification"] in ("OBSERVADO", "INFERIDO")]
    unconfirmed = list(cp.get("unconfirmed", [])) + [
        {"item": f"{f['problem_class']}@{f['resource']}", "reason": f"classificação {f['classification']}"}
        for f in findings if f["classification"] in ("HIPÓTESE", "NÃO VERIFICADO")]
    risks = [f for f in findings if f["state"] == "RISCO_FUTURO"]
    pending = [f"Etapa {sid} — {st['name']}: {st['status']}" for sid, st in cp["stages"].items()
               if st["status"] not in ("CONCLUÍDA", "NÃO SOLICITADO")]
    for d, c in cp["coverage"].items():
        if d.startswith("_"):
            continue
        if c["planned"] and c["status"] not in ("CONCLUÍDO", "NÃO NECESSÁRIO"):
            pending.append(f"Domínio {d}: {c['status']}" + (f" — {c['reason']}" if c.get("reason") else ""))
    m = cp["coverage"].get("metrics", {})
    if m.get("resources_expected") is not None and m.get("resources_analyzed", 0) < m["resources_expected"]:
        pending.append(f"Métricas: {m.get('resources_analyzed', 0)}/{m['resources_expected']} consultas planejadas concluídas")
    steps = []
    if cp["status"] != "CONCLUÍDA":
        steps.append(f"Retomar: python -m daia.orchestration.cli resume {cp['audit_id']} (só etapas pendentes; dados expirados são revalidados)")
    if cp.get("interruption") and "BudgetExceeded" in cp["interruption"]["kind"]:
        steps.append("Limite atingido: ampliar exige aprovação humana registrada (--approve-expansion).")
    if cp.get("proposals"):
        steps.append("Revisar propostas Jira e aprovar explicitamente as que devem ser criadas (CRIAR ATIVIDADES APROVADAS).")
    if current:
        steps.append("Executar os guias de diagnóstico (somente leitura) dos achados P0–P2 antes de qualquer correção.")
    if cp.get("tool_errors"):
        steps.append("Resolver as falhas de acesso listadas; o DAIA não contorna bloqueios.")
    return {
        "audit_id": cp["audit_id"], "status": cp["status"], "criteria_unmet": cp.get("criteria_unmet", []),
        "coverage": {d: {k: c.get(k) for k in ("planned", "status", "queries", "pages", "items", "reason",
                                              "resources_expected", "resources_analyzed")}
                     for d, c in cp["coverage"].items() if not d.startswith("_")},
        "identified": [_brief(f) for f in current],
        "unconfirmed": unconfirmed,
        "future_risks": [_brief(f) for f in risks],
        "pending": pending,
        "jira_proposals": [{"fingerprint": p["fingerprint"], "title": p["payload"]["summary"], "status": p["status"]} for p in cp.get("proposals", [])],
        "jira_links": [j for j in cp.get("jira", []) if j["action"] == "linked_existing"],
        "limitations": cp.get("limitations", []),
        "tool_errors": cp.get("tool_errors", []),
        "next_steps": steps,
        "budget_used": cp.get("budget_used", {}),
    }


def _brief(f: Mapping[str, Any]) -> dict[str, Any]:
    return {"priority": f.get("priority_rank"), "severity": f["severity"], "problem_class": f["problem_class"], "resource": f["resource"],
            "summary": f["summary"], "classification": f["classification"], "cause": f"{f['cause']['status']}: {f['cause']['description']}" if f.get("cause") else "não analisada",
            "silent": f["silent"], "recurrent": f.get("recurrent", False), "jira": f.get("jira_status")}


def render_report(cp: Mapping[str, Any]) -> str:
    s = human_summary(cp)
    out = [f"# Auditoria {s['audit_id']} — status {s['status']}", "",
           f"- Ambiente: {cp['request']['environment']} · janela {cp['window']['start_utc']} → {cp['window']['end_utc']} · modo {cp['request']['mode']}",
           f"- Gatilho: {cp['request']['trigger']}", ""]
    if s["criteria_unmet"]:
        out += ["**Critérios de conclusão não atendidos:**"] + [f"- {x}" for x in s["criteria_unmet"]] + [""]
    out += ["## Cobertura real", "", "| Domínio | Planejado | Status | Consultas | Páginas | Itens | Observação |", "|---|---|---|---|---|---|---|"]
    for d, c in s["coverage"].items():
        extra = f"{c['resources_analyzed']}/{c['resources_expected']} consultas" if c.get("resources_expected") is not None else ""
        out.append(f"| {d} | {'sim' if c['planned'] else 'não'} | {c['status']} | {c['queries']} | {c['pages']} | {c['items']} | {c.get('reason') or extra} |")
    def table(title, rows):
        nonlocal out
        out += ["", f"## {title}", ""]
        if not rows:
            out.append("Nenhum.")
            return
        out += ["| # | Sev | Problema | Recurso | Classificação | Causa | Silencioso | Recorrente | Jira |", "|---|---|---|---|---|---|---|---|---|"]
        for r in rows:
            out.append(f"| {r['priority']} | {r['severity']} | {r['summary']} | {r['resource']} | {r['classification']} | {r['cause']} | "
                       f"{'sim' if r['silent'] else 'não'} | {'sim' if r['recurrent'] else 'não'} | {r['jira'] or '—'} |")
    table("Problemas identificados", s["identified"])
    out += ["", "## Problemas não confirmados", ""] + ([f"- {u['item']}: {u['reason']}" for u in s["unconfirmed"]] or ["Nenhum."])
    table("Riscos futuros", s["future_risks"])
    out += ["", "## Investigações pendentes", ""] + ([f"- {p}" for p in s["pending"]] or ["Nenhuma."])
    out += ["", "## Propostas Jira (aguardando aprovação humana)", ""] + ([f"- {p['title']} — {p['status']}" for p in s["jira_proposals"]] or ["Nenhuma."])
    out += [f"- Relacionado a issue existente: {j['issue_key']}" for j in s["jira_links"]]
    out += ["", "## Falhas de ferramentas", ""] + ([f"- {e['tool']}: {e['code']} ({e.get('message')})" for e in s["tool_errors"]] or ["Nenhuma."])
    out += ["", "## Limitações", ""] + ([f"- {l}" for l in s["limitations"]] or ["Nenhuma registrada."])
    out += ["", "## Próximos passos", ""] + ([f"- {x}" for x in s["next_steps"]] or ["- Nenhum pendente."])
    out += ["", f"Consumo: {s['budget_used']}", ""]
    return "\n".join(out)


def to_audit_output(cp: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a checkpoint into audit-output-v1 so the eval suite can score the orchestrator."""
    domains = {}
    for d, c in cp["coverage"].items():
        if d.startswith("_") or not c["planned"]:
            continue
        if c["status"] == "CONCLUÍDO":
            domains[d] = "VERIFICADO"
        elif c["status"] != "NÃO NECESSÁRIO":
            domains[d] = "NÃO VERIFICADO"
    findings = [{k: v for k, v in f.items() if k not in INTERNAL} for f in cp.get("findings", [])]
    s = human_summary(cp)
    narrative = (f"Auditoria {cp['status']}. {len(s['identified'])} problema(s) identificado(s), {len(s['future_risks'])} risco(s) futuro(s), "
                 f"{len(s['unconfirmed'])} item(ns) não confirmado(s). " + (f"Pendências: {len(s['pending'])}." if s["pending"] else ""))
    return {"schema_version": "audit-output-v1", "status": cp["status"], "domains": domains, "findings": findings,
            "tool_errors_reported": [{"tool": e["tool"], "error_code": e["code"], "shown_to_human": True} for e in cp.get("tool_errors", [])],
            "security_notices": [{k: v for k, v in n.items() if k != "service"} for n in cp.get("notices", [])],
            "jira": cp.get("jira", []), "limitations": cp.get("limitations", []) + [f"Critério não atendido: {x}" for x in cp.get("criteria_unmet", [])],
            "narrative": narrative}
