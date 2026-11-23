"""V5.1 integrated analysis. Pure functions over already-collected, read-only data.

Plugs into AuditOrchestrator as an *enricher* (see ``orchestrator.enrichers``) so checkpoints, resume and
history are inherited. Every output is recommendation-only and carries cost and verification labels.
"""
from __future__ import annotations

from typing import Any, Mapping

from daia.docs_intel.catalog import Catalog
from daia.gaps.compliance import (INSUFICIENTE, NAO_CONFORME, OPORTUNIDADE, Observation, build as build_compliance)
from daia.gaps.coverage import ServiceInput, build_matrix, summarize as summarize_matrix
from daia.gaps.querylint import duplicate_groups, lint_query
from daia.logintel.indexes import exclusion_candidates, review_indexes
from daia.logintel.patterns import dedupe, pattern_stats
from daia.logintel.sensitive import mask


def _monitors(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = []
    for m in data.get("monitors") or []:
        out.append({"id": str(m.get("id", "")), "name": str(m.get("name", "")), "query": str(m.get("query", ""))})
    return out


def analyze(cp: Mapping[str, Any], data: Mapping[str, Any], *, catalog: Catalog | None = None,
            service_frameworks: Mapping[str, str] | None = None, indexes: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    cat = catalog or Catalog.load()
    monitors = _monitors(data)
    coverage = cp.get("coverage", {})
    monitors_complete = coverage.get("monitors", {}).get("status") == "CONCLUÍDO"

    lint = [i for m in monitors for i in lint_query(m["id"], m["query"], service_frameworks)]
    services = sorted({f.get("service") for f in cp.get("findings", []) if f.get("service")})
    matrix = build_matrix([ServiceInput(s, has_apm=True) for s in services], monitors, monitors_complete)

    logs = [dict(l) for l in (data.get("logs") or [])]
    masked_findings: dict[str, int] = {}
    for l in logs:
        r = mask(str(l.get("message") or ""))
        l["message"] = r.text
        for k, v in r.findings.items():
            masked_findings[k] = masked_findings.get(k, 0) + v
    stats = pattern_stats(logs)
    obs: dict[str, Observation] = {}
    if indexes is not None:
        ix = review_indexes(indexes, cat)
        no_quota = [f.index for f in ix if f.kind == "NO_DAILY_QUOTA"]
        if no_quota:
            obs["DAIA-DOC-LOG-002"] = Observation(OPORTUNIDADE, f"indices sem cota diaria: {', '.join(no_quota)}", "P2")
    else:
        ix = []
    legacy = [i for i in lint if i.code == "LEGACY_API_USAGE_METRIC"]
    if legacy:
        obs["DAIA-DOC-API-003"] = Observation(NAO_CONFORME, f"{len(legacy)} monitor(es) usam o namespace legado", "P3")
    compliance = build_compliance(cat, obs)

    return {
        "status": "OK",
        "mode": "RECOMMEND_ONLY",
        "writes_performed": 0,
        "monitor_lint": [i.__dict__ for i in lint],
        "monitor_duplicates": duplicate_groups(monitors),
        "coverage_summary": summarize_matrix(matrix),
        "coverage_rows": len(matrix),
        "log_dedup": dedupe(logs).__dict__,
        "log_top_patterns": [s.__dict__ for s in stats[:10]],
        "exclusion_candidates": [c.__dict__ for c in exclusion_candidates(stats)],
        "sensitive_data_in_logs": masked_findings,
        "index_findings": [f.__dict__ for f in ix],
        "compliance_states": {s: sum(1 for r in compliance if r.state == s) for s in {r.state for r in compliance}},
        "limitations": ([] if monitors_complete else ["inventario de monitores incompleto: ausencia de monitor nao e prova"]) +
                       ([] if indexes is not None else ["configuracao de indices nao fornecida: logs/indices nao avaliados"]),
    }


def make_enricher(**kwargs: Any):
    def daia_v51_integrated(cp: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
        return analyze(cp, data, **kwargs)
    return daia_v51_integrated
