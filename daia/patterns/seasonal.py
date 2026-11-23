"""Seasonality-aware baselines and anomaly decisions (deterministic statistics, no ML)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import median
from typing import Iterable, Sequence

Point = tuple[datetime, float]
MIN_SAMPLES_PER_SLOT = 3
MAD_K = 1.4826   # consistency constant: MAD -> sigma under normality


def _utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware UTC")
    return ts.astimezone(timezone.utc)


def slot_of(ts: datetime) -> tuple[int, int]:
    """(weekday, hour) bucket in UTC."""
    t = _utc(ts)
    return t.weekday(), t.hour


def hour_slot(ts: datetime) -> int:
    return _utc(ts).hour


@dataclass(frozen=True)
class SlotBaseline:
    slot: tuple[int, int] | int
    n: int
    median: float
    mad: float


def build_slot_baselines(points: Iterable[Point], by_weekday: bool = True) -> dict[object, SlotBaseline]:
    buckets: dict[object, list[float]] = {}
    for ts, v in points:
        key = slot_of(ts) if by_weekday else hour_slot(ts)
        buckets.setdefault(key, []).append(float(v))
    out = {}
    for key, vals in buckets.items():
        med = median(vals)
        mad = median(abs(x - med) for x in vals)
        out[key] = SlotBaseline(key, len(vals), med, mad)
    return out


@dataclass(frozen=True)
class SeasonalVerdict:
    status: str    # ANOMALY | SEASONAL_NORMAL | NOT_CALCULABLE
    value: float
    expected: float | None
    z: float | None
    n: int
    detail: str
    seasonality_used: str


def evaluate(value: float, ts: datetime, history: Sequence[Point], z_threshold: float = 4.0,
             min_rel_change: float = 0.5) -> SeasonalVerdict:
    """Compare `value` with the same weekday+hour history; fall back to hour-of-day only when sparse.
    A raw spike that matches the slot's usual level is SEASONAL_NORMAL, not an anomaly."""
    weekly = build_slot_baselines(history, by_weekday=True).get(slot_of(ts))
    used, base = "weekday+hour", weekly
    if base is None or base.n < MIN_SAMPLES_PER_SLOT:
        daily = build_slot_baselines(history, by_weekday=False).get(hour_slot(ts))
        used, base = "hour-of-day", daily
    if base is None or base.n < MIN_SAMPLES_PER_SLOT:
        return SeasonalVerdict("NOT_CALCULABLE", value, None, None, base.n if base else 0,
                               f"fewer than {MIN_SAMPLES_PER_SLOT} comparable samples", "none")
    scale = max(base.mad * MAD_K, abs(base.median) * 0.05, 1e-9)    # floor avoids z explosion on flat series
    z = (value - base.median) / scale
    rel = abs(value - base.median) / abs(base.median) if base.median else float("inf")
    if abs(z) >= z_threshold and rel >= min_rel_change:
        return SeasonalVerdict("ANOMALY", value, base.median, z, base.n,
                               f"{value:g} vs expected {base.median:g} for this slot (z={z:.1f}, {rel:.0%} off)", used)
    return SeasonalVerdict("SEASONAL_NORMAL", value, base.median, z, base.n, "within the usual range for this slot", used)
