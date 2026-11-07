"""Limit policy, budget accounting and rate limiting for audits.

Limits come only from an explicit configuration file. Raising any limit above
the configured value (scope expansion) requires a recorded human approval;
lowering is always allowed. Exceeding a budget stops the audit cleanly with
status INCOMPLETA, it never silently truncates into a "complete" result.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

LIMITS_PATH = Path(__file__).resolve().parent.parent / "config" / "orchestration-limits.json"

LIMIT_KEYS = ("max_runtime_s", "max_queries", "max_concurrency", "max_pages_per_query", "page_size",
              "max_items_per_query", "max_data_bytes", "max_tokens", "max_cost_usd", "max_retries",
              "max_backoff_s", "max_queries_per_second")


class LimitPolicyError(ValueError):
    pass


class BudgetExceeded(RuntimeError):
    def __init__(self, limit: str, used: Any, maximum: Any):
        super().__init__(f"limite '{limit}' atingido ({used} de {maximum})")
        self.limit, self.used, self.maximum = limit, used, maximum


@dataclass(frozen=True)
class ScopeApproval:
    approver: str
    reason: str
    approved_at_utc: str
    approval_id: str

    def validate(self) -> None:
        if not all([self.approver, self.reason, self.approved_at_utc, self.approval_id]):
            raise LimitPolicyError("aprovação de ampliação incompleta (approver, reason, approved_at_utc, approval_id)")


@dataclass(frozen=True)
class LimitPolicy:
    version: str
    limits: dict[str, float]
    staleness_ttl_s: dict[str, int]
    defaults: dict[str, Any]
    source: str
    expansions: tuple[dict[str, Any], ...] = ()

    @classmethod
    def load(cls, path: Path = LIMITS_PATH) -> "LimitPolicy":
        data = json.loads(path.read_text(encoding="utf-8"))
        limits = data.get("limits", {})
        missing = [k for k in LIMIT_KEYS if k not in limits]
        if missing:
            raise LimitPolicyError(f"limites não configurados: {missing} (não há valores implícitos)")
        for k in LIMIT_KEYS:
            v = limits[k]
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0:
                raise LimitPolicyError(f"limite inválido {k}={v!r}")
        for k in ("max_concurrency", "max_pages_per_query", "page_size", "max_queries", "max_runtime_s"):
            if limits[k] <= 0:
                raise LimitPolicyError(f"{k} deve ser > 0")
        return cls(data["version"], dict(limits), dict(data.get("staleness_ttl_s", {})), dict(data.get("defaults", {})),
                   data.get("source", ""))

    def with_overrides(self, overrides: Mapping[str, float], approval: ScopeApproval | None = None) -> "LimitPolicy":
        unknown = set(overrides) - set(LIMIT_KEYS)
        if unknown:
            raise LimitPolicyError(f"limites desconhecidos: {sorted(unknown)}")
        increases = {k: v for k, v in overrides.items() if v > self.limits[k]}
        if increases:
            if approval is None:
                raise LimitPolicyError(f"ampliação de escopo sem aprovação humana: {increases}")
            approval.validate()
        new = dict(self.limits)
        new.update(overrides)
        record = {"overrides": dict(overrides), "increases": increases,
                  "approval": approval.__dict__ if approval else None}
        return LimitPolicy(self.version, new, self.staleness_ttl_s, self.defaults, self.source, self.expansions + (record,))

    def ttl(self, domain: str) -> int:
        return int(self.staleness_ttl_s.get(domain, 900))

    def as_dict(self) -> dict[str, Any]:
        return {"version": self.version, "limits": self.limits, "staleness_ttl_s": self.staleness_ttl_s,
                "source": self.source, "expansions": list(self.expansions)}


@dataclass
class Budget:
    """Thread-safe usage tracker. Usage survives resumption (loaded from checkpoint)."""
    policy: LimitPolicy
    clock: Callable[[], float] = time.monotonic
    used: dict[str, float] = field(default_factory=lambda: {"queries": 0, "data_bytes": 0, "tokens": 0, "cost_usd": 0.0,
                                                            "retries": 0, "runtime_s": 0.0})
    _started: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def start(self) -> None:
        self._started = self.clock()

    def _runtime(self) -> float:
        return self.used["runtime_s"] + ((self.clock() - self._started) if self._started is not None else 0.0)

    def check_runtime(self) -> None:
        if self._runtime() > self.policy.limits["max_runtime_s"]:
            raise BudgetExceeded("max_runtime_s", round(self._runtime(), 1), self.policy.limits["max_runtime_s"])

    def charge_query(self) -> None:
        with self._lock:
            self.check_runtime()
            if self.used["queries"] + 1 > self.policy.limits["max_queries"]:
                raise BudgetExceeded("max_queries", self.used["queries"], self.policy.limits["max_queries"])
            self.used["queries"] += 1

    def charge_data(self, nbytes: int) -> None:
        with self._lock:
            self.used["data_bytes"] += nbytes
            if self.used["data_bytes"] > self.policy.limits["max_data_bytes"]:
                raise BudgetExceeded("max_data_bytes", self.used["data_bytes"], self.policy.limits["max_data_bytes"])

    def charge_llm(self, tokens: int, cost_usd: float) -> None:
        """For optional LLM steps. With the default policy (0/0) any use is refused."""
        with self._lock:
            if self.used["tokens"] + tokens > self.policy.limits["max_tokens"]:
                raise BudgetExceeded("max_tokens", self.used["tokens"] + tokens, self.policy.limits["max_tokens"])
            if self.used["cost_usd"] + cost_usd > self.policy.limits["max_cost_usd"]:
                raise BudgetExceeded("max_cost_usd", self.used["cost_usd"] + cost_usd, self.policy.limits["max_cost_usd"])
            self.used["tokens"] += tokens
            self.used["cost_usd"] += cost_usd

    def charge_retry(self) -> bool:
        with self._lock:
            self.used["retries"] += 1
            return True

    def snapshot(self) -> dict[str, float]:
        with self._lock:
            out = dict(self.used)
            out["runtime_s"] = round(self._runtime(), 3)
            return out


class RateLimiter:
    """Minimum interval between dispatches (max_queries_per_second)."""

    def __init__(self, qps: float, clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.interval = 1.0 / qps if qps > 0 else 0.0
        self.clock, self.sleep = clock, sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self.clock()
            wait = self._next - now
            self._next = max(now, self._next) + self.interval
        if wait > 0:
            self.sleep(wait)
