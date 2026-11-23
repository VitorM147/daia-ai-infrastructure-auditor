"""Documentation compliance matrix: official recommendation vs observed environment."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from daia.docs_intel.catalog import Catalog

CONFORME, NAO_CONFORME, OPORTUNIDADE = "CONFORMIDADE_DEMONSTRADA", "NAO_CONFORMIDADE_DEMONSTRADA", "OPORTUNIDADE_DE_MELHORIA"
INSUFICIENTE, NAO_APLICAVEL = "INFORMACAO_INSUFICIENTE", "REGRA_NAO_APLICAVEL"
ALL_STATES = frozenset({CONFORME, NAO_CONFORME, OPORTUNIDADE, INSUFICIENTE, NAO_APLICAVEL})


@dataclass(frozen=True)
class Observation:
    state: str
    evidence: str
    priority: str = "P3"


@dataclass(frozen=True)
class ComplianceRow:
    area: str
    rule_id: str
    practice: str
    state: str
    evidence: str
    priority: str
    cost: str
    source: str

    def md(self) -> str:
        return f"| {self.area} | {self.practice} | {self.state} | {self.evidence} | {self.priority} | {self.cost} | {self.source} |"


def build(catalog: Catalog, observations: Mapping[str, Observation]) -> list[ComplianceRow]:
    """Rules with no observation are INFORMACAO_INSUFICIENTE: never inferred as compliant or non-compliant."""
    rows = []
    for rule in catalog.rules.values():
        obs = observations.get(rule.rule_id)
        if obs is None:
            state, ev, prio = INSUFICIENTE, "no observation collected for this rule", "P3"
        else:
            if obs.state not in ALL_STATES:
                raise ValueError(f"invalid state {obs.state}")
            state, ev, prio = obs.state, obs.evidence, obs.priority
            if state in (CONFORME, NAO_CONFORME) and not ev.strip():
                raise ValueError(f"{rule.rule_id}: a demonstrated state requires evidence")
        rows.append(ComplianceRow(rule.domain, rule.rule_id, rule.title, state, ev, prio, rule.cost_status, rule.source.url))
    return rows


def to_markdown(rows: list[ComplianceRow]) -> str:
    head = "| Area | Boa pratica oficial | Situacao | Evidencia | Prioridade | Custo | Fonte |\n|---|---|---|---|---|---|---|\n"
    return head + "\n".join(r.md() for r in rows)
