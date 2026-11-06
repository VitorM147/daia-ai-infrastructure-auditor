import unittest
from datetime import datetime, timezone

from daia.context.adapters import ContextSourceUnavailable, NotConnectedAdapter
from daia.context.models import ContextEntity, ContextRelationship, Provenance
from daia.context.retrieval import ContextRetriever
from daia.context.store import ContextStore


def prov(evidence, status="VERIFICADO"):
    return Provenance("synthetic", "syn-1", evidence, datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc), "alta" if status == "VERIFICADO" else "não_verificado", "team-synthetic", "prod", status)


def entity(entity_id, level, name, org="org-synthetic", evidence="synthetic evidence"):
    return ContextEntity(entity_id, level, name, org, prov(evidence), {})


class ContextTests(unittest.TestCase):
    def complete_store(self):
        store = ContextStore()
        levels = ["EMPRESA", "UNIDADE_DE_NEGOCIO", "PROCESSO", "JORNADA", "APLICAÇÃO", "SERVIÇO", "INFRAESTRUTURA", "EQUIPE"]
        for level in levels:
            store.add_entity(entity(level.lower(), level, level.title()))
        for source, target, relation in zip(levels[:-1], levels[1:], ["contains"] * 7):
            store.add_relationship(ContextRelationship(f"r-{source}", "org-synthetic", source.lower(), target.lower(), relation, prov("synthetic relationship")))
        return store

    def test_complete_context_is_retrievable(self):
        result = ContextRetriever(self.complete_store()).for_service("org-synthetic", "serviço")
        self.assertEqual(result.status, "CONTEXTUALIZADO")
        self.assertEqual(len(result.gaps), 0)

    def test_missing_context_is_explicit(self):
        result = ContextRetriever(ContextStore()).for_service("org-synthetic", "unknown")
        self.assertIn("NÃO VERIFICADO", result.status)

    def test_cross_organization_relationship_is_rejected(self):
        store = ContextStore(); store.add_entity(entity("a", "SERVIÇO", "A", "org-a")); store.add_entity(entity("b", "EQUIPE", "B", "org-b"))
        with self.assertRaises(ValueError):
            store.add_relationship(ContextRelationship("r", "org-a", "a", "b", "owned_by", prov("invalid")))

    def test_contradictory_evidence_is_reported(self):
        store = ContextStore(); store.add_entity(entity("s1", "SERVIÇO", "Payments", evidence="source A")); store.add_entity(entity("s2", "SERVIÇO", "Payments", evidence="source B"))
        result = ContextRetriever(store).for_service("org-synthetic", "s1")
        self.assertTrue(result.contradictions)

    def test_unconnected_source_does_not_claim_context(self):
        with self.assertRaises(ContextSourceUnavailable):
            NotConnectedAdapter("Confluence").discover_entities("org", "service")

    def test_provenance_rejects_non_utc(self):
        with self.assertRaises(ValueError):
            ContextEntity("x", "SERVIÇO", "x", "org", Provenance("x", "x", "e", datetime(2026, 1, 1), None, "alta", None, None, "VERIFICADO")) .validate()


if __name__ == "__main__":
    unittest.main()
