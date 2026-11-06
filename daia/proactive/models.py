"""Contracts for preventive analysis; predictions require explicit uncertainty."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class TrendResult:
    status: str
    direction: str
    slope_per_second: float | None
    relative_change: float | None
    points: int
    coverage: float
    seasonality_checked: bool
    reason: str


@dataclass(frozen=True)
class ExhaustionEstimate:
    status: str
    seconds_to_threshold: float | None
    lower_seconds: float | None
    upper_seconds: float | None
    confidence: str
    reason: str


@dataclass(frozen=True)
class RiskAssessment:
    risk_id: str
    state: str  # PROBLEMA_ATUAL, RISCO_FUTURO, SEM_EVIDENCIA, NAO_VERIFICADO
    severity: str
    confidence: str
    evidence: tuple[str, ...]
    counter_evidence: tuple[str, ...]
    accelerators: tuple[str, ...]
    mitigators: tuple[str, ...]
    preventive_actions: tuple[str, ...]
    follow_up_indicators: tuple[str, ...]
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()
