"""Jira integration contracts without credentials or vendor assumptions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class JiraConfig:
    base_url: str | None = None
    mode: str = "NIVEL_2"
    authorized_projects: tuple[str, ...] = ()
    timeout_seconds: int = 30
    identity: str = "jira-create-approved"
    configured: bool = False


@dataclass(frozen=True)
class JiraIssueProposal:
    title: str
    problem: str
    business_context: str
    priority: str
    evidence: tuple[str, ...]
    cause_or_hypotheses: tuple[str, ...]
    observed_impact: str
    potential_impact: str
    human_diagnosis: tuple[str, ...]
    resolution_options: tuple[str, ...]
    risks_and_rollback: tuple[str, ...]
    datadog_links: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    responsible_team: str
    fingerprint: str
    audit_id: str
    environment: str
    service: str
    resource: str

    def validate(self) -> None:
        required = {
            "title": self.title, "problem": self.problem, "priority": self.priority,
            "evidence": self.evidence, "cause_or_hypotheses": self.cause_or_hypotheses,
            "human_diagnosis": self.human_diagnosis, "resolution_options": self.resolution_options,
            "risks_and_rollback": self.risks_and_rollback, "acceptance_criteria": self.acceptance_criteria,
            "responsible_team": self.responsible_team, "fingerprint": self.fingerprint,
            "audit_id": self.audit_id, "environment": self.environment,
            "service": self.service, "resource": self.resource,
        }
        missing = [key for key, value in required.items() if not value]
        if missing:
            raise ValueError(f"required proposal fields missing: {missing}")
        if "<" in self.title or "TODO" in self.title.upper():
            raise ValueError("proposal contains unresolved placeholder")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "summary": self.title,
            "description": {
                "problem": self.problem,
                "business_context": self.business_context,
                "priority": self.priority,
                "evidence": list(self.evidence),
                "cause_or_hypotheses": list(self.cause_or_hypotheses),
                "impact": {"observed": self.observed_impact, "potential": self.potential_impact},
                "human_diagnosis": list(self.human_diagnosis),
                "resolution_options": list(self.resolution_options),
                "risks_and_rollback": list(self.risks_and_rollback),
                "datadog_links": list(self.datadog_links),
                "acceptance_criteria": list(self.acceptance_criteria),
                "responsible_team": self.responsible_team,
                "fingerprint": self.fingerprint,
                "audit_id": self.audit_id,
                "environment": self.environment,
                "service": self.service,
                "resource": self.resource,
            },
            "labels": ["daia", self.fingerprint],
        }


@dataclass(frozen=True)
class CreationApproval:
    approval_id: str
    approved: bool
    fingerprint: str
    project: str
    approver: str
    scope: str


@dataclass(frozen=True)
class JiraIssueSearchResult:
    issue_id: str
    issue_key: str
    url: str
    fingerprint: str
    status: str


JiraSearchResult = JiraIssueSearchResult
