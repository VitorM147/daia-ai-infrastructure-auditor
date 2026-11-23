"""Static lint of monitor queries. Heuristics with explicit confidence; never edits anything."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping

SCOPE_RX = re.compile(r"\{([^{}]*)\}")


@dataclass(frozen=True)
class LintIssue:
    monitor_id: str
    code: str
    severity: str        # P2 | P3
    detail: str
    evidence: str
    confidence: str      # ALTA = pattern is unambiguous; MEDIA = needs metric tag check
    verify: str          # how a human validates it (read-only)


def _scopes(query: str) -> list[str]:
    return SCOPE_RX.findall(query)


def _mixed_and_or_without_parens(scope: str) -> bool:
    depth, tokens_by_depth = 0, {0: set()}
    for tok in re.findall(r"\(|\)|\band\b|\bor\b", scope, flags=re.IGNORECASE):
        if tok == "(":
            depth += 1
            tokens_by_depth.setdefault(depth, set())
        elif tok == ")":
            tokens_by_depth.pop(depth, None)
            depth = max(0, depth - 1)
        else:
            tokens_by_depth.setdefault(depth, set()).add(tok.lower())
    return any({"and", "or"} <= s for s in tokens_by_depth.values())


def lint_query(monitor_id: str, query: str, service_frameworks: Mapping[str, str] | None = None) -> list[LintIssue]:
    issues: list[LintIssue] = []
    q = query or ""
    if re.search(r"\benv:prd\b", q):
        issues.append(LintIssue(monitor_id, "ENV_TAG_PRD", "P2", "query filters env:prd; the corporate environment tag observed elsewhere is env:prod",
                                "env:prd", "ALTA", "list the real values of the env tag on the metric (Metrics Explorer, group by env)"))
    for sc in _scopes(q):
        if _mixed_and_or_without_parens(sc):
            issues.append(LintIssue(monitor_id, "AND_OR_PRECEDENCE", "P2",
                                    "scope mixes AND and OR without parentheses; one term may escape the other filters (e.g. the environment)",
                                    sc.strip()[:160], "MEDIA", "test each OR branch alone in Metrics Explorer and compare the series returned"))
    if re.search(r"(?<![a-z_])cluster_name:", q):
        issues.append(LintIssue(monitor_id, "CLUSTER_TAG_NAME", "P2",
                                "query uses cluster_name; sibling Kubernetes monitors use kube_cluster_name",
                                "cluster_name:", "MEDIA", "group the same metric by kube_cluster_name and by cluster_name and compare series counts"))
    if "datadog.apis.usage." in q:
        issues.append(LintIssue(monitor_id, "LEGACY_API_USAGE_METRIC", "P3",
                                "uses the legacy datadog.apis.usage.* namespace, documented as replaced by datadog.apis.rate_limit.usage.*",
                                "datadog.apis.usage.", "ALTA", "confirm the metric still returns data; see rule DAIA-DOC-API-003"))
    m = re.search(r"trace\.(http|netty|servlet|express|spring)\.request", q)
    svc = re.search(r"service:([A-Za-z0-9_.\-*]+)", q)
    if m and svc and service_frameworks:
        fw = service_frameworks.get(svc.group(1))
        if fw and fw != m.group(1):
            issues.append(LintIssue(monitor_id, "APM_METRIC_FRAMEWORK_MISMATCH", "P2",
                                    f"query uses trace.{m.group(1)}.request but the service was observed with framework '{fw}'",
                                    m.group(0), "MEDIA", f"query trace.{fw}.request.hits for the service; if it has data and the monitor metric has none, the monitor is blind"))
    if re.search(r"\bdefault_zero\s*\(", q) is None and re.search(r"\.as_count\(\)\s*/\s*", q) and "clamp_min" not in q:
        issues.append(LintIssue(monitor_id, "RATIO_WITHOUT_ZERO_GUARD", "P3", "ratio of counts without clamp_min/default_zero can yield NaN or No Data when the denominator is zero",
                                "as_count() / ...", "MEDIA", "evaluate the query over an idle window"))
    return issues


def duplicate_groups(monitors: Iterable[Mapping[str, object]]) -> list[list[str]]:
    """Monitors whose normalised query is identical (same thresholds too)."""
    groups: dict[str, list[str]] = {}
    for m in monitors:
        key = re.sub(r"\s+", "", str(m.get("query", ""))).lower()
        if key:
            groups.setdefault(key, []).append(str(m["id"]))
    return [ids for ids in groups.values() if len(ids) > 1]
