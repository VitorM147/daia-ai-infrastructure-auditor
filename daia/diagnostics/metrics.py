"""Unit-aware deterministic metric calculations."""
from __future__ import annotations

from math import isfinite
from typing import Iterable

from .models import MetricPoint


class MetricCalculationError(ValueError):
    pass


def _validated(points: Iterable[MetricPoint]) -> list[MetricPoint]:
    result = list(points)
    if not result:
        raise MetricCalculationError("at least one point is required")
    for point in result:
        point.validate()
    return result


def aggregate_count(points: Iterable[MetricPoint], *, expected_unit: str = "count") -> float:
    values = _validated(points)
    if any(p.unit != expected_unit for p in values):
        raise MetricCalculationError("count aggregation requires a common count unit")
    if len({p.identity for p in values}) != 1:
        raise MetricCalculationError("cannot aggregate unrelated series")
    return sum(p.value for p in values)


def calculate_rate(numerator: Iterable[MetricPoint], denominator: Iterable[MetricPoint], *, scale: float = 1.0) -> float:
    nums, dens = _validated(numerator), _validated(denominator)
    if len({p.identity for p in nums}) != 1 or len({p.identity for p in dens}) != 1:
        raise MetricCalculationError("rate inputs must each describe one series")
    if nums[0].resource_id != dens[0].resource_id or nums[0].service != dens[0].service:
        raise MetricCalculationError("numerator and denominator resource/service mismatch")
    if nums[0].source_kind != dens[0].source_kind:
        raise MetricCalculationError("numerator and denominator source kind mismatch")
    if len({p.timestamp_utc for p in nums}) != len(nums) or len({p.timestamp_utc for p in dens}) != len(dens):
        raise MetricCalculationError("duplicate timestamps are ambiguous")
    if {p.timestamp_utc for p in nums} != {p.timestamp_utc for p in dens}:
        raise MetricCalculationError("numerator and denominator windows must have matching timestamps")
    n, d = sum(p.value for p in nums), sum(p.value for p in dens)
    if d <= 0:
        raise MetricCalculationError("denominator must be positive")
    if not isfinite(scale) or scale < 0:
        raise MetricCalculationError("scale must be finite and non-negative")
    return (n / d) * scale


def calculate_percentage(numerator: Iterable[MetricPoint], denominator: Iterable[MetricPoint]) -> float:
    return calculate_rate(numerator, denominator, scale=100.0)
