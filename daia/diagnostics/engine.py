"""Read-only diagnostic pipeline: validate evidence, calculate, compare, assess."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .baseline import BaselineResult, compare_with_baseline
from .diagnostics import DiagnosticAssessment, assess_diagnostic
from .models import EvidencePackage, MetricPoint


@dataclass(frozen=True)
class DiagnosticResult:
    metric_value: float | None
    baseline_comparison: dict[str, object]
    assessment: DiagnosticAssessment


def run_read_only(*, package: EvidencePackage, current_value: float,
                  baseline: BaselineResult, threshold: float,
                  claim: str, evidence_for: Iterable[str],
                  evidence_against: Iterable[str], alternatives: Iterable[str],
                  causal_identifiers_match: bool = False,
                  current_state_confirmed: bool = False) -> DiagnosticResult:
    package.validate()
    comparison = compare_with_baseline(current_value, baseline, threshold=threshold)
    assessment = assess_diagnostic(packages=[package], claim=claim,
                                   evidence_for=evidence_for,
                                   evidence_against=evidence_against,
                                   alternatives=alternatives,
                                   coverage_sufficient=baseline.calculable,
                                   causal_identifiers_match=causal_identifiers_match,
                                   current_state_confirmed=current_state_confirmed)
    return DiagnosticResult(current_value, comparison, assessment)
