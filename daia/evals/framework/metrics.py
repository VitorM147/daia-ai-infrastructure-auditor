"""Run-level metrics with explicit sample sizes and uncertainty.

Every rate is reported with its numerator, denominator and a Wilson 95% interval.
Results that were not executed or are pending human review are counted
separately and never folded into pass rates.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Mapping

from .taxonomy import DIMENSIONS, EVAL_IDS, FAIL, NOT_APPLICABLE, NOT_EXECUTED, PASS, PENDING, SEVERITIES


def wilson(successes: int, n: int, z: float = 1.96) -> dict[str, Any]:
    if n == 0:
        return {"value": None, "n": 0, "successes": 0, "ci95": [None, None]}
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return {"value": round(p, 4), "n": n, "successes": successes,
            "ci95": [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]}


def aggregate(scores: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    scores = list(scores)
    executed = [s for s in scores if s["outcome"] != NOT_EXECUTED]
    outcome_counts: dict[str, int] = {}
    for s in scores:
        outcome_counts[s["outcome"]] = outcome_counts.get(s["outcome"], 0) + 1
    tp = sum(s["counts"]["tp"] for s in executed)
    fp = sum(s["counts"]["fp"] for s in executed)
    req = sum(s["counts"]["required"] for s in executed)
    tp_req = sum(s["counts"]["tp_required"] for s in executed)
    fn = sum(s["counts"]["fn"] for s in executed)
    trap_fp = sum(s["counts"]["trap_fp"] for s in executed)

    pairs = [p for s in executed for p in s["dimensions"]["D05_severity"]["metrics"].get("pairs", [])]
    sev_ok = sum(s["dimensions"]["D05_severity"]["metrics"].get("accepted", 0) for s in executed)
    sev_app = len(pairs)
    confusion = {e: {p: 0 for p in (*SEVERITIES, "outro")} for e in SEVERITIES}
    for e, p in pairs:
        confusion[e][p if p in SEVERITIES else "outro"] += 1
    exact = sum(1 for e, p in pairs if e == p)

    dims: dict[str, Any] = {}
    for d in DIMENSIONS:
        counts = {PASS: 0, FAIL: 0, NOT_APPLICABLE: 0, PENDING: 0}
        for s in executed:
            counts[s["dimensions"][d]["status"]] = counts.get(s["dimensions"][d]["status"], 0) + 1
        decided = counts[PASS] + counts[FAIL]
        dims[d] = {"title": DIMENSIONS[d]["title"], "critical": DIMENSIONS[d]["critical"],
                   "subjective": DIMENSIONS[d]["subjective"], "counts": counts,
                   "not_executed": len(scores) - len(executed),
                   "pass_rate": wilson(counts[PASS], decided)}

    evals: dict[str, Any] = {}
    for e in EVAL_IDS:
        rel = [s for s in scores if e in s["eval_ids"]]
        outs = [s["outcome"] for s in rel]
        if not rel:
            status = "SEM CENÁRIO"
        elif all(o == NOT_EXECUTED for o in outs):
            status = NOT_EXECUTED
        elif any(o in (FAIL, "ERROR") for o in outs):
            status = FAIL
        elif any(o in (PENDING, NOT_EXECUTED) for o in outs):
            status = PENDING if PENDING in outs else NOT_EXECUTED
        else:
            status = PASS
        evals[e] = {"status": status, "scenarios": len(rel), "outcomes": outs}

    healthy = [s for s in executed if s["healthy"]]
    healthy_clean = sum(1 for s in healthy if s["counts"]["fp"] == 0 and s["counts"]["jira_created"] == 0)
    return {
        "scenarios_total": len(scores),
        "scenarios_executed": len(executed),
        "outcomes": outcome_counts,
        "precision": wilson(tp, tp + fp),
        "recall": wilson(tp_req, req),
        "true_positives": tp, "false_positives": fp, "trap_false_positives": trap_fp, "false_negatives": fn,
        "severity_accuracy": wilson(sev_ok, sev_app),
        "severity_exact": wilson(exact, len(pairs)),
        "severity_confusion": confusion,
        "cause_accuracy": dims["D06_cause"]["pass_rate"],
        "uncertainty_accuracy": dims["D07_uncertainty"]["pass_rate"],
        "healthy_specificity": wilson(healthy_clean, len(healthy)),
        "critical_violations": [f"{s['scenario_id']} :: {v}" for s in executed for v in s["critical_violations"]],
        "dimensions": dims,
        "evals": evals,
    }


def stability(repeats: list[list[Mapping[str, Any]]]) -> dict[str, Any]:
    """Fraction of scenarios whose outcome is identical across repeated runs."""
    if len(repeats) < 2:
        return {"repeats": len(repeats), "stable_fraction": None, "unstable": []}
    by_id: dict[str, set[str]] = {}
    for rep in repeats:
        for s in rep:
            by_id.setdefault(s["scenario_id"], set()).add(s["outcome"])
    unstable = sorted(k for k, v in by_id.items() if len(v) > 1)
    return {"repeats": len(repeats), "stable_fraction": round(1 - len(unstable) / len(by_id), 4), "unstable": unstable}
