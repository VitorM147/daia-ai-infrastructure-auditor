"""Correlation checks and the hypothesis contract (evidence for, against, alternatives, method, limits)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import Sequence

from .seasonal import Point

MIN_WINDOW_SAMPLES = 5


@dataclass(frozen=True)
class DeployImpact:
    status: str     # CHANGED | NO_CHANGE | NOT_CALCULABLE
    before: float | None
    after: float | None
    ratio: float | None
    n_before: int
    n_after: int
    detail: str


def deploy_impact(points: Sequence[Point], deploy_at: datetime, window: timedelta, min_rel: float = 0.5) -> DeployImpact:
    before = [v for ts, v in points if deploy_at - window <= ts < deploy_at]
    after = [v for ts, v in points if deploy_at <= ts < deploy_at + window]
    if len(before) < MIN_WINDOW_SAMPLES or len(after) < MIN_WINDOW_SAMPLES:
        return DeployImpact("NOT_CALCULABLE", None, None, None, len(before), len(after),
                            f"need >= {MIN_WINDOW_SAMPLES} samples on each side")
    b, a = median(before), median(after)
    ratio = (a / b) if b else None
    changed = (b == 0 and a > 0) or (ratio is not None and abs(ratio - 1) >= min_rel)
    return DeployImpact("CHANGED" if changed else "NO_CHANGE", b, a, ratio, len(before), len(after),
                        "median shifted across the deploy" if changed else "no material shift across the deploy")


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n != len(ys) or n < 6:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sx = sum((x - mx) ** 2 for x in xs)
    sy = sum((y - my) ** 2 for y in ys)
    if sx == 0 or sy == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy) ** 0.5


@dataclass(frozen=True)
class Hypothesis:
    statement: str
    evidence_for: tuple[str, ...]
    evidence_against: tuple[str, ...]
    alternatives: tuple[str, ...]
    method: str
    limitations: tuple[str, ...]
    confidence: str      # computed, never supplied
    status: str          # HIPOTESE | INFERIDO_FRACO | NAO_VERIFICADO
    reasons: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in self.__dict__.items()}


def build_hypothesis(statement: str, evidence_for: Sequence[str], evidence_against: Sequence[str],
                     alternatives: Sequence[str], method: str, limitations: Sequence[str],
                     same_identifier_proof: bool = False) -> Hypothesis:
    """Confidence is derived from completeness; a hypothesis never reaches 'confirmed' here."""
    reasons = []
    if not evidence_for:
        reasons.append("no supporting evidence")
    if not evidence_against:
        reasons.append("no counter-evidence listed (a hypothesis without counter-evidence is not reviewed)")
    if not alternatives:
        reasons.append("no alternative explanation listed")
    if not method.strip():
        reasons.append("no validation method")
    if not limitations:
        reasons.append("no data limitations listed")
    if reasons:
        return Hypothesis(statement, tuple(evidence_for), tuple(evidence_against), tuple(alternatives), method,
                          tuple(limitations), "BAIXA", "NAO_VERIFICADO", tuple(reasons))
    conf = "MEDIA" if same_identifier_proof else "BAIXA"
    status = "INFERIDO_FRACO" if same_identifier_proof else "HIPOTESE"
    return Hypothesis(statement, tuple(evidence_for), tuple(evidence_against), tuple(alternatives), method,
                      tuple(limitations), conf, status, ())
