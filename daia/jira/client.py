"""Jira client protocol and safe no-network implementation boundary."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .models import JiraIssueSearchResult


class JiraClientError(RuntimeError):
    pass


class JiraAuthError(JiraClientError):
    pass


class JiraTimeoutError(JiraClientError):
    pass


class JiraClient(Protocol):
    def list_projects(self) -> list[dict[str, Any]]: ...
    def get_issue_metadata(self, project: str) -> dict[str, Any]: ...
    def search_by_fingerprint(self, fingerprint: str) -> list[JiraIssueSearchResult]: ...
    def create_issue(self, project: str, payload: dict[str, Any]) -> JiraIssueSearchResult: ...
    def get_issue_by_fingerprint(self, fingerprint: str) -> list[JiraIssueSearchResult]: ...


@dataclass
class NotConfiguredJiraClient:
    """Explicit boundary used until an approved transport is configured."""
    reason: str = "Jira integration is not configured"

    def _fail(self):
        raise JiraClientError(self.reason)

    def list_projects(self): self._fail()
    def get_issue_metadata(self, project): self._fail()
    def search_by_fingerprint(self, fingerprint): self._fail()
    def create_issue(self, project, payload): self._fail()
    def get_issue_by_fingerprint(self, fingerprint): self._fail()
