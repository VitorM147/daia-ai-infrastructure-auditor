"""Quality gates and version-to-version regression comparison."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .taxonomy import EVAL_IDS, FAIL, NOT_EXECUTED, PASS, PENDING

GATES_PATH = Path(__file__).resolve().parent.parent / "gates.json"

EXIT_CODES = {"PASS": 0, "BLOCKED": 1, "PASS_PENDING_HUMAN_REVIEW": 2, "NOT_EXECUTED": 3, "INCOMPLETE": 3}


def load_gates(path: Path = GATES_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_runs(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Compare two stored run results (``result.json``)."""
    pm, cm = previous["metrics"], current["metrics"]
    notes = []
    if previous["metadata"]["dataset"]["version"] != current["metadata"]["dataset"]["version"]:
        notes.append("versões de dataset diferentes: comparação apenas indicativa")
    deltas = {}
    for key in ("precision", "recall", "severity_accuracy", "cause_accuracy", "uncertainty_accuracy", "healthy_specificity"):
        a, b = pm[key]["value"], cm[key]["value"]
        deltas[key] = {"previous": a, "current": b, "delta": None if a is None or b is None else round(b - a, 4),
                       "n_previous": pm[key]["n"], "n_current": cm[key]["n"]}
    for key in ("false_positives", "false_negatives", "trap_false_positives"):
        deltas[key] = {"previous": pm[key], "current": cm[key], "delta": cm[key] - pm[key]}
    prev = {s["scenario_id"]: s for s in previous["scenarios"]}
    regressions, fixes, new_critical = [], [], []
    for s in current["scenarios"]:
        p = prev.get(s["scenario_id"])
        if not p:
            continue
        if p["outcome"] in (PASS, PENDING) and s["outcome"] in (FAIL, "ERROR"):
            dims = [d for d, r in s["dimensions"].items() if r["status"] == FAIL and p["dimensions"].get(d, {}).get("status") != FAIL]
            regressions.append({"scenario_id": s["scenario_id"], "dimensions": dims})
        if p["outcome"] in (FAIL, "ERROR") and s["outcome"] in (PASS, PENDING):
            fixes.append(s["scenario_id"])
        if s["critical_violations"] and not p["critical_violations"]:
            new_critical.append({"scenario_id": s["scenario_id"], "violations": s["critical_violations"]})
    return {"previous_run": previous["metadata"]["run_id"], "current_run": current["metadata"]["run_id"],
            "previous_agent": previous["metadata"]["agent"], "current_agent": current["metadata"]["agent"],
            "metric_deltas": deltas, "regressions": regressions, "fixes": fixes,
            "new_critical_violations": new_critical, "notes": notes}


def evaluate_gates(result: Mapping[str, Any], gates: Mapping[str, Any], comparison: Mapping[str, Any] | None = None) -> dict[str, Any]:
    m = result["metrics"]
    checks: list[dict[str, Any]] = []

    def check(cid: str, status: str, detail: str, blocking: bool) -> None:
        checks.append({"id": cid, "status": status, "detail": detail, "blocking": blocking})

    if m["scenarios_executed"] == 0:
        check("G00-execution", NOT_EXECUTED, "nenhum cenário executado (agente indisponível?)", True)
        return {"decision": "NOT_EXECUTED", "exit_code": EXIT_CODES["NOT_EXECUTED"], "checks": checks}

    crit = m["critical_violations"]
    check("G01-critical-violations", FAIL if crit else PASS,
          f"{len(crit)} violação(ões) crítica(s)" + (": " + "; ".join(crit[:5]) if crit else ""),
          gates.get("block_on_any_critical_violation", True))
    errors = m["outcomes"].get("ERROR", 0)
    check("G02-agent-errors", FAIL if errors else PASS, f"{errors} cenário(s) com erro do agente", gates.get("block_on_agent_error", True))
    missing = [e for e in EVAL_IDS if m["evals"][e]["status"] in (NOT_EXECUTED, "SEM CENÁRIO")]
    check("G03-eval-coverage", "INCOMPLETE" if missing else PASS,
          ("EVALs sem execução: " + ", ".join(missing)) if missing else "EVAL-001..015 executados",
          gates.get("require_all_evals_executed", True))
    pending = sum(d["counts"].get(PENDING, 0) for d in m["dimensions"].values())
    check("G04-human-review", PENDING if pending else PASS, f"{pending} item(ns) aguardando revisão humana",
          gates.get("require_human_review_for_release", True))
    targets = gates.get("targets", {})
    for key, metric in (("precision_min", "precision"), ("recall_min", "recall"), ("severity_accuracy_min", "severity_accuracy"),
                        ("cause_accuracy_min", "cause_accuracy"), ("healthy_specificity_min", "healthy_specificity")):
        target = targets.get(key)
        value = m[metric]["value"]
        if target is None:
            check(f"G10-{metric}", "SEM META", f"{metric}={value} (n={m[metric]['n']}); meta não definida", False)
        elif value is None:
            check(f"G10-{metric}", "INCOMPLETE", f"{metric} sem amostra", True)
        else:
            check(f"G10-{metric}", PASS if value >= target else FAIL, f"{metric}={value} (n={m[metric]['n']}) meta {target}", True)
    if comparison:
        reg = gates.get("regression", {})
        nc = comparison["new_critical_violations"]
        check("G20-new-critical", FAIL if nc else PASS, f"{len(nc)} cenário(s) com nova violação crítica vs {comparison['previous_run']}",
              reg.get("block_on_new_critical_violation", True))
        rg = comparison["regressions"]
        check("G21-scenario-regressions", FAIL if rg else PASS, f"{len(rg)} cenário(s) regrediram vs {comparison['previous_run']}",
              reg.get("block_on_scenario_regression", False))

    blocking_fail = any(c["blocking"] and c["status"] == FAIL for c in checks)
    incomplete = any(c["blocking"] and c["status"] in ("INCOMPLETE", NOT_EXECUTED) for c in checks)
    pending_review = any(c["blocking"] and c["status"] == PENDING for c in checks)
    if blocking_fail:
        decision = "BLOCKED"
    elif incomplete:
        decision = "INCOMPLETE"
    elif pending_review:
        decision = "PASS_PENDING_HUMAN_REVIEW"
    else:
        decision = "PASS"
    return {"decision": decision, "exit_code": EXIT_CODES[decision], "checks": checks}
