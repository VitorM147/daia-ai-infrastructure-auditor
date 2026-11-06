"""Read-only source adapter contracts. No network implementation is assumed."""
from __future__ import annotations

from typing import Any, Protocol


class ContextSourceUnavailable(RuntimeError):
    pass


class ReadOnlyContextAdapter(Protocol):
    source_type: str

    def discover_entities(self, organization_id: str, query: str) -> list[dict[str, Any]]: ...
    def discover_relationships(self, organization_id: str, entity_id: str) -> list[dict[str, Any]]: ...
    def search_evidence(self, organization_id: str, query: str) -> list[dict[str, Any]]: ...


class NotConnectedAdapter:
    def __init__(self, source_type: str):
        self.source_type = source_type

    def _unavailable(self):
        raise ContextSourceUnavailable(f"{self.source_type} is not connected; context is not verified")

    def discover_entities(self, organization_id, query): self._unavailable()
    def discover_relationships(self, organization_id, entity_id): self._unavailable()
    def search_evidence(self, organization_id, query): self._unavailable()
