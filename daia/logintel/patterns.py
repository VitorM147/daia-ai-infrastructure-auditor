"""Log pattern analysis: templates, deduplication, empty messages, origin classification."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Iterable, Mapping

from .sensitive import mask

_SUBS = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<UUID>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<IP>"),
    (re.compile(r"\b[0-9a-fA-F]{16,}\b"), "<HEX>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?Z?"), "<TS>"),
    (re.compile(r"\b\d+(?:\.\d+)?\b"), "<N>"),
]

# Origins that are telemetry/infrastructure, not business application errors. Extend via data, not code paths.
INFRA_SERVICES = frozenset({"kubeturbo", "opentelemetry-collector-contrib", "fluentd", "datadog-agent", "coredns",
                            "kube-proxy", "aws-node", "node-exporter", "data-prepper", "twistlock", "zabbix-agent"})
INFRA_PREFIXES = ("kube-", "ebs-csi", "cluster-agent", "datadog-")

# Never propose excluding these: they are evidence for incidents, security or audit.
PROTECTED_KEYWORDS = ("auth", "login", "denied", "forbidden", "unauthor", "audit", "security", "payment", "pagamento",
                      "fraud", "exception", "fatal", "panic", "oom", "outofmemory", "timeout", "refused", "error", "fail", "falha", "erro")


def template(message: str) -> str:
    out = mask(message or "").text
    for rx, repl in _SUBS:
        out = rx.sub(repl, out)
    return re.sub(r"\s+", " ", out).strip()[:200]


def classify_origin(service: str | None, source: str | None = None) -> str:
    s = (service or "").lower()
    if not s or s == "undefined":
        return "unknown"
    if s in INFRA_SERVICES or s.startswith(INFRA_PREFIXES):
        return "infrastructure"
    if (source or "").lower() in {"kubernetes", "containerd", "docker", "cloudwatch"}:
        return "infrastructure"
    return "application"


@dataclass(frozen=True)
class PatternStat:
    service: str
    template: str
    count: int
    share: float
    levels: tuple[str, ...]
    origin: str
    protected: bool


@dataclass(frozen=True)
class DedupResult:
    raw: int
    unique: int
    duplicates: int
    empty_messages: int
    empty_ratio: float
    caveat: str


def dedupe(logs: Iterable[Mapping[str, object]]) -> DedupResult:
    """Unique key = (trace_id, span_id, message). Logs without ids cannot be proven duplicates."""
    seen, raw, empty, no_ids = set(), 0, 0, 0
    for log in logs:
        raw += 1
        msg = str(log.get("message") or "")
        if not msg.strip():
            empty += 1
        tid, sid = log.get("trace_id"), log.get("span_id")
        if not tid or not sid:
            no_ids += 1
            seen.add(("noid", raw))      # kept as unique: absence of ids is not proof of duplication
            continue
        seen.add((tid, sid, msg))
    unique = len(seen)
    caveat = f"{no_ids} log(s) without trace/span id counted as unique" if no_ids else "all logs carry trace/span ids"
    return DedupResult(raw, unique, raw - unique, empty, (empty / raw) if raw else 0.0, caveat)


def pattern_stats(logs: Iterable[Mapping[str, object]], top: int = 20) -> list[PatternStat]:
    counts: Counter[tuple[str, str]] = Counter()
    levels: dict[tuple[str, str], set[str]] = defaultdict(set)
    total = 0
    for log in logs:
        msg = str(log.get("message") or "")
        if not msg.strip():
            continue
        key = (str(log.get("service") or "undefined"), template(msg))
        counts[key] += 1
        levels[key].add(str(log.get("status") or "unknown").lower())
        total += 1
    out = []
    for (svc, tpl), n in counts.most_common(top):
        out.append(PatternStat(svc, tpl, n, n / total if total else 0.0, tuple(sorted(levels[(svc, tpl)])),
                               classify_origin(svc), is_protected(tpl, levels[(svc, tpl)])))
    return out


def is_protected(tpl: str, levels: Iterable[str]) -> bool:
    low = tpl.lower()
    if any(k in low for k in PROTECTED_KEYWORDS):
        return True
    return any(l in {"error", "critical", "alert", "emergency"} for l in levels)
