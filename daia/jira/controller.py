"""Approval-gated Jira controller with preflight, deduplication and reconciliation."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from .client import JiraClient, JiraClientError, JiraTimeoutError
from .models import CreationApproval, JiraConfig, JiraIssueProposal, JiraIssueSearchResult


@dataclass(frozen=True)
class CreationResult:
    status: str
    fingerprint: str
    issue: JiraIssueSearchResult | None = None
    reason: str = ""


class JiraController:
    def __init__(self, config: JiraConfig, client: JiraClient):
        self.config = config
        self.client = client
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def _lock_for(self, fingerprint: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(fingerprint, threading.Lock())

    def propose(self, proposal: JiraIssueProposal) -> dict[str, Any]:
        proposal.validate()
        return {"status": "PROPOSTA", "fingerprint": proposal.fingerprint, "payload": proposal.payload()}

    def preflight(self, proposal: JiraIssueProposal, project: str) -> CreationResult:
        proposal.validate()
        if not self.config.configured:
            return CreationResult("NÃO_VERIFICADO", proposal.fingerprint, reason="Jira is not configured")
        if project not in self.config.authorized_projects:
            return CreationResult("BLOQUEADO", proposal.fingerprint, reason="project is not authorized")
        try:
            matches = self.client.search_by_fingerprint(proposal.fingerprint)
        except JiraClientError as exc:
            return CreationResult("NÃO_VERIFICADO", proposal.fingerprint, reason=str(exc))
        if matches:
            return CreationResult("DUPLICATA", proposal.fingerprint, matches[0], "existing issue matches fingerprint")
        return CreationResult("APROVÁVEL", proposal.fingerprint, reason="no duplicate found; approval still required")

    def create(self, proposal: JiraIssueProposal, project: str, approval: CreationApproval) -> CreationResult:
        proposal.validate()
        if self.config.mode == "NIVEL_1":
            return CreationResult("PROPOSTA", proposal.fingerprint, reason="level 1 does not create")
        if self.config.mode == "NIVEL_3":
            return CreationResult("BLOQUEADO", proposal.fingerprint, reason="level 3 requires separate corporate authorization")
        if not approval.approved:
            return CreationResult("BLOQUEADO", proposal.fingerprint, reason="approval denied")
        if approval.fingerprint != proposal.fingerprint or approval.project != project:
            return CreationResult("BLOQUEADO", proposal.fingerprint, reason="approval scope does not match proposal")
        if project not in self.config.authorized_projects:
            return CreationResult("BLOQUEADO", proposal.fingerprint, reason="project is not authorized")
        lock = self._lock_for(proposal.fingerprint)
        if not lock.acquire(blocking=False):
            return CreationResult("CONCORRÊNCIA", proposal.fingerprint, reason="creation already in progress")
        try:
            try:
                matches = self.client.search_by_fingerprint(proposal.fingerprint)
                if matches:
                    return CreationResult("DUPLICATA", proposal.fingerprint, matches[0], "revalidated before create")
                issue = self.client.create_issue(project, proposal.payload())
                return CreationResult("CRIADA", proposal.fingerprint, issue, "creation response received")
            except JiraTimeoutError:
                # Mandatory reconciliation: never blindly retry after timeout.
                matches = self.client.get_issue_by_fingerprint(proposal.fingerprint)
                if len(matches) == 1:
                    return CreationResult("CRIADA_RECONCILIADA", proposal.fingerprint, matches[0], "timeout reconciled")
                if len(matches) == 0:
                    return CreationResult("INDETERMINADA", proposal.fingerprint, reason="timeout and no matching issue; human must decide")
                return CreationResult("DUPLICATA", proposal.fingerprint, matches[0], "multiple matches after timeout")
            except JiraClientError as exc:
                return CreationResult("NÃO_VERIFICADO", proposal.fingerprint, reason=str(exc))
        finally:
            lock.release()
