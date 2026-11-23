"""Cached, URL-validated index of the official llms.txt tree.

Only index files are read (never a crawl). Every entry records whether the URL was
verified to exist, so a 404 such as /logs/llms.txt is a recorded fact, not a guess.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .catalog import OFFICIAL_HOSTS
from .freshness import FetchResult, QueryBudget

CACHE_PATH = Path(__file__).with_name("index_cache.json")
ENTRY_RX = re.compile(r"\[([^\]]+)\]\((https://docs\.datadoghq\.com/[a-z0-9_\-]+/llms\.txt)\)")


def parse_root_index(body: str) -> dict[str, str]:
    """Return {section_title: llms_url} from the root llms.txt."""
    out: dict[str, str] = {}
    for title, url in ENTRY_RX.findall(body):
        out[title.strip()] = url
    return out


def validate_index_urls(urls: dict[str, str], fetch: Callable[[str], FetchResult], budget: QueryBudget) -> dict[str, dict[str, object]]:
    """Check each index URL within budget. Unchecked entries stay explicit (exists=None)."""
    result: dict[str, dict[str, object]] = {}
    for title, url in urls.items():
        if urlparse(url).hostname not in OFFICIAL_HOSTS:
            result[title] = {"url": url, "exists": None, "note": "host not allowed"}
            continue
        if not budget.take():
            result[title] = {"url": url, "exists": None, "note": "not checked: budget exhausted"}
            continue
        try:
            res = fetch(url)
        except Exception as exc:
            result[title] = {"url": url, "exists": None, "note": f"fetch failed: {type(exc).__name__}"}
            continue
        if res.status == 429:
            result[title] = {"url": url, "exists": None, "note": "HTTP 429; stopped"}
            break
        result[title] = {"url": url, "exists": res.status == 200, "status": res.status}
    return result


def save_cache(entries: dict[str, dict[str, object]], verified_at: str, path: Path = CACHE_PATH) -> None:
    path.write_text(json.dumps({"verified_at": verified_at, "entries": entries}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def load_cache(path: Path = CACHE_PATH) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {"verified_at": None, "entries": {}}
