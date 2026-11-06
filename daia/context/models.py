"""Provenance-aware enterprise knowledge graph contracts."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


LEVELS = ("EMPRESA", "UNIDADE_DE_NEGOCIO", "PROCESSO", "JORNADA", "APLICAÇÃO", "SERVIÇO", "INFRAESTRUTURA", "EQUIPE")
STATUSES = ("VERIFICADO", "PARCIAL", "NÃO_VERIFICADO", "CONTRADITÓRIO", "DESATUALIZADO")


@dataclass(frozen=True)
class Provenance:
    source_type: str
    source_id: str
    evidence: str
    collected_at_utc: datetime
    last_validated_at_utc: datetime | None
    confidence: str
    responsible: str | None
    environment: str | None
    verification_status: str

    def validate(self) -> None:
        if self.collected_at_utc.tzinfo != timezone.utc:
            raise ValueError("context provenance collection time must be UTC")
        if self.last_validated_at_utc and self.last_validated_at_utc.tzinfo != timezone.utc:
            raise ValueError("context validation time must be UTC")
        if not self.source_type or not self.source_id or not self.evidence:
            raise ValueError("source, source id and evidence are required")
        if self.verification_status not in STATUSES:
            raise ValueError("invalid context verification status")
        if self.confidence not in {"alta", "média", "baixa", "não_verificado"}:
            raise ValueError("invalid context confidence")


@dataclass(frozen=True)
class ContextEntity:
    entity_id: str
    level: str
    name: str
    organization_id: str
    provenance: Provenance
    attributes: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if self.level not in LEVELS:
            raise ValueError("invalid enterprise context level")
        if not self.entity_id or not self.name or not self.organization_id:
            raise ValueError("entity identity is required")
        self.provenance.validate()


@dataclass(frozen=True)
class ContextRelationship:
    relationship_id: str
    organization_id: str
    from_entity: str
    to_entity: str
    relation: str
    provenance: Provenance
    dependencies: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.relationship_id or not self.from_entity or not self.to_entity or not self.relation:
            raise ValueError("relationship identity is required")
        if self.from_entity == self.to_entity:
            raise ValueError("self relationship is not allowed")
        self.provenance.validate()
