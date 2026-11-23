"""Log ingestion analysis from usage-metric style series (read-only data, offline math).

Input points are what ``datadog.estimated_usage.logs.ingested_*`` style queries return,
already collected by an authorised read-only path. These are estimates, never billing.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Iterable, Mapping, Sequence

MIN_BUCKETS = 6
DISCLAIMER = "Estimativa de uso (metricas estimated_usage); nao e valor de faturamento."


@dataclass(frozen=True)
class ServiceUsage:
    service: str
    total: float
    share: float
    status: str            # GROWTH | DROP | STOPPED | STABLE | NOT_CALCULABLE
    ratio_vs_baseline: float | None
    detail: str


def top_services(points: Iterable[Mapping[str, object]], limit: int = 10) -> list[tuple[str, float, float]]:
    totals: dict[str, float] = {}
    for p in points:
        totals[str(p["service"])] = totals.get(str(p["service"]), 0.0) + float(p["value"])
    grand = sum(totals.values())
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [(s, v, (v / grand) if grand else 0.0) for s, v in ranked]


def classify_series(values: Sequence[float], recent: int = 3, growth_factor: float = 2.0, drop_factor: float = 0.3) -> tuple[str, float | None, str]:
    """Compare the last `recent` buckets with the median of earlier buckets."""
    if len(values) < max(MIN_BUCKETS, recent + 3):
        return "NOT_CALCULABLE", None, f"{len(values)} buckets; need >= {max(MIN_BUCKETS, recent + 3)}"
    base = median(values[:-recent])
    last = sum(values[-recent:]) / recent
    if base == 0:
        return ("GROWTH", None, "baseline is zero; new source or restart of emission") if last > 0 else ("STABLE", None, "no volume in baseline or recent buckets")
    ratio = last / base
    if last == 0:
        return "STOPPED", 0.0, "source emitted at baseline and now emits nothing; verify agent/pipeline before concluding outage"
    if ratio >= growth_factor:
        return "GROWTH", ratio, f"recent average is {ratio:.1f}x the baseline median"
    if ratio <= drop_factor:
        return "DROP", ratio, f"recent average is {ratio:.2f}x the baseline median"
    return "STABLE", ratio, "within the baseline range"


def analyze_services(series_by_service: Mapping[str, Sequence[float]]) -> list[ServiceUsage]:
    grand = sum(sum(v) for v in series_by_service.values())
    out = []
    for svc, vals in series_by_service.items():
        status, ratio, detail = classify_series(list(vals))
        total = float(sum(vals))
        out.append(ServiceUsage(svc, total, (total / grand) if grand else 0.0, status, ratio, detail))
    return sorted(out, key=lambda u: u.total, reverse=True)


def ingested_vs_indexed(ingested: float, indexed: float) -> dict[str, object]:
    if ingested <= 0:
        return {"status": "NOT_CALCULABLE", "detail": "no ingested volume"}
    if indexed > ingested * 1.0001:
        return {"status": "INCONSISTENT", "detail": "indexed exceeds ingested; check the datadog_is_excluded filter and the window"}
    return {"status": "OK", "indexed_ratio": indexed / ingested, "excluded_ratio": 1 - indexed / ingested}


def project_month(mtd_total: float, day_of_month: int, year: int, month: int, daily_recent: Sequence[float],
                  contract: float | None) -> dict[str, object]:
    """Linear projection with an explicit range from the min/max of recent daily values."""
    days = calendar.monthrange(year, month)[1]
    if not 1 <= day_of_month <= days:
        raise ValueError("day_of_month out of range")
    remaining = days - day_of_month
    if len(daily_recent) < 3:
        return {"status": "NOT_CALCULABLE", "detail": "need >= 3 recent daily values", "disclaimer": DISCLAIMER}
    lo, hi, mid = min(daily_recent), max(daily_recent), sum(daily_recent) / len(daily_recent)
    res: dict[str, object] = {"status": "ESTIMATE", "projected_low": mtd_total + lo * remaining,
                              "projected_mid": mtd_total + mid * remaining, "projected_high": mtd_total + hi * remaining,
                              "remaining_days": remaining, "disclaimer": DISCLAIMER}
    if contract is None or contract <= 0:
        res["contract_status"] = "CONTRATO_NAO_INFORMADO"
    else:
        res["contract_status"] = "INFORMADO"
        for k in ("low", "mid", "high"):
            res[f"pct_{k}"] = 100 * res[f"projected_{k}"] / contract
        res["may_exceed"] = res["projected_high"] > contract
        res["will_exceed_mid"] = res["projected_mid"] > contract
    return res
