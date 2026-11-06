"""Comparable-window baselines with explicit coverage and seasonality."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Iterable

from .models import MetricPoint


@dataclass(frozen=True)
class BaselineResult:
    calculable: bool
    value: float | None
    points: int
    coverage: float
    window_start_utc: datetime
    window_end_utc: datetime
    method: str
    reason: str | None = None


def build_baseline(points: Iterable[MetricPoint], *, start_utc: datetime, end_utc: datetime,
                   expected_points: int, min_coverage: float = 0.8,
                   seasonal_weekday: int | None = None) -> BaselineResult:
    if start_utc.tzinfo != timezone.utc or end_utc.tzinfo != timezone.utc:
        raise ValueError("baseline window must be UTC")
    selected = [p for p in points if start_utc <= p.timestamp_utc < end_utc
                and (seasonal_weekday is None or p.timestamp_utc.weekday() == seasonal_weekday)]
    selected.sort(key=lambda p: (p.timestamp_utc, p.metric_id, p.resource_id))
    coverage = len(selected) / expected_points if expected_points > 0 else 0.0
    if not selected:
        return BaselineResult(False, None, 0, coverage, start_utc, end_utc, "median", "no comparable points")
    if coverage < min_coverage:
        return BaselineResult(False, None, len(selected), coverage, start_utc, end_utc, "median", "insufficient coverage")
    units = {p.unit for p in selected}
    identities = {p.identity for p in selected}
    if len(units) != 1 or len(identities) != 1:
        return BaselineResult(False, None, len(selected), coverage, start_utc, end_utc, "median", "mixed units or series")
    return BaselineResult(True, median([p.value for p in selected]), len(selected), coverage, start_utc, end_utc, "median")


def compare_with_baseline(current: float, baseline: BaselineResult, *, threshold: float,
                          direction: str = "above") -> dict[str, object]:
    if not baseline.calculable or baseline.value is None:
        return {"status": "NOT_CALCULABLE", "reason": baseline.reason, "coverage": baseline.coverage}
    if baseline.value == 0:
        delta = None if current == 0 else float("inf")
    else:
        delta = (current - baseline.value) / abs(baseline.value)
    triggered = (delta is not None and ((delta >= threshold) if direction == "above" else (delta <= -threshold)))
    return {
        "status": "REGRESSION" if triggered else "NO_REGRESSION",
        "current": current,
        "baseline": baseline.value,
        "relative_delta": delta,
        "threshold": threshold,
        "direction": direction,
        "coverage": baseline.coverage,
        "points": baseline.points,
    }
