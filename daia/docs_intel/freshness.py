"""On-demand freshness verification of catalog rules against official pages.

Rules:
- Offline by default. Network is used only through an explicit ``fetch`` callable and a ``QueryBudget``.
- A fetch failure never invalidates a rule; it marks it ``STALE_UNVERIFIED`` (usable, flagged).
- HTTP 429 stops the whole run (no retry loop); ``Retry-After`` / ``X-RateLimit-Period`` is reported.
- Only hosts on the official allow-list are fetched. Page bodies are hashed, never stored.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Callable, Iterable, Mapping
from urllib.parse import urlparse

from .catalog import OFFICIAL_HOSTS, Catalog, Rule

DEFAULT_MAX_AGE_DAYS = 90


@dataclass(frozen=True)
class FetchResult:
    status: int
    body: str = ""
    headers: Mapping[str, str] | None = None


Fetch = Callable[[str], FetchResult]


class QueryBudget:
    def __init__(self, max_requests: int):
        if max_requests < 0:
            raise ValueError("max_requests must be >= 0")
        self.max_requests = max_requests
        self.used = 0

    def take(self) -> bool:
        if self.used >= self.max_requests:
            return False
        self.used += 1
        return True


@dataclass(frozen=True)
class FreshnessVerdict:
    rule_id: str
    status: str   # FRESH | STALE_AGE | STALE_UNVERIFIED | CHANGED | LINK_BROKEN | NOT_CHECKED_BUDGET | RATE_LIMITED
    detail: str
    new_sha256: str | None = None


def _norm(body: str) -> str:
    return re.sub(r"\s+", " ", body).strip()


def page_hash(body: str) -> str:
    return hashlib.sha256(_norm(body).encode("utf-8")).hexdigest()


def age_days(rule: Rule, today: date) -> int | None:
    if not rule.source.verified_at:
        return None
    return (today - date.fromisoformat(rule.source.verified_at)).days


def offline_status(rule: Rule, today: date, max_age_days: int = DEFAULT_MAX_AGE_DAYS) -> FreshnessVerdict:
    """No network. Answers 'is this rule possibly out of date?' from metadata only."""
    age = age_days(rule, today)
    if age is None:
        return FreshnessVerdict(rule.rule_id, "STALE_UNVERIFIED", "never verified against the official page")
    if age > max_age_days:
        return FreshnessVerdict(rule.rule_id, "STALE_AGE", f"verified {age} days ago (limit {max_age_days})")
    return FreshnessVerdict(rule.rule_id, "FRESH", f"verified {age} days ago")


def verify_online(catalog: Catalog, fetch: Fetch, budget: QueryBudget, today: date,
                  rule_ids: Iterable[str] | None = None) -> list[FreshnessVerdict]:
    """Verify rules against their source pages, one request per distinct URL, within budget."""
    wanted = [catalog.get(r) for r in rule_ids] if rule_ids else list(catalog.rules.values())
    by_url: dict[str, list[Rule]] = {}
    for rule in wanted:
        by_url.setdefault(rule.source.url, []).append(rule)
    verdicts: list[FreshnessVerdict] = []
    rate_limited = False
    for url, rules in by_url.items():
        if rate_limited:
            verdicts += [FreshnessVerdict(r.rule_id, "RATE_LIMITED", "run stopped after HTTP 429") for r in rules]
            continue
        if urlparse(url).hostname not in OFFICIAL_HOSTS:
            verdicts += [FreshnessVerdict(r.rule_id, "STALE_UNVERIFIED", "host not on the official allow-list") for r in rules]
            continue
        if not budget.take():
            verdicts += [FreshnessVerdict(r.rule_id, "NOT_CHECKED_BUDGET", "query budget exhausted") for r in rules]
            continue
        try:
            res = fetch(url)
        except Exception as exc:  # network failure must not invalidate a rule
            verdicts += [FreshnessVerdict(r.rule_id, "STALE_UNVERIFIED", f"fetch failed: {type(exc).__name__}") for r in rules]
            continue
        if res.status == 429:
            rate_limited = True
            wait = (res.headers or {}).get("Retry-After") or (res.headers or {}).get("X-RateLimit-Period") or "unknown"
            verdicts += [FreshnessVerdict(r.rule_id, "RATE_LIMITED", f"HTTP 429; wait {wait}s; no retry") for r in rules]
        elif res.status in (404, 410):
            verdicts += [FreshnessVerdict(r.rule_id, "LINK_BROKEN", f"HTTP {res.status}") for r in rules]
        elif res.status != 200:
            verdicts += [FreshnessVerdict(r.rule_id, "STALE_UNVERIFIED", f"HTTP {res.status}") for r in rules]
        else:
            digest = page_hash(res.body)
            for r in rules:
                known = r.source.page_sha256
                if known is None:
                    verdicts.append(FreshnessVerdict(r.rule_id, "FRESH", "page reachable; no previous hash to compare", digest))
                elif known != digest:
                    verdicts.append(FreshnessVerdict(r.rule_id, "CHANGED", "official page changed since last verification; review the rule", digest))
                else:
                    verdicts.append(FreshnessVerdict(r.rule_id, "FRESH", "page unchanged", digest))
    return verdicts


def deprecated_markers(body: str) -> list[str]:
    """Cheap, explainable markers that a page may describe a deprecated/replaced feature."""
    hits = []
    for rx in (r"\bdeprecated\b", r"\blegacy\b", r"\breplaces?\b", r"\bend[- ]of[- ]life\b", r"\bno longer supported\b"):
        if re.search(rx, body, re.IGNORECASE):
            hits.append(rx.strip(r"\b").replace("\\b", ""))
    return hits
