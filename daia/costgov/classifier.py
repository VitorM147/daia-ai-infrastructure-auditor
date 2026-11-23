"""Zero-cost governance. The incremental budget is R$ 0.

Only CUSTO_ZERO_CONFIRMADO makes a proposal *eligible* for a future, human-approved implementation.
Public pricing never substitutes the corporate contract: anything that creates or enables a Datadog
resource is blocked unless a human contract validation is attached. Nothing is ever applied here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Iterable, Mapping

ZERO, POTENTIAL, UNKNOWN, PAID = "CUSTO_ZERO_CONFIRMADO", "CUSTO_POTENCIAL", "CUSTO_DESCONHECIDO", "RECURSO_PAGO"
BLOCKED = "BLOQUEADO_POR_CUSTO"

# Products the official documentation describes as separately billable (see docs_intel rules).
PAID_PRODUCTS = frozenset({"sensitive_data_scanner", "audit_trail", "flex_logs", "synthetics", "rum", "cloud_siem",
                           "cloud_cost_management", "database_monitoring", "network_monitoring", "ai_features",
                           "bits_ai", "apm", "profiler", "byoc_logs"})
# Kinds that can add consumption even when the product itself is included.
CONSUMPTION_KINDS = frozenset({"custom_metric", "log_based_metric", "monitor", "dashboard", "slo", "index",
                               "exclusion_filter", "pipeline", "synthetic_test", "notebook"})
# Kinds that touch nothing in Datadog.
LOCAL_KINDS = frozenset({"offline_analysis", "report", "documentation"})


@dataclass(frozen=True)
class ContractValidation:
    """Evidence that a human checked the corporate contract. Without all fields it does not count."""
    approver: str
    validated_on: str
    evidence_ref: str
    scope: str

    def is_valid(self) -> bool:
        try:
            date.fromisoformat(self.validated_on)
        except ValueError:
            return False
        return all(x and x.strip() for x in (self.approver, self.evidence_ref, self.scope))


@dataclass(frozen=True)
class CostProposal:
    name: str
    kind: str
    creates_or_enables_datadog_resource: bool = False
    new_datadog_queries: int = 0
    products_required: tuple[str, ...] = ()
    reuses_existing_metrics_only: bool = False
    validation: ContractValidation | None = None


@dataclass(frozen=True)
class CostDecision:
    proposal: str
    status: str
    blocked: bool
    eligible_for_future_implementation: bool
    requires_human_approval: bool
    reasons: tuple[str, ...]
    label: str = ""

    def as_dict(self) -> dict[str, object]:
        d = dict(self.__dict__)
        d["reasons"] = list(self.reasons)
        return d


def classify(p: CostProposal) -> CostDecision:
    reasons: list[str] = []
    paid = sorted(set(p.products_required) & PAID_PRODUCTS)
    valid_contract = bool(p.validation and p.validation.is_valid())
    if p.validation and not valid_contract:
        reasons.append("contract validation attached but incomplete; ignored")

    if paid:
        reasons.append(f"requires separately billable product(s): {', '.join(paid)}")
        return CostDecision(p.name, PAID, True, False, True, tuple(reasons), BLOCKED)

    if p.kind in LOCAL_KINDS and not p.creates_or_enables_datadog_resource and p.new_datadog_queries == 0:
        reasons.append("offline analysis of already collected data; no Datadog resource and no new query")
        return CostDecision(p.name, ZERO, False, True, True, tuple(reasons))

    if p.creates_or_enables_datadog_resource or p.kind in CONSUMPTION_KINDS:
        if p.kind in {"custom_metric", "log_based_metric"}:
            reasons.append("custom/log-based metrics can create custom-metric consumption; never created automatically")
            status = POTENTIAL if not valid_contract else POTENTIAL
            return CostDecision(p.name, status, True, False, True, tuple(reasons), BLOCKED)
        if valid_contract:
            reasons.append(f"human contract validation by {p.validation.approver} on {p.validation.validated_on} ({p.validation.scope})")
            return CostDecision(p.name, ZERO, False, True, True, tuple(reasons))
        reasons.append("creates or changes a Datadog resource and the corporate contract was not validated")
        return CostDecision(p.name, UNKNOWN, True, False, True, tuple(reasons), BLOCKED)

    if p.new_datadog_queries > 0 and not p.reuses_existing_metrics_only:
        reasons.append(f"{p.new_datadog_queries} new Datadog queries; consumption of API budget not validated")
        return CostDecision(p.name, POTENTIAL, True, False, True, tuple(reasons), BLOCKED)

    if p.reuses_existing_metrics_only and not (p.creates_or_enables_datadog_resource):
        reasons.append("read-only reuse of already available metrics; no new resource")
        return CostDecision(p.name, ZERO if valid_contract else POTENTIAL, not valid_contract, valid_contract, True, tuple(reasons),
                            "" if valid_contract else BLOCKED)

    reasons.append("insufficient information to classify")
    return CostDecision(p.name, UNKNOWN, True, False, True, tuple(reasons), BLOCKED)


def summarize(decisions: Iterable[CostDecision]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in decisions:
        out[d.status] = out.get(d.status, 0) + 1
    return out
