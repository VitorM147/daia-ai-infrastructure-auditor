"""On-demand documentation verification. Network happens ONLY here, only when a human runs it.

  python -m daia.docs_intel.cli status                      # offline: age of every rule
  python -m daia.docs_intel.cli verify --budget 5 [--write]  # fetch each distinct source page once
  python -m daia.docs_intel.cli index  --budget 20 [--write] # validate the required llms.txt index URLs

Only docs.datadoghq.com is contacted. Page bodies are hashed and discarded. 429 stops the run.
--write updates the local catalog/cache only; it never touches Datadog or any other repository.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import date

from .catalog import OFFICIAL_HOSTS, Catalog
from .freshness import FetchResult, QueryBudget, offline_status, verify_online
from .index_cache import save_cache, validate_index_urls

UA = "daia-docs-intel/5.1 (read-only documentation check)"
REQUIRED_INDEXES = {
    "Log Management": "https://docs.datadoghq.com/log_management/llms.txt",
    "API Reference": "https://docs.datadoghq.com/api/llms.txt",
    "APM": "https://docs.datadoghq.com/apm/llms.txt",
    "Infrastructure": "https://docs.datadoghq.com/infrastructure/llms.txt",
    "Containers": "https://docs.datadoghq.com/containers/llms.txt",
    "Dashboards": "https://docs.datadoghq.com/dashboards/llms.txt",
    "Monitors": "https://docs.datadoghq.com/monitors/llms.txt",
    "Database Monitoring": "https://docs.datadoghq.com/database_monitoring/llms.txt",
    "Datadog MCP Server": "https://docs.datadoghq.com/datadog_mcp_server/llms.txt",
    "Cloud Cost Management": "https://docs.datadoghq.com/cloud_cost_management/llms.txt",
    "Integrations": "https://docs.datadoghq.com/integrations/llms.txt",
    "Datadog Watchdog": "https://docs.datadoghq.com/datadog_watchdog/llms.txt",
    "Service Level Objectives": "https://docs.datadoghq.com/service_level_objectives/llms.txt",
    "Event Management": "https://docs.datadoghq.com/event_management/llms.txt",
    # Paths named in the V5.1 brief that are NOT in the official root index; recorded as facts when they 404.
    "(brief) /logs/llms.txt": "https://docs.datadoghq.com/logs/llms.txt",
    "(brief) /service_management/llms.txt": "https://docs.datadoghq.com/service_management/llms.txt",
}


class _NoCrossHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlparse
        if urlparse(newurl).hostname not in OFFICIAL_HOSTS:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_fetch(url: str) -> FetchResult:
    opener = urllib.request.build_opener(_NoCrossHostRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/plain,text/html,text/markdown"})
    time.sleep(0.5)   # conservative pacing
    try:
        with opener.open(req, timeout=25) as r:
            body = r.read(5_000_000).decode("utf-8", errors="replace")
            return FetchResult(r.status, body, dict(r.headers))
    except urllib.error.HTTPError as e:
        return FetchResult(e.code, "", dict(e.headers or {}))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="daia-docs")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    for name in ("verify", "index"):
        s = sub.add_parser(name)
        s.add_argument("--budget", type=int, required=True, help="maximum number of HTTP requests")
        s.add_argument("--write", action="store_true", help="persist hashes/cache locally")
    a = p.parse_args(argv)
    today = date.today()
    cat = Catalog.load()
    if a.cmd == "status":
        print(json.dumps([offline_status(r, today).__dict__ for r in cat.rules.values()], indent=1))
        return 0
    if a.cmd == "verify":
        verdicts = verify_online(cat, http_fetch, QueryBudget(a.budget), today)
        for v in verdicts:
            print(f"{v.status:20} {v.rule_id}  {v.detail}")
        if a.write:
            digest = {v.rule_id: v.new_sha256 for v in verdicts if v.new_sha256}
            # Only record a hash/date for rules whose page was actually reached (FRESH/CHANGED). CHANGED keeps the
            # OLD hash so it stays flagged until a human reviews the rule and re-baselines it.
            reached = {v.rule_id: v for v in verdicts if v.status == "FRESH" and v.new_sha256}
            for rid, v in reached.items():
                src = cat.rules[rid].source
                object.__setattr__(src, "page_sha256", v.new_sha256)
                object.__setattr__(src, "verified_at", today.isoformat())
            cat.save()
        return 0 if all(v.status in ("FRESH", "CHANGED") for v in verdicts) else 2
    res = validate_index_urls(REQUIRED_INDEXES, http_fetch, QueryBudget(a.budget))
    for t, r in res.items():
        print(f"{str(r.get('status', r.get('note'))):>6}  exists={r['exists']}  {t}")
    if a.write:
        save_cache(res, today.isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
