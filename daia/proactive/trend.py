"""Conservative trend and exhaustion calculations for ordered time series."""
from __future__ import annotations

from math import isfinite
from statistics import mean, pstdev
from typing import Iterable, Sequence

from daia.diagnostics.models import MetricPoint
from .models import ExhaustionEstimate, TrendResult


def _ordered(points: Iterable[MetricPoint]) -> list[MetricPoint]:
    values = sorted(points, key=lambda p: p.timestamp_utc)
    for point in values:
        point.validate()
    if len({p.timestamp_utc for p in values}) != len(values):
        raise ValueError("duplicate timestamps prevent deterministic trend analysis")
    if len({p.identity for p in values}) > 1:
        raise ValueError("trend requires one comparable series")
    return values


def analyze_trend(points: Iterable[MetricPoint], *, min_points: int = 5,
                  min_coverage: float = 0.8, expected_points: int | None = None,
                  seasonal_baseline_available: bool = False) -> TrendResult:
    values = _ordered(points)
    coverage = len(values) / expected_points if expected_points else 1.0
    if len(values) < min_points:
        return TrendResult("NOT_CALCULABLE", "UNKNOWN", None, None, len(values), coverage,
                           seasonal_baseline_available, "insufficient points")
    if coverage < min_coverage:
        return TrendResult("NOT_CALCULABLE", "UNKNOWN", None, None, len(values), coverage,
                           seasonal_baseline_available, "insufficient coverage")
    times = [(p.timestamp_utc - values[0].timestamp_utc).total_seconds() for p in values]
    ys = [p.value for p in values]
    mean_x, mean_y = mean(times), mean(ys)
    denom = sum((x - mean_x) ** 2 for x in times)
    if denom == 0:
        return TrendResult("NOT_CALCULABLE", "UNKNOWN", None, None, len(values), coverage,
                           seasonal_baseline_available, "zero time span")
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(times, ys)) / denom
    relative = None if ys[0] == 0 else (ys[-1] - ys[0]) / abs(ys[0])
    direction = "UP" if slope > 0 else "DOWN" if slope < 0 else "FLAT"
    status = "TREND" if direction != "FLAT" else "NO_TREND"
    return TrendResult(status, direction, slope, relative, len(values), coverage,
                       seasonal_baseline_available,
                       "linear trend; seasonality must be considered separately" if not seasonal_baseline_available else "linear trend with seasonal baseline")


def estimate_exhaustion(points: Iterable[MetricPoint], *, threshold: float,
                        min_points: int = 5, min_coverage: float = 0.8,
                        expected_points: int | None = None,
                        uncertainty_z: float = 2.0) -> ExhaustionEstimate:
    """Estimate only with a positive trend and uncertainty interval.

    The interval uses residual standard deviation as a conservative data-quality
    proxy; it is not a statistical prediction interval for arbitrary systems.
    """
    values = _ordered(points)
    trend = analyze_trend(values, min_points=min_points, min_coverage=min_coverage,
                          expected_points=expected_points)
    if trend.status != "TREND" or trend.slope_per_second is None or trend.slope_per_second <= 0:
        return ExhaustionEstimate("NOT_CALCULABLE", None, None, None, "low", "no validated positive trend")
    current = values[-1].value
    if current >= threshold:
        return ExhaustionEstimate("THRESHOLD_REACHED", 0.0, 0.0, 0.0, "high", "current value is already at threshold")
    raw = (threshold - current) / trend.slope_per_second
    predicted = [values[0].value + trend.slope_per_second * t for t in [(p.timestamp_utc - values[0].timestamp_utc).total_seconds() for p in values]]
    residuals = [p.value - y for p, y in zip(values, predicted)]
    uncertainty = uncertainty_z * (pstdev(residuals) if len(residuals) > 1 else 0.0)
    if not isfinite(raw) or raw <= 0:
        return ExhaustionEstimate("NOT_CALCULABLE", None, None, None, "low", "invalid time estimate")
    # Convert value uncertainty into time uncertainty; clamp lower bound to zero.
    time_uncertainty = uncertainty / trend.slope_per_second
    return ExhaustionEstimate("ESTIMATE", raw, max(0.0, raw - time_uncertainty),
                               raw + time_uncertainty, "medium", "trend and uncertainty interval available; not a guarantee")
