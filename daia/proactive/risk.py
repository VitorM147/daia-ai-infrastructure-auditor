"""Risk classification that keeps current failures separate from future risk."""
from __future__ import annotations

from typing import Iterable

from .models import RiskAssessment, TrendResult


def classify_risk(*, risk_id: str, current_value: float | None, threshold: float | None,
                  trend: TrendResult, telemetry_quality: str,
                  evidence: Iterable[str], counter_evidence: Iterable[str],
                  accelerators: Iterable[str], mitigators: Iterable[str],
                  preventive_actions: Iterable[str], follow_up_indicators: Iterable[str]) -> RiskAssessment:
    evidence = tuple(evidence)
    counter_evidence = tuple(counter_evidence)
    accelerators = tuple(accelerators)
    mitigators = tuple(mitigators)
    preventive_actions = tuple(preventive_actions)
    follow_up_indicators = tuple(follow_up_indicators)
    if telemetry_quality != "SUFFICIENT":
        return RiskAssessment(risk_id, "NÃO_VERIFICADO", "unknown", "low", evidence, counter_evidence,
                              accelerators, mitigators, preventive_actions, follow_up_indicators,
                              "telemetry quality is insufficient")
    if current_value is not None and threshold is not None and current_value >= threshold:
        return RiskAssessment(risk_id, "PROBLEMA_ATUAL", "high", "high", evidence, counter_evidence,
                              accelerators, mitigators, preventive_actions, follow_up_indicators,
                              "current value is at or above the operational threshold")
    if trend.status == "TREND" and trend.direction == "UP":
        return RiskAssessment(risk_id, "RISCO_FUTURO", "medium", "medium", evidence, counter_evidence,
                              accelerators, mitigators, preventive_actions, follow_up_indicators,
                              "validated positive trend below threshold; no incident is asserted")
    if trend.status == "NOT_CALCULABLE":
        return RiskAssessment(risk_id, "SEM_EVIDENCIA", "unknown", "low", evidence, counter_evidence,
                              accelerators, mitigators, preventive_actions, follow_up_indicators,
                              "trend is not calculable with the available coverage")
    return RiskAssessment(risk_id, "SEM_EVIDENCIA", "low", "medium", evidence, counter_evidence,
                          accelerators, mitigators, preventive_actions, follow_up_indicators,
                          "no validated future degradation signal")
