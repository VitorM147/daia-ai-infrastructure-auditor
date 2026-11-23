"""Read-only review of index configuration + exclusion candidates. Recommendations only."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from daia.docs_intel.catalog import Catalog

from .patterns import PatternStat

NEAR_QUOTA = 0.8   # the official guide suggests alerting at 80 percent of the daily quota


@dataclass(frozen=True)
class IndexFinding:
    index: str
    kind: str          # NO_DAILY_QUOTA | QUOTA_NEAR | QUOTA_REACHED | RETENTION_UNKNOWN | UNQUERIED_CANDIDATE | DATA_MISSING
    rule_id: str
    detail: str
    cost_status: str
    action: str = "RECOMMEND_ONLY"
    verification: str = "OBSERVADO"


def review_indexes(indexes: Iterable[Mapping[str, object]], catalog: Catalog | None = None) -> list[IndexFinding]:
    """`indexes` come from an authorised GET/list call. Missing fields stay NAO_VERIFICADO, never defaulted."""
    cat = catalog or Catalog.load()
    out: list[IndexFinding] = []
    cost = lambda rid: cat.get(rid).cost_status
    for ix in indexes:
        name = str(ix.get("name", "<unnamed>"))
        quota, used = ix.get("daily_quota"), ix.get("indexed_24h")
        if "daily_quota" not in ix:
            out.append(IndexFinding(name, "DATA_MISSING", "DAIA-DOC-LOG-002", "daily_quota not provided; cannot assess", cost("DAIA-DOC-LOG-002"), verification="NAO_VERIFICADO"))
        elif quota in (None, 0):
            out.append(IndexFinding(name, "NO_DAILY_QUOTA", "DAIA-DOC-LOG-002",
                                    "index has no daily quota; a new noisy source or debug level can raise usage unnoticed. Review with the owner; do not set automatically.", cost("DAIA-DOC-LOG-002")))
        elif isinstance(used, (int, float)):
            ratio = used / float(quota)
            if ratio >= 1:
                out.append(IndexFinding(name, "QUOTA_REACHED", "DAIA-DOC-LOG-003", f"indexed {used:.0f} of quota {quota:.0f} in 24h; new logs may be dropped from the index", cost("DAIA-DOC-LOG-003")))
            elif ratio >= NEAR_QUOTA:
                out.append(IndexFinding(name, "QUOTA_NEAR", "DAIA-DOC-LOG-003", f"{ratio:.0%} of the daily quota in 24h (guide suggests alerting at {NEAR_QUOTA:.0%})", cost("DAIA-DOC-LOG-003")))
        if ix.get("retention_days") is None:
            out.append(IndexFinding(name, "RETENTION_UNKNOWN", "DAIA-DOC-LOG-001", "retention not provided; do not suggest changes without legal/security requirements", cost("DAIA-DOC-LOG-001"), verification="NAO_VERIFICADO"))
        if ix.get("queries_30d") == 0:
            out.append(IndexFinding(name, "UNQUERIED_CANDIDATE", "DAIA-DOC-LOG-008",
                                    "no queries observed in 30d (source: Audit Trail, a billable product). Evaluate retention/tier only with the owner.", cost("DAIA-DOC-LOG-008")))
    return out


@dataclass(frozen=True)
class ExclusionCandidate:
    service: str
    template: str
    share: float
    decision: str      # CANDIDATE | BLOCKED_PROTECTED | BLOCKED_LOW_VOLUME | BLOCKED_INFRA_TELEMETRY_REVIEW
    reason: str
    rule_id: str = "DAIA-DOC-LOG-007"
    cost_status: str = "CUSTO_DESCONHECIDO"
    action: str = "RECOMMEND_ONLY"


def exclusion_candidates(stats: Iterable[PatternStat], min_share: float = 0.05, catalog: Catalog | None = None) -> list[ExclusionCandidate]:
    cost = (catalog or Catalog.load()).get("DAIA-DOC-LOG-007").cost_status
    out = []
    for s in stats:
        if s.protected:
            out.append(ExclusionCandidate(s.service, s.template, s.share, "BLOCKED_PROTECTED",
                                          "pattern looks like error/security/payment/audit evidence; exclusion could remove incident evidence", cost_status=cost))
        elif s.share < min_share:
            out.append(ExclusionCandidate(s.service, s.template, s.share, "BLOCKED_LOW_VOLUME", f"share {s.share:.1%} below {min_share:.0%}", cost_status=cost))
        elif s.origin == "infrastructure":
            out.append(ExclusionCandidate(s.service, s.template, s.share, "BLOCKED_INFRA_TELEMETRY_REVIEW",
                                          "infrastructure telemetry; fix the emitter or its log level at the source before excluding", cost_status=cost))
        else:
            out.append(ExclusionCandidate(s.service, s.template, s.share, "CANDIDATE",
                                          f"repetitive non-error pattern with {s.share:.1%} of analysed logs; keep log-based metrics if a trend is needed", cost_status=cost))
    return out
