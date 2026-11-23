"""Partial failures: one instance behaving differently from its peers."""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Mapping

MIN_PEERS = 4


@dataclass(frozen=True)
class InstanceOutlier:
    instance: str
    value: float
    peer_median: float
    ratio: float | None
    direction: str


@dataclass(frozen=True)
class PeerAnalysis:
    status: str          # OUTLIERS | UNIFORM | NOT_CALCULABLE | SERVICE_WIDE
    outliers: tuple[InstanceOutlier, ...]
    detail: str


def find_outliers(values: Mapping[str, float], min_rel: float = 1.0, higher_is_worse: bool = True) -> PeerAnalysis:
    """Robust peer comparison. If *most* peers are bad the problem is service-wide, not partial."""
    if len(values) < MIN_PEERS:
        return PeerAnalysis("NOT_CALCULABLE", (), f"{len(values)} instances; need >= {MIN_PEERS}")
    med = median(values.values())
    mad = median(abs(v - med) for v in values.values())
    scale = max(mad * 1.4826, abs(med) * 0.1, 1e-9)
    found = []
    for inst, v in values.items():
        z = (v - med) / scale
        rel = abs(v - med) / abs(med) if med else float("inf")
        if abs(z) >= 3.5 and rel >= min_rel:
            direction = "HIGH" if v > med else "LOW"
            if (direction == "HIGH") == higher_is_worse:
                found.append(InstanceOutlier(inst, v, med, (v / med) if med else None, direction))
    if not found:
        return PeerAnalysis("UNIFORM", (), "no instance deviates from its peers")
    if len(found) > len(values) / 2:
        return PeerAnalysis("SERVICE_WIDE", tuple(found), "most instances deviate; not a single-instance problem")
    return PeerAnalysis("OUTLIERS", tuple(found), f"{len(found)} of {len(values)} instances deviate from the peer median")
