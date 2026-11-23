"""Alert intelligence: alerts are evidence, not output.

Deduplicates, groups by (service, problem), tracks recurrence and worsening, and decides whether a
*new* finding deserves attention. It never sends anything: ``notify`` is a decision, and external
delivery requires an explicit, separately configured channel (``channel_enabled``).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence

SEV_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3, "P4": 4, "P5": 5}
REASONS = ("CRITICAL_UNDETECTED", "SILENT_FAILURE", "SIGNIFICANT_WORSENING", "NEW_STRONG_HYPOTHESIS", "RECURRENT_UNRESOLVED")


@dataclass(frozen=True)
class Alert:
    monitor_id: str
    service: str
    problem: str            # normalised problem class, e.g. "error_rate"
    severity: str           # P0..P5
    at: datetime
    value: float | None = None
    source: str = "monitor"  # monitor | daia


@dataclass
class Group:
    key: str
    service: str
    problem: str
    alerts: list[Alert] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.alerts)

    @property
    def monitors(self) -> set[str]:
        return {a.monitor_id for a in self.alerts}

    @property
    def worst(self) -> str:
        return min((a.severity for a in self.alerts), key=lambda s: SEV_RANK[s])


def group_key(service: str, problem: str) -> str:
    return hashlib.sha256(f"{service.lower()}|{problem.lower()}".encode()).hexdigest()[:16]


def dedupe_alerts(alerts: Iterable[Alert], window: timedelta = timedelta(minutes=5)) -> list[Alert]:
    """Same monitor + service + problem within `window` collapses to the first alert."""
    out: list[Alert] = []
    last: dict[tuple[str, str, str], datetime] = {}
    for a in sorted(alerts, key=lambda x: x.at):
        k = (a.monitor_id, a.service, a.problem)
        if k in last and a.at - last[k] < window:
            continue
        last[k] = a.at
        out.append(a)
    return out


def group_alerts(alerts: Iterable[Alert]) -> dict[str, Group]:
    groups: dict[str, Group] = {}
    for a in alerts:
        k = group_key(a.service, a.problem)
        groups.setdefault(k, Group(k, a.service, a.problem)).alerts.append(a)
    return groups


@dataclass(frozen=True)
class History:
    """Previous notifications: group key -> (last_notified_at, severity_at_that_time, value_at_that_time, resolved)."""
    last: Mapping[str, tuple[datetime, str, float | None, bool]]


@dataclass(frozen=True)
class Finding:
    """A DAIA finding that may or may not be covered by an existing monitor alert."""
    service: str
    problem: str
    severity: str
    detected_by_monitor: bool
    silent: bool = False
    hypothesis_strength: str = "NONE"   # NONE | WEAK | STRONG
    resolved: bool = False


@dataclass(frozen=True)
class Decision:
    key: str
    service: str
    problem: str
    notify: bool
    reason: str                 # one of REASONS or a suppression reason
    detail: str
    external_delivery: bool = False   # always False unless a channel is explicitly enabled


def decide(finding: Finding, group: Group | None, history: History, now: datetime, cooldown: timedelta = timedelta(hours=24),
           worsening_factor: float = 1.5, channel_enabled: bool = False) -> Decision:
    key = group_key(finding.service, finding.problem)
    prev = history.last.get(key)
    wrap = lambda notify, reason, detail: Decision(key, finding.service, finding.problem, notify, reason, detail,
                                                   external_delivery=bool(notify and channel_enabled))
    if finding.resolved:
        return wrap(False, "SUPPRESSED_RESOLVED", "finding resolved")
    in_cooldown = prev is not None and (now - prev[0]) < cooldown and not prev[3]
    # 1. critical and not detected by any monitor
    if finding.severity in ("P0", "P1") and not finding.detected_by_monitor and not (prev and not prev[3] and in_cooldown):
        return wrap(True, "CRITICAL_UNDETECTED", "P0/P1 condition with no monitor alert")
    # 2. worsening vs the last notification
    if prev and group and group.alerts and not prev[3]:
        worst_now = SEV_RANK[group.worst]
        if worst_now < SEV_RANK[prev[1]]:
            return wrap(True, "SIGNIFICANT_WORSENING", f"severity moved {prev[1]} -> {group.worst}")
        vals = [a.value for a in group.alerts if a.value is not None]
        if vals and prev[2] not in (None, 0) and max(vals) >= prev[2] * worsening_factor:
            return wrap(True, "SIGNIFICANT_WORSENING", f"value grew {max(vals) / prev[2]:.1f}x since the last notification")
    if in_cooldown:
        return wrap(False, "SUPPRESSED_COOLDOWN", f"already notified {int((now - prev[0]).total_seconds() // 3600)}h ago; no worsening")
    # 3. silent failure
    if finding.silent and not finding.detected_by_monitor:
        return wrap(True, "SILENT_FAILURE", "degradation not detected by any monitor")
    # 4. strong new hypothesis
    if finding.hypothesis_strength == "STRONG" and prev is None:
        return wrap(True, "NEW_STRONG_HYPOTHESIS", "new hypothesis with strong evidence")
    # 5. recurrent and unresolved beyond cooldown
    if prev is not None and not prev[3]:
        return wrap(True, "RECURRENT_UNRESOLVED", "problem persists past the cooldown")
    if finding.detected_by_monitor:
        return wrap(False, "SUPPRESSED_ALREADY_ALERTED", "monitor already alerts; DAIA does not repeat it")
    return wrap(False, "SUPPRESSED_LOW_VALUE", "no criterion for notification met")


def suppress_redundant_recommendations(recs: Iterable[Mapping[str, str]]) -> list[Mapping[str, str]]:
    """Keep one recommendation per (service, action)."""
    seen, out = set(), []
    for r in recs:
        k = (r.get("service", "").lower(), r.get("action", "").lower())
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


def noise_summary(raw: Sequence[Alert], deduped: Sequence[Alert], groups: Mapping[str, Group], decisions: Sequence[Decision]) -> dict[str, object]:
    notified = [d for d in decisions if d.notify]
    return {"raw_alerts": len(raw), "after_dedup": len(deduped), "groups": len(groups), "decisions": len(decisions),
            "would_notify": len(notified), "suppressed": len(decisions) - len(notified),
            "reduction_pct": round(100 * (1 - len(notified) / len(raw)), 1) if raw else 0.0,
            "external_deliveries": sum(1 for d in decisions if d.external_delivery)}
