"""Context retrieval that distinguishes documented context from gaps."""
from __future__ import annotations

from dataclasses import dataclass
from .models import ContextEntity, ContextRelationship
from .store import ContextStore


@dataclass(frozen=True)
class ContextResult:
    status: str
    entities: tuple[ContextEntity, ...]
    relationships: tuple[ContextRelationship, ...]
    gaps: tuple[str, ...]
    contradictions: tuple[str, ...]


class ContextRetriever:
    def __init__(self, store: ContextStore):
        self.store = store

    def for_service(self, organization_id: str, service_id: str) -> ContextResult:
        service_key = (organization_id, service_id)
        service = self.store.entities.get(service_key)
        if service is None:
            return ContextResult("NÃO VERIFICADO — CONTEXTO EMPRESARIAL INSUFICIENTE", (), (), ("serviço não encontrado",), ())
        relationships = []
        entity_ids = {service_id}
        frontier = [service_id]
        while frontier:
            current = frontier.pop()
            for relation in self.store.relationships_for(organization_id, current):
                if relation not in relationships:
                    relationships.append(relation)
                for candidate in (relation.from_entity, relation.to_entity):
                    if candidate not in entity_ids:
                        entity_ids.add(candidate)
                        frontier.append(candidate)
        relationships = tuple(relationships)
        entities = tuple(self.store.entities[(organization_id, entity_id)] for entity_id in entity_ids if (organization_id, entity_id) in self.store.entities)
        missing_levels = set(("EMPRESA", "UNIDADE_DE_NEGOCIO", "PROCESSO", "JORNADA", "APLICAÇÃO", "SERVIÇO", "INFRAESTRUTURA", "EQUIPE")) - {entity.level for entity in entities}
        contradictions = tuple(f"{a.entity_id} vs {b.entity_id}: evidências divergentes" for a, b in self.store.contradictions(organization_id) if a.entity_id in entity_ids or b.entity_id in entity_ids)
        gaps = tuple(f"nível ausente: {level}" for level in sorted(missing_levels))
        status = "CONTEXTUALIZADO" if not gaps and not contradictions else "PARCIAL — CONTEXTO EMPRESARIAL INSUFICIENTE"
        return ContextResult(status, entities, relationships, gaps, contradictions)
