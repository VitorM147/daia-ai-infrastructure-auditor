"""Stable issue fingerprints for deduplication and idempotency."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Mapping


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")


def build_fingerprint(*, environment: str, application: str, service: str,
                      resource: str, problem_class: str, failure_identifier: str) -> str:
    """Build a stable fingerprint without volatile timestamps."""
    fields = {
        "environment": _normalize(environment), "application": _normalize(application),
        "service": _normalize(service), "resource": _normalize(resource),
        "problem_class": _normalize(problem_class), "failure_identifier": _normalize(failure_identifier),
    }
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return "daia-fp-v1-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
