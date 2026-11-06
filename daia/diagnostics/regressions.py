"""Synthetic regression rules derived from prior DAIA failure modes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class RegressionFinding:
    case_id: str
    status: str
    classification: str
    reason: str
    evidence: tuple[str, ...]


def evaluate_synthetic_case(case_id: str, facts: Mapping[str, object]) -> RegressionFinding:
    """Apply conservative gates to the six known failure patterns."""
    if case_id == "DAIA-001":
        if facts.get("error_rate_source") != "traffic_metric" or not facts.get("outbound_correlation_id"):
            return RegressionFinding(case_id, "INCOMPLETA", "HIPÓTESE", "traffic source or correlation identifier missing", ("do not call sampled spans 100% traffic",))
        return RegressionFinding(case_id, "ATIVA", "CAUSA_PROVÁVEL", "outbound correlation is present but mapping still needs business validation", ("traffic metric", "real correlation id"))
    if case_id == "DAIA-006":
        if facts.get("aggregation") == "weighted" or not facts.get("raw_series"): 
            return RegressionFinding(case_id, "INCOMPLETA", "NÃO VERIFICADO", "weighted or missing raw series cannot support trend", ("raw series required",))
        return RegressionFinding(case_id, "ATIVA", "INFERIDO", "raw lag trend is observable; producer/consumer ownership remains open", ("raw series",))
    if case_id == "DAIA-007":
        if facts.get("max_replicas") == 1:
            return RegressionFinding(case_id, "ATIVA", "CONFIGURAÇÃO", "100% desired/max with maxReplicas=1 is not saturation", ("maxReplicas",))
        return RegressionFinding(case_id, "ATIVA", "HIPÓTESE", "capacity pressure requires load evidence", ("non-trivial maxReplicas",))
    if case_id == "DAIA-030":
        origin = facts.get("oom_origin")
        if origin not in {"fluentd", "datadog-init"}:
            return RegressionFinding(case_id, "INCOMPLETA", "NÃO VERIFICADO", "OOM origin not attributed by event identity", ("container event identity",))
        return RegressionFinding(case_id, "ATIVA", "INFERIDO", "event identity attributes origin; service cause is not confirmed", (str(origin),))
    if case_id == "DAIA-038":
        if not facts.get("baseline_available"):
            return RegressionFinding(case_id, "INCOMPLETA", "NÃO VERIFICADO", "absolute retransmission count without baseline cannot establish anomaly", ("baseline required",))
        return RegressionFinding(case_id, "ATIVA", "INFERIDO", "ratio can be compared with equivalent baseline", ("baseline",))
    if case_id == "DAIA-040":
        if facts.get("read_points", 0) < facts.get("total_points", 0):
            return RegressionFinding(case_id, "INCOMPLETA", "NÃO VERIFICADO", "partial job sample cannot support global closure", ("pagination incomplete",))
        return RegressionFinding(case_id, "ATIVA", "INFERIDO", "complete current-state inventory supports active-state assessment", ("complete inventory",))
    return RegressionFinding(case_id, "INCOMPLETA", "NÃO VERIFICADO", "unknown synthetic regression case", ())
