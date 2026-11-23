"""Labeled SYNTHETIC cases used to measure the V5.1 detectors.

The numbers produced from these cases measure the detectors against fixtures written by the authors.
They are NOT production precision/recall and must never be reported as such.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from daia.gaps.querylint import lint_query
from daia.logintel.sensitive import mask
from daia.logintel.usage import classify_series
from daia.patterns.growth import detect_growth
from daia.patterns.instances import find_outliers
from daia.patterns.seasonal import evaluate

UTC = timezone.utc
T0 = datetime(2026, 10, 5, tzinfo=UTC)

# (name, query, expected set of lint codes). Physical "prd" names and balanced scopes are negatives.
LINT_CASES = [
    ("env tag prd", "avg:m.x{env:prd,service:a}", {"ENV_TAG_PRD"}),
    ("env tag prod", "avg:m.x{env:prod,service:a}", set()),
    ("physical prd name", "avg:aws.rds.cpuutilization{name:rds-sample-prd*} by {dbinstanceidentifier}", set()),
    ("and/or no parens", "sum:m.x{env:prod and service:a* OR service:b}", {"AND_OR_PRECEDENCE"}),
    ("and/or with parens", "sum:m.x{env:prod AND (service:a* OR service:b)}", set()),
    ("cluster_name", "sum:container.cpu.usage{cluster_name:c1}", {"CLUSTER_TAG_NAME"}),
    ("kube_cluster_name", "sum:container.cpu.usage{kube_cluster_name:c1}", set()),
    ("legacy api metric", "sum:datadog.apis.usage.per_org{*}", {"LEGACY_API_USAGE_METRIC"}),
    ("new api metric", "sum:datadog.apis.rate_limit.usage.per_org_count{*}", set()),
    ("simple", "avg:system.cpu.user{host:h1}", set()),
]

SENSITIVE_CASES = [("pw", "password=Abcd1234x", True), ("email", "contact a.b@example.org now", True),
                   ("clean", "order 42 shipped in 120 ms", False), ("plain number", "order id 1234567890123456", False),
                   ("bearer", "Authorization: Bearer abcdefghijklmnop1234", True)]

# (name, series, expected status)
USAGE_CASES = [("growth", [10, 11, 9, 10, 10, 11, 30, 32, 31], "GROWTH"), ("drop", [100, 98, 102, 100, 99, 101, 10, 12, 11], "DROP"),
               ("stopped", [50, 52, 48, 50, 51, 49, 0, 0, 0], "STOPPED"), ("stable", [10, 11, 9, 10, 10, 11, 10, 11, 10], "STABLE"),
               ("short", [1, 2, 3], "NOT_CALCULABLE")]

GROWTH_CASES = [("leak", [100, 110, 121, 133, 146, 160, 176, 193, 212], "CONTINUOUS_GROWTH"),
                ("sawtooth", [100, 130, 170, 220, 60, 90, 130, 180, 40, 70, 110, 160], "SAWTOOTH_RESTARTS"),
                ("flat", [100, 101, 99, 100, 102, 100, 99, 101, 100], "STABLE")]


def _weekly(batch_hour=2):
    pts = []
    for w in range(4):
        for d in range(7):
            for h in range(24):
                pts.append((T0 + timedelta(weeks=w, days=d, hours=h), (900.0 if h == batch_hour else 100.0) + (h % 3)))
    return pts


SEASONAL_CASES = [("batch at usual hour", 905.0, 2, "SEASONAL_NORMAL"), ("same value at odd hour", 905.0, 14, "ANOMALY"),
                  ("normal level", 101.0, 14, "SEASONAL_NORMAL")]

OUTLIER_CASES = [("one bad pod", {**{f"p{i}": 0.5 + i * 0.01 for i in range(7)}, "bad": 40.0}, "OUTLIERS"),
                 ("service wide", {"a": 1.0, "b": 1.1, "c": 50.0, "d": 52.0, "e": 55.0, "f": 49.0}, "SERVICE_WIDE_OR_NOT_OUTLIERS"),
                 ("uniform", {f"p{i}": 1.0 + i * 0.01 for i in range(6)}, "UNIFORM")]


def run_all() -> dict[str, dict[str, int]]:
    """Return TP/FP/FN/TN per detector. Positive = the detector should raise a signal."""
    res: dict[str, dict[str, int]] = {}

    def acc(name, expected_pos, got_pos):
        r = res.setdefault(name, {"tp": 0, "fp": 0, "fn": 0, "tn": 0})
        r["tp" if expected_pos and got_pos else "fn" if expected_pos else "fp" if got_pos else "tn"] += 1

    for _, q, exp in LINT_CASES:
        got = {i.code for i in lint_query("x", q)}
        for code in {"ENV_TAG_PRD", "AND_OR_PRECEDENCE", "CLUSTER_TAG_NAME", "LEGACY_API_USAGE_METRIC"}:
            acc("querylint", code in exp, code in got)
    for _, text, exp in SENSITIVE_CASES:
        acc("sensitive_masking", exp, mask(text).has_sensitive)
    for _, s, exp in USAGE_CASES:
        got = classify_series(s)[0]
        acc("log_volume", exp in ("GROWTH", "DROP", "STOPPED"), got in ("GROWTH", "DROP", "STOPPED"))
    for _, s, exp in GROWTH_CASES:
        acc("growth", exp != "STABLE", detect_growth(s).status in ("CONTINUOUS_GROWTH", "SAWTOOTH_RESTARTS"))
    hist = _weekly()
    for _, v, hour, exp in SEASONAL_CASES:
        acc("seasonal_anomaly", exp == "ANOMALY", evaluate(v, T0 + timedelta(weeks=5, hours=hour), hist).status == "ANOMALY")
    for _, vals, exp in OUTLIER_CASES:
        acc("instance_outlier", exp == "OUTLIERS", find_outliers(vals).status == "OUTLIERS")
    return res


def metrics(counts: dict[str, int]) -> dict[str, float | None]:
    tp, fp, fn = counts["tp"], counts["fp"], counts["fn"]
    return {"precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None}
