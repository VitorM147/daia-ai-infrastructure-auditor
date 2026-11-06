"""Evidence and metric contracts. All timestamps are required to be UTC."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


class EvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class Provenance:
    source_id: str
    source_kind: str  # metric, span, event, log, export
    collector_version: str
    query_hash: str
    collected_at_utc: datetime
    requested_start_utc: datetime
    requested_end_utc: datetime
    effective_start_utc: datetime
    effective_end_utc: datetime
    pages_read: int = 1
    pages_expected: int | None = None
    errors: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()

    def validate(self) -> None:
        times = (self.collected_at_utc, self.requested_start_utc, self.requested_end_utc,
                 self.effective_start_utc, self.effective_end_utc)
        if any(t.tzinfo != timezone.utc for t in times):
            raise EvidenceError("all provenance timestamps must use UTC")
        if self.requested_start_utc >= self.requested_end_utc:
            raise EvidenceError("requested window must be ordered")
        if self.effective_start_utc >= self.effective_end_utc:
            raise EvidenceError("effective window must be ordered")
        if self.pages_read < 0 or (self.pages_expected is not None and self.pages_expected < self.pages_read):
            raise EvidenceError("invalid pagination metadata")
        if not self.source_id or not self.collector_version or not self.query_hash:
            raise EvidenceError("source, collector version and query hash are required")


@dataclass(frozen=True)
class MetricPoint:
    metric_id: str
    timestamp_utc: datetime
    value: float
    unit: str
    resource_id: str
    service: str | None = None
    environment: str | None = None
    tags: tuple[tuple[str, str], ...] = ()
    source_id: str = ""
    source_kind: str = "metric"
    sample_fraction: float = 1.0

    def validate(self) -> None:
        if self.timestamp_utc.tzinfo != timezone.utc:
            raise EvidenceError("metric timestamp must be UTC")
        if self.value != self.value or self.value in (float("inf"), float("-inf")):
            raise EvidenceError("metric value must be finite")
        if not self.metric_id or not self.unit or not self.resource_id or not self.source_id:
            raise EvidenceError("metric identity, unit, resource and source are required")
        if not 0 < self.sample_fraction <= 1:
            raise EvidenceError("sample_fraction must be in (0, 1]")
        if tuple(sorted(self.tags)) != self.tags:
            raise EvidenceError("tags must be sorted for deterministic identity")

    @property
    def identity(self) -> tuple[Any, ...]:
        return (self.metric_id, self.resource_id, self.service, self.environment, self.tags, self.unit)


@dataclass(frozen=True)
class EvidencePackage:
    schema_version: str
    package_id: str
    provenance: Provenance
    points: tuple[MetricPoint, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    data_classification: str = "internal-synthetic"

    def validate(self) -> None:
        if self.schema_version != "evidence-v1":
            raise EvidenceError("unsupported evidence schema")
        if not self.package_id:
            raise EvidenceError("package_id is required")
        self.provenance.validate()
        for point in self.points:
            point.validate()
            if not self.provenance.effective_start_utc <= point.timestamp_utc < self.provenance.effective_end_utc:
                raise EvidenceError("point falls outside effective window")
        if not self.points and not self.provenance.errors:
            raise EvidenceError("empty evidence requires a recorded source error")


def utc(*args: int) -> datetime:
    """Small fixture helper: utc(year, month, day, hour=0, minute=0)."""
    values = list(args) + [0] * (5 - len(args))
    return datetime(*values[:5], tzinfo=timezone.utc)
