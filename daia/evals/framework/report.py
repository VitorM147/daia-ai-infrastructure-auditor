"""Markdown metrics report for one run."""
from __future__ import annotations

from typing import Any, Mapping

from .taxonomy import SEVERITIES


def _rate(m: Mapping[str, Any]) -> str:
    if m["value"] is None:
        return "sem amostra (n=0)"
    lo, hi = m["ci95"]
    return f"{m['value']:.1%} ({m['successes']}/{m['n']}; IC95% {lo:.0%}–{hi:.0%})"


def render(result: Mapping[str, Any]) -> str:
    md, m, g = result["metadata"], result["metrics"], result["gate"]
    a = md["agent"]
    lines = [
        f"# Relatório de Evals comportamentais — {md['run_id']}",
        "",
        "## Identificação",
        f"- Agente: **{a['name']}** {a['version']} · tipo: {a.get('kind')} · modelo: {a.get('model') or 'não se aplica'}",
        f"- Configuração do agente: `{a.get('config')}`",
        f"- Dataset: {md['dataset']['version']} (manifest {md['dataset']['manifest_sha256'][:12]}) · cenários selecionados: {m['scenarios_total']}",
        f"- Scorer: {md['scorer_version']} · Gates: {md['gates_version']} · Política sandbox: {md['policy_sha256'][:12]}",
        f"- Commit: {md.get('git_commit') or 'não disponível'}{' (com alterações não commitadas)' if md.get('git_dirty') else ''} · Python {md['python']} · {md['timestamp_utc']} · repetições: {md['repeat']}",
        "",
        f"## Decisão do gate: **{g['decision']}** (exit {g['exit_code']})",
        "",
        "| Gate | Status | Bloqueante | Detalhe |", "|---|---|---|---|",
    ]
    for c in g["checks"]:
        lines.append(f"| {c['id']} | {c['status']} | {'sim' if c['blocking'] else 'não'} | {c['detail']} |")
    lines += [
        "",
        "## Métricas agregadas",
        f"- Executados: {m['scenarios_executed']}/{m['scenarios_total']} · Resultados: {m['outcomes']}",
        f"- Precisão (achados): {_rate(m['precision'])}",
        f"- Recall (achados obrigatórios): {_rate(m['recall'])}",
        f"- Falsos positivos: {m['false_positives']} (em armadilhas conhecidas: {m['trap_false_positives']}) · Falsos negativos: {m['false_negatives']}",
        f"- Severidade aceita: {_rate(m['severity_accuracy'])} · exata: {_rate(m['severity_exact'])}",
        f"- Causa (D06): {_rate(m['cause_accuracy'])} · Incerteza (D07): {_rate(m['uncertainty_accuracy'])}",
        f"- Especificidade em cenários saudáveis: {_rate(m['healthy_specificity'])}",
    ]
    if result.get("stability", {}).get("stable_fraction") is not None:
        st = result["stability"]
        lines.append(f"- Estabilidade entre {st['repeats']} repetições: {st['stable_fraction']:.0%} (instáveis: {', '.join(st['unstable']) or 'nenhum'})")
    lines += ["", "### Matriz de severidade (linhas = esperado, colunas = obtido)", "",
              "| esperado \\ obtido | " + " | ".join((*SEVERITIES, "outro")) + " |", "|---" * (len(SEVERITIES) + 2) + "|"]
    for e in SEVERITIES:
        lines.append(f"| {e} | " + " | ".join(str(m["severity_confusion"][e][p]) for p in (*SEVERITIES, "outro")) + " |")
    lines += ["", "## Dimensões avaliadas", "", "| Dimensão | Crítica | PASS | FAIL | Pendente revisão | N/A | Não executado | Taxa |", "|---|---|---|---|---|---|---|---|"]
    for d, v in m["dimensions"].items():
        c = v["counts"]
        lines.append(f"| {d} {v['title']} | {'sim' if v['critical'] else 'não'} | {c.get('PASS', 0)} | {c.get('FAIL', 0)} | "
                     f"{c.get('PENDING_HUMAN_REVIEW', 0)} | {c.get('NOT_APPLICABLE', 0)} | {v['not_executed']} | {_rate(v['pass_rate'])} |")
    lines += ["", "## EVAL-001 a EVAL-015", "", "| EVAL | Status | Cenários | Resultados |", "|---|---|---|---|"]
    for e, v in m["evals"].items():
        lines.append(f"| {e} | {v['status']} | {v['scenarios']} | {', '.join(v['outcomes'])} |")
    lines += ["", "## Falhas por cenário", ""]
    any_fail = False
    for s in result["scenarios"]:
        fails = {d: r for d, r in s["dimensions"].items() if r["status"] == "FAIL"}
        if not fails and s["outcome"] not in ("ERROR",):
            continue
        any_fail = True
        lines.append(f"### {s['scenario_id']} (repetição {s.get('repeat', 0)}) — {s['outcome']}")
        if s.get("error"):
            lines.append(f"- Erro do agente: {s['error']}")
        for d, r in fails.items():
            for det in r["details"][:6]:
                lines.append(f"- **{d}**: {det}")
        lines.append("")
    if not any_fail:
        lines.append("Nenhuma falha automática registrada.")
    if result.get("comparison"):
        c = result["comparison"]
        lines += ["", f"## Comparação com {c['previous_run']}", ""]
        for n in c["notes"]:
            lines.append(f"- Nota: {n}")
        for k, v in c["metric_deltas"].items():
            lines.append(f"- {k}: {v['previous']} → {v['current']} (Δ {v['delta']})")
        lines.append(f"- Regressões: {[r['scenario_id'] for r in c['regressions']] or 'nenhuma'} · Correções: {c['fixes'] or 'nenhuma'}")
    lines += ["", "## Limitações desta medição", ""]
    lines += [f"- {x}" for x in result.get("limitations", [])]
    return "\n".join(lines) + "\n"
