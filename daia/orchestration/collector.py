"""Query execution with caching, staleness, retries, rate limiting and pagination.

All tool access of the orchestrator goes through ``ToolClient``:
- a query already answered and still fresh is served from the audit store
  (no duplicate dispatch on resume);
- a stale answer is re-queried (revalidation) and the event is logged;
- 401/403/policy denials are final for the audit (never retried);
- 429/503/timeout get at most ``max_retries`` retries, honouring Retry-After
  only when it fits ``max_backoff_s``;
- every dispatch is charged to the budget before it happens.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .limits import Budget, BudgetExceeded, LimitPolicy, RateLimiter
from .store import AuditStore, query_key

ToolPort = Callable[[str, Mapping[str, Any]], dict[str, Any]]
PERMANENT = {"UNAUTHENTICATED", "PERMISSION_DENIED", "FORBIDDEN_BY_POLICY", "UNKNOWN_TOOL", "BAD_REQUEST"}
TRANSIENT = {"SOURCE_UNAVAILABLE", "TIMEOUT", "PAGE_UNAVAILABLE"}


class ExternalInterruption(RuntimeError):
    """The data source reported that the execution was interrupted (e.g. upstream budget)."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


@dataclass
class QueryResult:
    key: str
    tool: str
    args: dict[str, Any]
    domain: str
    ok: bool
    data: Any
    error: dict[str, Any] | None
    call_id: str | None
    collected_at: str
    from_cache: bool = False
    revalidated: bool = False


@dataclass
class PageCollection:
    items: list[Any]
    pages_read: int
    complete: bool
    reason: str | None
    call_ids: list[str] = field(default_factory=list)
    keys: list[str] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


