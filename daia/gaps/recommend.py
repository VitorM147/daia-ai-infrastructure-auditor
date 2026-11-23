"""Monitor and dashboard recommendation engine. Proposals only; nothing is created.

Every monitor proposal is checked against existing monitors (duplication), the available metrics, and
passed through zero-cost governance. If cost is not CUSTO_ZERO_CONFIRMADO the proposal is BLOQUEADO_POR_CUSTO.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from daia.costgov.classifier import BLOCKED, CostProposal, classify, ContractValidation

REQUIRED_MONITOR_FIELDS = ("name", "justification", "service", "query", "threshold", "window", "severity", "metric",
                           "doc_source", "dependencies", "incremental_cost", "expected_benefit")
REQUIRED_DASHBOARD_FIELDS = ("objective", "audience", "widgets", "queries", "data_sources", "justification", "gap_solved",
                             "doc_source", "cost")


@dataclass(frozen=True)
class MonitorCandidate:
    name: str
    service: str
    metric: str
    query: str
    threshold: str
    window: str
    severity: str
    justification: str
    doc_source: str
    dependencies: tuple[str, ...] = ()
    expected_benefit: str = ""
    historical_samples: int = 0
    false_positive_note: str = ""


@dataclass(frozen=True)
class Proposal:
    kind: str                       # MONITOR | DASHBOARD
    status: str                     # PROPOSTA | DUPLICADA | METRICA_INEXISTENTE | EVIDENCIA_INSUFICIENTE | BLOQUEADO_POR_CUSTO
    data: dict[str, object]
    cost_status: str
    blocked: bool
    notes: tuple[str, ...]
    created: bool = False           # invariant: always False

    def as_dict(self) -> dict[str, object]:
        d = dict(self.__dict__); d["notes"] = list(self.notes); return d


def _norm(q: str) -> str:
    return re.sub(r"\s+", "", q or "").lower()


def _metric_of(query: str) -> str | None:
    m = re.search(r"[a-z_]+(?:\.[a-z_0-9]+)+", query or "")
    return m.group(0) if m else None


def propose_monitor(c: MonitorCandidate, existing: Sequence[Mapping[str, object]], available_metrics: Iterable[str] | None,
                    min_samples: int = 24, validation: ContractValidation | None = None) -> Proposal:
    notes: list[str] = []
    cost = classify(CostProposal(c.name, "monitor", creates_or_enables_datadog_resource=True, validation=validation))
    data = {"name": c.name, "justification": c.justification, "service": c.service, "query": c.query, "threshold": c.threshold,
            "window": c.window, "severity": c.severity, "metric": c.metric, "doc_source": c.doc_source,
            "dependencies": list(c.dependencies), "incremental_cost": cost.status, "expected_benefit": c.expected_benefit,
            "false_positive_assessment": c.false_positive_note or "NAO_AVALIADO"}
    optional = {"dependencies"}   # a monitor may legitimately depend on nothing
    missing = [f for f in REQUIRED_MONITOR_FIELDS if f not in optional and data.get(f) in (None, "", [])]
    if missing:
        return Proposal("MONITOR", "EVIDENCIA_INSUFICIENTE", data, cost.status, True, (f"missing: {missing}",))
    if not c.doc_source.startswith("https://docs.datadoghq.com/"):
        return Proposal("MONITOR", "EVIDENCIA_INSUFICIENTE", data, cost.status, True, ("doc_source must be an official Datadog page",))
    for m in existing:
        same_query = _norm(str(m.get("query", ""))) == _norm(c.query)
        same_scope = c.service and c.service in str(m.get("query", "")) and (_metric_of(str(m.get("query", ""))) == c.metric)
        if same_query or same_scope:
            return Proposal("MONITOR", "DUPLICADA", data, cost.status, False, (f"existing monitor {m.get('id')} already covers this metric for the service",))
    if available_metrics is not None and c.metric not in set(available_metrics):
        return Proposal("MONITOR", "METRICA_INEXISTENTE", data, cost.status, True, (f"metric {c.metric} was not found among the collected metrics",))
    if c.historical_samples < min_samples:
        notes.append(f"only {c.historical_samples} historical samples (< {min_samples}); threshold is provisional and false positives are likely")
    if cost.blocked:
        notes.append(f"{BLOCKED}: {'; '.join(cost.reasons)}")
        return Proposal("MONITOR", BLOCKED, data, cost.status, True, tuple(notes))
    notes.append("requires human approval; nothing was created")
    return Proposal("MONITOR", "PROPOSTA", data, cost.status, False, tuple(notes))


@dataclass(frozen=True)
class DashboardCandidate:
    objective: str
    audience: str
    widgets: tuple[str, ...]
    queries: tuple[str, ...]
    data_sources: tuple[str, ...]
    justification: str
    gap_solved: str
    doc_source: str


def propose_dashboard(c: DashboardCandidate, existing_titles: Iterable[str], validation: ContractValidation | None = None) -> Proposal:
    cost = classify(CostProposal(c.objective, "dashboard", creates_or_enables_datadog_resource=True, validation=validation))
    data = {"objective": c.objective, "audience": c.audience, "widgets": list(c.widgets), "queries": list(c.queries),
            "data_sources": list(c.data_sources), "justification": c.justification, "gap_solved": c.gap_solved,
            "doc_source": c.doc_source, "cost": cost.status}
    if any(not data[f] for f in REQUIRED_DASHBOARD_FIELDS):
        return Proposal("DASHBOARD", "EVIDENCIA_INSUFICIENTE", data, cost.status, True, ("incomplete proposal",))
    words = set(re.findall(r"[a-z0-9]+", c.objective.lower())) - {"de", "da", "do", "e", "the", "and", "-"}
    for t in existing_titles:
        tw = set(re.findall(r"[a-z0-9]+", t.lower()))
        if words and len(words & tw) / len(words) >= 0.7:
            return Proposal("DASHBOARD", "DUPLICADA", data, cost.status, False, (f"existing dashboard '{t}' already matches the objective; extend or reuse it",))
    if cost.blocked:
        return Proposal("DASHBOARD", BLOCKED, data, cost.status, True, (f"{BLOCKED}: {'; '.join(cost.reasons)}",))
    return Proposal("DASHBOARD", "PROPOSTA", data, cost.status, False, ("requires human approval; nothing was created",))
