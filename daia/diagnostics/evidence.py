"""Evidence provenance helpers and deterministic fingerprints."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Mapping


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def query_hash(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def evidence_fingerprint(*, metric_id: str, resource_id: str, start_utc: datetime, end_utc: datetime, source_id: str) -> str:
    raw = canonical_json({"metric_id": metric_id, "resource_id": resource_id,
                          "start": start_utc.astimezone(timezone.utc).isoformat(),
                          "end": end_utc.astimezone(timezone.utc).isoformat(), "source_id": source_id})
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def safe_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Allow only scalar metadata; payloads and secrets never enter evidence records."""
    result: dict[str, Any] = {}
    for key, value in metadata.items():
        if key.lower() in {"payload", "body", "token", "password", "secret", "api_key"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[str(key)] = value
    return result
