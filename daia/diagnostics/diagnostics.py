"""Conservative diagnostic conclusions: evidence is not cause."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import EvidencePackage


@dataclass(frozen=True)
class DiagnosticAssessment:
    status: str
    classification: str
    confidence: str
    evidence_for: tuple[str, ...]
    evidence_against: tuple[str, ...]
    alternatives: tuple[str, ...]
    reason: str


def assess_diagnostic(*, packages: Iterable[EvidencePackage], claim: str,
                      evidence_for: Iterable[str], evidence_against: Iterable[str],
                      alternatives: Iterable[str], coverage_sufficient: bool,
                      causal_identifiers_match: bool = False,
                      current_state_confirmed: bool = False) -> DiagnosticAssessment:
    """Never returns confirmed cause without coverage and real correlation IDs."""
    packs = list(packages)
    for package in packs:
        package.validate()
    supporting = tuple(evidence_for)
    opposing = tuple(evidence_against)
    other = tuple(alternatives)
    if not coverage_sufficient:
        return DiagnosticAssessment("INCOMPLETA", "NÃO VERIFICADO", "baixa", supporting, opposing, other,
                                    f"{claim}: cobertura insuficiente; não extrapolar amostra")
    if not causal_identifiers_match:
        return DiagnosticAssessment("INCOMPLETA", "HIPÓTESE", "média-baixa", supporting, opposing, other,
                                    f"{claim}: identificadores de correlação causal ausentes")
    if not opposing or not other:
        return DiagnosticAssessment("INCOMPLETA", "HIPÓTESE", "média-baixa", supporting, opposing, other,
                                    f"{claim}: evidências contrárias e alternativas obrigatórias ausentes")
    if not current_state_confirmed:
        return DiagnosticAssessment("INCOMPLETA", "INFERIDO", "média", supporting, opposing, other,
                                    f"{claim}: estado atual não confirmado")
    return DiagnosticAssessment("ATIVA", "CAUSA_PROVÁVEL", "média", supporting, opposing, other,
                                f"{claim}: correlação e cobertura suficientes; causa ainda não confirmada")
