"""Continuous growth (leak-like) detection that tolerates restarts, and rising restart counts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

MIN_POINTS = 8


@dataclass(frozen=True)
class GrowthVerdict:
    status: str       # CONTINUOUS_GROWTH | SAWTOOTH_RESTARTS | STABLE | NOT_CALCULABLE
    segments: int
    growing_segments: int
    detail: str


def _segments(values: Sequence[float], drop_ratio: float) -> list[list[float]]:
    segs, cur = [], [values[0]]
    for prev, v in zip(values, values[1:]):
        if prev > 0 and v < prev * drop_ratio:      # sharp drop = restart/GC-style reset
            segs.append(cur)
            cur = [v]
        else:
            cur.append(v)
    segs.append(cur)
    return segs


def _slope_up(seg: Sequence[float], min_rel: float) -> bool:
    if len(seg) < 3:
        return False
    first = sum(seg[:2]) / 2
    last = sum(seg[-2:]) / 2
    rises = sum(1 for a, b in zip(seg, seg[1:]) if b >= a)
    mono = rises / (len(seg) - 1)
    return first > 0 and (last - first) / first >= min_rel and mono >= 0.8


def detect_growth(values: Sequence[float], min_rel: float = 0.2, drop_ratio: float = 0.7) -> GrowthVerdict:
    if len(values) < MIN_POINTS:
        return GrowthVerdict("NOT_CALCULABLE", 0, 0, f"{len(values)} points; need >= {MIN_POINTS}")
    segs = _segments(values, drop_ratio)
    usable = [s for s in segs if len(s) >= 3]
    growing = sum(1 for s in usable if _slope_up(s, min_rel))
    if len(segs) == 1 and growing == 1:
        return GrowthVerdict("CONTINUOUS_GROWTH", 1, 1, "monotonic rise without any reset in the window")
    if len(segs) > 1 and usable and growing == len(usable):
        return GrowthVerdict("SAWTOOTH_RESTARTS", len(segs), growing, "memory grows after each reset; resets suggest restarts hide a leak-like pattern")
    return GrowthVerdict("STABLE", len(segs), growing, "no sustained growth")


def restarts_rising(restarts_per_bucket: Sequence[float], recent: int = 3, factor: float = 2.0, min_total: float = 3) -> bool:
    if len(restarts_per_bucket) < recent + 3:
        return False
    base = sum(restarts_per_bucket[:-recent]) / (len(restarts_per_bucket) - recent)
    last = sum(restarts_per_bucket[-recent:]) / recent
    return sum(restarts_per_bucket[-recent:]) >= min_total and last >= max(base * factor, 1)