class ToolClient:
    def __init__(self, port: ToolPort, store: AuditStore, policy: LimitPolicy, budget: Budget,
                 *, now: Callable[[], datetime] = utc_now, sleep: Callable[[float], None] | None = None,
                 rate_limiter: RateLimiter | None = None):
        import time
        self.port, self.store, self.policy, self.budget = port, store, policy, budget
        self.now = now
        self.sleep = sleep or time.sleep
        self.rate = rate_limiter or RateLimiter(policy.limits["max_queries_per_second"], sleep=self.sleep)
        self.log: list[dict[str, Any]] = []
        self.dispatches = 0
        self.cache_hits = 0
        self.revalidations = 0
        self.blocked: dict[str, dict[str, Any]] = {}   # tool -> {"code", "until"}; circuit breaker, never bypassed
        self._lock = threading.Lock()

    # ------------------------------------------------------------- single query
    def query(self, tool: str, args: Mapping[str, Any], domain: str, *, use_cache: bool = True) -> QueryResult:
        args = dict(args)
        key = query_key(tool, args)
        cached = self.store.get_query(key) if use_cache else None
        revalidate = False
        if cached:
            age = (self.now() - parse_iso(cached["collected_at"])).total_seconds()
            code = (cached.get("error") or {}).get("code")
            if cached["ok"] and age <= self.policy.ttl(domain):
                return self._from_cache(cached)
            if not cached["ok"] and code in PERMANENT:
                return self._from_cache(cached)  # never re-attempt a permanent denial in the same audit
            revalidate = cached["ok"]
        block = self.blocked.get(tool)
        if block and (block["until"] is None or self.now() < block["until"]):
            res = QueryResult(key, tool, args, domain, False, None,
                              {"code": block["code"], "http_status": block.get("http_status"),
                               "message": f"não consultado: {tool} bloqueado nesta execução após {block['code']} (sem contorno)"},
                              None, iso(self.now()))
            self._record(res)
            return res
        result = self._dispatch(tool, args, domain, key)
        result.revalidated = revalidate
        if revalidate:
            with self._lock:
                self.revalidations += 1
            self.store.event("revalidation", key=key, tool=tool, domain=domain, at=result.collected_at)
        return result

    def _from_cache(self, rec: Mapping[str, Any]) -> QueryResult:
        with self._lock:
            self.cache_hits += 1
        res = QueryResult(rec["key"], rec["tool"], rec["args"], rec["domain"], rec["ok"], rec.get("data"), rec.get("error"),
                          rec.get("call_id"), rec["collected_at"], from_cache=True)
        self._record(res)
        return res

    def _dispatch(self, tool: str, args: dict[str, Any], domain: str, key: str) -> QueryResult:
        attempts = 0
        while True:
            self.budget.charge_query()
            self.rate.acquire()
            raw = self.port(tool, args)
            with self._lock:
                self.dispatches += 1
            err = raw.get("error") if not raw.get("ok") else None
            code = (err or {}).get("code")
            if code == "AUDIT_INTERRUPTED":
                self._record(QueryResult(key, tool, args, domain, False, None, err, raw.get("call_id"), iso(self.now())))
                exc = ExternalInterruption(err.get("message", "interrupted"))
                exc.tool, exc.error = tool, dict(err)
                raise exc
            if err and code not in PERMANENT and attempts < self.policy.limits["max_retries"]:
                retry_after = float(err.get("retry_after_s", 0) or 0)
                if code == "RATE_LIMITED" and retry_after > self.policy.limits["max_backoff_s"]:
                    pass  # respect the block: do not wait longer than allowed, do not hammer
                elif code in TRANSIENT or code == "RATE_LIMITED":
                    attempts += 1
                    self.budget.charge_retry()
                    self.store.event("retry", key=key, tool=tool, code=code, wait_s=retry_after)
                    if retry_after:
                        self.sleep(retry_after)
                    continue
            if err:
                self._maybe_block(tool, err, attempts)
            data = raw.get("data") if raw.get("ok") else None
            if data is not None:
                self.budget.charge_data(len(json.dumps(data, default=str)))
            res = QueryResult(key, tool, args, domain, bool(raw.get("ok")), data, err, raw.get("call_id"), iso(self.now()))
            self.store.put_query({"key": key, "tool": tool, "args": args, "domain": domain, "ok": res.ok, "data": data,
                                  "error": err, "call_id": res.call_id, "collected_at": res.collected_at})
            self._record(res)
            return res

    def _maybe_block(self, tool: str, err: Mapping[str, Any], attempts: int) -> None:
        from datetime import timedelta
        code = err.get("code")
        until = None
        if code in ("UNAUTHENTICATED", "PERMISSION_DENIED", "FORBIDDEN_BY_POLICY"):
            until = None  # whole session
        elif code == "RATE_LIMITED":
            until = self.now() + timedelta(seconds=float(err.get("retry_after_s", 0) or 0))
        else:
            return
        with self._lock:
            self.blocked[tool] = {"code": code, "http_status": err.get("http_status"), "until": until}
        self.store.event("tool_blocked", tool=tool, code=code, until=iso(until) if until else "fim da sessão")

    def _record(self, res: QueryResult) -> None:
        with self._lock:
            self.log.append({"key": res.key, "tool": res.tool, "args": res.args, "domain": res.domain, "ok": res.ok,
                             "error_code": (res.error or {}).get("code"), "call_id": res.call_id,
                             "collected_at": res.collected_at, "from_cache": res.from_cache, "revalidated": res.revalidated})

    # --------------------------------------------------------------- pagination
    def paginate(self, tool: str, args: Mapping[str, Any], domain: str, item_key: str, *, style: str = "cursor") -> PageCollection:
        """Read pages until exhausted or a limit is hit. Never reports a partial read as complete."""
        max_pages = int(self.policy.limits["max_pages_per_query"])
        max_items = int(self.policy.limits["max_items_per_query"])
        size = int(self.policy.limits["page_size"])
        items: list[Any] = []
        coll = PageCollection(items, 0, False, None)
        cursor: Any = None if style == "cursor" else 1
        while True:
            page_args = dict(args)
            if style == "cursor":
                page_args["page_size"] = size
                if cursor is not None:
                    page_args["cursor"] = cursor
            else:
                page_args["page"] = cursor
            res = self.query(tool, page_args, domain)
            coll.keys.append(res.key)
            if not res.ok:
                coll.errors.append({"tool": tool, "code": (res.error or {}).get("code"), "message": (res.error or {}).get("message"),
                                    "http_status": (res.error or {}).get("http_status"), "page": coll.pages_read + 1})
                coll.reason = f"página {coll.pages_read + 1} falhou: {(res.error or {}).get('code')}"
                return coll
            coll.pages_read += 1
            if res.call_id:
                coll.call_ids.append(res.call_id)
            data = res.data or {}
            if style == "cursor":
                items.extend(data.get(item_key, []))
                for k, v in data.items():
                    if k not in (item_key, "pagination"):
                        coll.extra.setdefault(k, v)
                nxt = (data.get("pagination") or {}).get("next_cursor")
                if "pagination" not in data and data.get("truncated"):
                    coll.reason = "fonte sem paginação devolveu resultado truncado"
                    return coll
            else:
                for k, v in (data.get("items") or {}).items():
                    coll.extra.setdefault(k, [])
                    coll.extra[k].extend(v)
                pag = data.get("pagination") or {}
                nxt = cursor + 1 if pag.get("page", cursor) < pag.get("total_pages", cursor) else None
            if len(items) > max_items:
                coll.reason = f"volume acima de max_items_per_query={max_items}"
                return coll
            if nxt is None:
                coll.complete = True
                return coll
            if coll.pages_read >= max_pages:
                coll.reason = f"limite de {max_pages} páginas atingido; há mais dados não lidos"
                return coll
            cursor = nxt
