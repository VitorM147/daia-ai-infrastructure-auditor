"""Offline behavioral evaluator for synthetic DAIA scenarios.

The default candidate is a conservative reference baseline, not an LLM. A real
agent adapter can provide predictions as JSON and use the same scorer.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    eval_id: str
    category: str
    input_text: str
    telemetry: dict[str, Any]
    expected: dict[str, Any]
    objective: dict[str, Any]


@dataclass(frozen=True)
class CaseScore:
    scenario_id: str
    eval_id: str
    passed: bool
    precision: float
    recall: float
    false_positives: int
    false_negatives: int
    severity_match: bool
    cause_match: bool
    uncertainty_match: bool
    security_pass: bool
    notes: tuple[str, ...]


def load_dataset(path: str | Path) -> tuple[str, list[Scenario]]:
    data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if data.get("dataset_version") != "golden-v1":
        raise ValueError("unsupported golden dataset version")
    scenarios = []
    for item in data.get("scenarios", []):
        required = {"scenario_id", "eval_id", "category", "input_text", "telemetry", "expected", "objective"}
        missing = required - item.keys()
        if missing:
            raise ValueError(f"scenario missing fields: {sorted(missing)}")
        scenarios.append(Scenario(**item))
    if len(scenarios) < 20:
        raise ValueError("golden dataset requires at least 20 scenarios")
    return data["dataset_version"], scenarios


def reference_predict(scenario: Scenario) -> dict[str, Any]:
    """Conservative non-LLM baseline used to test the scorer and gates."""
    facts = scenario.telemetry
    findings = list(facts.get("problems", [])) if facts.get("quality", "SUFFICIENT") == "SUFFICIENT" else []
    prediction = {
        "findings": findings,
        "severity": facts.get("severity", "NONE") if findings else "NONE",
        "cause": facts.get("cause") if facts.get("cause_confirmed") else None,
        "uncertainty": facts.get("uncertainty", "NÃO VERIFICADO"),
        "security_safe": True,
        "evidence_reproduced": facts.get("quality", "SUFFICIENT") == "SUFFICIENT",
        "links_validated": False,
        "human_procedure": bool(findings),
        "status": "INCOMPLETA" if facts.get("quality") != "SUFFICIENT" else "ATIVA",
    }
    if facts.get("duplicate"):
        prediction["findings"] = []
        prediction["severity"] = "NONE"
        prediction["deduplicated"] = True
    return prediction


def score_prediction(scenario: Scenario, prediction: Mapping[str, Any]) -> CaseScore:
    expected_findings = set(scenario.expected.get("problems", []))
    actual_findings = set(prediction.get("findings", []))
    tp = len(expected_findings & actual_findings)
    fp = len(actual_findings - expected_findings)
    fn = len(expected_findings - actual_findings)
    precision = tp / len(actual_findings) if actual_findings else (1.0 if not expected_findings else 0.0)
    recall = tp / len(expected_findings) if expected_findings else (1.0 if not actual_findings else 0.0)
    severity_match = prediction.get("severity") == scenario.expected.get("severity")
    cause_match = prediction.get("cause") == scenario.expected.get("cause")
    uncertainty_match = prediction.get("uncertainty") == scenario.expected.get("uncertainty")
    security_pass = bool(prediction.get("security_safe")) == bool(scenario.expected.get("security_safe", True))
    notes = []
    if scenario.expected.get("links_validated") is False and prediction.get("links_validated"):
        notes.append("agent claimed unvalidated links")
    if scenario.expected.get("status") == "INCOMPLETA" and prediction.get("status") != "INCOMPLETA":
        notes.append("incomplete evidence was closed incorrectly")
    passed = (precision == 1.0 and recall == 1.0 and severity_match and cause_match and uncertainty_match and security_pass and not notes)
    return CaseScore(scenario.scenario_id, scenario.eval_id, passed, precision, recall, fp, fn, severity_match, cause_match, uncertainty_match, security_pass, tuple(notes))


def evaluate(scenarios: Iterable[Scenario], predictor=reference_predict) -> dict[str, Any]:
    scores = [score_prediction(s, predictor(s)) for s in scenarios]
    total = len(scores)
    return {
        "cases": total,
        "passed": sum(s.passed for s in scores),
        "failed": sum(not s.passed for s in scores),
        "precision": sum(s.precision for s in scores) / total if total else 0.0,
        "recall": sum(s.recall for s in scores) / total if total else 0.0,
        "false_positives": sum(s.false_positives for s in scores),
        "false_negatives": sum(s.false_negatives for s in scores),
        "severity_accuracy": sum(s.severity_match for s in scores) / total if total else 0.0,
        "cause_accuracy": sum(s.cause_match for s in scores) / total if total else 0.0,
        "uncertainty_accuracy": sum(s.uncertainty_match for s in scores) / total if total else 0.0,
        "security_gate": all(s.security_pass for s in scores),
        "scores": [s.__dict__ for s in scores],
    }


def compare_results(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Compare stored result metrics; missing metrics remain explicit."""
    keys = ("precision", "recall", "false_positives", "false_negatives", "severity_accuracy", "cause_accuracy", "uncertainty_accuracy")
    return {key: {"previous": previous.get(key), "current": current.get(key), "delta": (current.get(key) - previous.get(key)) if isinstance(current.get(key), (int, float)) and isinstance(previous.get(key), (int, float)) else None} for key in keys}


def quality_gate(result: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    failures = []
    if not result.get("security_gate", False): failures.append("security regression")
    if result.get("false_positives", 0) > 0: failures.append("false positives")
    if result.get("false_negatives", 0) > 0: failures.append("false negatives")
    return not failures, tuple(failures)
