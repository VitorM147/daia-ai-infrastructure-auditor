"""Audit output contract (audit-output-v1) that every agent adapter must return.

The scorer validates and normalises the output; malformed output is itself a
measurable failure, never silently accepted.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Mapping

from .taxonomy import (AUDIT_STATUSES, CAUSE_STATUSES, CLASSIFICATIONS, DOMAIN_STATES,
                       IMPACTS, OUTPUT_SCHEMA_VERSION, PROBLEM_CLASSES, SEVERITIES)

OUTPUT_EXAMPLE: dict[str, Any] = {
    "schema_version": OUTPUT_SCHEMA_VERSION,
    "status": "CONCLUÍDA | INCOMPLETA",
    "domains": {"metrics": "VERIFICADO | NÃO VERIFICADO"},
    "findings": [{
        "problem_class": "|".join(PROBLEM_CLASSES),
        "resource": "service name | deployment/container | host:device | monitor:<id> | consumer group | database",
        "service": "string|null", "environment": "prod",
        "severity": "P0|P1|P2|P3",
        "classification": "OBSERVADO|INFERIDO|HIPÓTESE|NÃO VERIFICADO",
        "silent": False,
        "impact": "observado|potencial|indeterminado",
        "summary": "texto curto",
        "cause": {"code": "string|null", "description": "texto", "status": "confirmada|provável|hipótese|indeterminada",
                  "alternatives": ["hipótese alternativa"], "evidence_against": ["evidência contrária"]},
        "evidence": [{"call_id": "c0003", "value": 123.0, "note": "o que o valor representa"}],
        "computed": [{"name": "error_rate_current", "value": 0.08, "op": "ratio",
                      "inputs": [{"call_id": "c0003", "series_index": 0, "slice": [-3, None]},
                                 {"call_id": "c0002", "series_index": 0, "slice": [-3, None]}]}],
        "links": [{"url": "somente URL retornada por ferramenta", "validated": False}],
        "manual_navigation": "caminho manual quando não há link",
        "procedure": {"diagnostic_steps": [{"text": "...", "read_only": True}],
                      "resolution_steps": [{"text": "...", "human_execution_label": True, "risks": ["..."],
                                            "rollback": "...", "validation": "..."}],
                      "alternatives": ["..."]},
        "fingerprint": "string|null",
    }],
    "tool_errors_reported": [{"tool": "search_datadog_logs", "error_code": "SOURCE_UNAVAILABLE", "shown_to_human": True}],
    "security_notices": [{"type": "prompt_injection", "call_id": "c0007", "description": "redigido"}],
    "jira": [{"action": "proposed|linked_existing|created|reconciled|indeterminate", "fingerprint": "...", "issue_key": "..."}],
    "limitations": ["texto"],
    "narrative": "resumo para humano (sem dados sensíveis)",
}

URL_RX = re.compile(r"https?://[^\s\"'<>)\]]+")


def _norm_resource(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^(service|host|kube_deployment):", "", text)
    return re.sub(r"\s+", "", text)


def normalize(output: Mapping[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """Return (normalised output, schema errors). Never raises on bad input."""
    errors: list[str] = []
    if not isinstance(output, Mapping):
        return _empty(), ["output is not an object"]
    out = copy.deepcopy(dict(output))
    if out.get("schema_version") != OUTPUT_SCHEMA_VERSION:
        errors.append("schema_version missing or unsupported")
    status = out.get("status")
    if status not in AUDIT_STATUSES:
        errors.append(f"invalid status {status!r}")
    domains = out.get("domains") if isinstance(out.get("domains"), Mapping) else {}
    for name, state in list(domains.items()):
        if state not in DOMAIN_STATES:
            errors.append(f"domain {name} has invalid state {state!r}")
    findings = []
    for i, f in enumerate(out.get("findings") or []):
        if not isinstance(f, Mapping):
            errors.append(f"finding {i} is not an object")
            continue
        f = dict(f)
        if f.get("problem_class") not in PROBLEM_CLASSES:
            errors.append(f"finding {i}: unknown problem_class {f.get('problem_class')!r}")
        if f.get("severity") not in SEVERITIES:
            errors.append(f"finding {i}: invalid severity {f.get('severity')!r}")
        if f.get("classification") not in CLASSIFICATIONS:
            errors.append(f"finding {i}: invalid classification")
        if f.get("impact") not in IMPACTS:
            errors.append(f"finding {i}: invalid impact")
        cause = f.get("cause") if isinstance(f.get("cause"), Mapping) else {}
        if cause.get("status") not in CAUSE_STATUSES:
            errors.append(f"finding {i}: invalid cause.status")
        f["cause"] = {"code": cause.get("code"), "description": cause.get("description") or "",
                      "status": cause.get("status"), "alternatives": list(cause.get("alternatives") or []),
                      "evidence_against": list(cause.get("evidence_against") or [])}
        f["_key"] = (str(f.get("problem_class")), _norm_resource(f.get("resource")))
        f.setdefault("evidence", [])
        f.setdefault("computed", [])
        f.setdefault("links", [])
        f.setdefault("procedure", {})
        findings.append(f)
    norm = {
        "schema_version": out.get("schema_version"),
        "status": status,
        "domains": dict(domains),
        "findings": findings,
        "tool_errors_reported": list(out.get("tool_errors_reported") or []),
        "security_notices": list(out.get("security_notices") or []),
        "jira": list(out.get("jira") or []),
        "limitations": list(out.get("limitations") or []),
        "narrative": str(out.get("narrative") or ""),
        "agent": dict(out.get("agent") or {}),
    }
    return norm, errors


def _empty() -> dict[str, Any]:
    return {"schema_version": None, "status": None, "domains": {}, "findings": [], "tool_errors_reported": [],
            "security_notices": [], "jira": [], "limitations": [], "narrative": "", "agent": {}}


def norm_resource(value: Any) -> str:
    return _norm_resource(value)
