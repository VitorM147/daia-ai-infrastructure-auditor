"""Isolated in-memory context store; persistence can be added behind this boundary."""
from __future__ import annotations

from dataclasses import dataclass
from .models import ContextEntity, ContextRelationship


@dataclass
class ContextStore:
    entities: dict[tuple[str, str], ContextEntity]
    relationships: dict[tuple[str, str], ContextRelationship]

    def __init__(self):
        self.entities = {}
        self.relationships = {}

    def add_entity(self, entity: ContextEntity) -> None:
        entity.validate()
        self.entities[(entity.organization_id, entity.entity_id)] = entity

    def add_relationship(self, relationship: ContextRelationship) -> None:
        relationship.validate()
        key = (relationship.organization_id, relationship.relationship_id)
        if (relationship.organization_id, relationship.from_entity) not in self.entities or (relationship.organization_id, relationship.to_entity) not in self.entities:
            raise ValueError("relationship references unknown entity in this organization")
        self.relationships[key] = relationship

    def entities_for(self, organization_id: str, *, level: str | None = None) -> list[ContextEntity]:
        values = [e for (org, _), e in self.entities.items() if org == organization_id]
        return [e for e in values if level is None or e.level == level]

    def relationships_for(self, organization_id: str, entity_id: str) -> list[ContextRelationship]:
        return [r for (org, _), r in self.relationships.items() if org == organization_id and (r.from_entity == entity_id or r.to_entity == entity_id)]

    def contradictions(self, organization_id: str) -> list[tuple[ContextEntity, ContextEntity]]:
        result = []
        values = self.entities_for(organization_id)
        for index, left in enumerate(values):
            for right in values[index + 1:]:
                if left.level == right.level and left.name.lower() == right.name.lower() and left.provenance.evidence != right.provenance.evidence:
                    result.append((left, right))
        return result
