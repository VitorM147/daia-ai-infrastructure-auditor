"""Structured contract for actionable human resolution guides."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InvestigationStep:
    number: int
    objective: str
    interface: str
    location: str
    command_or_query: str
    expected: str
    interpretation: str
    if_different: str
    read_only: bool = True


@dataclass(frozen=True)
class ResolutionOption:
    name: str
    action: str
    why: str
    prerequisites: tuple[str, ...]
    risks: tuple[str, ...]
    approval: str
    manual_command: str
    validation: str
    stop_condition: str
    rollback: str


@dataclass(frozen=True)
class FindingGuide:
    finding_id: str
    title: str
    priority: str
    status: str
    environment: str
    service: str
    resource: str
    team: str
    team_validation: str
    analysis_timestamp: str
    analysis_window: str
    fingerprint: str
    executive_summary: str
    business_impact: str
    evidence: tuple[str, ...]
    metrics_queries: tuple[str, ...]
    sanitized_logs: tuple[str, ...]
    traces: tuple[str, ...]
    events_changes: tuple[str, ...]
    history: tuple[str, ...]
    alerting: tuple[str, ...]
    links: tuple[str, ...]
    symptoms: tuple[str, ...]
    expected_behavior: str
    abnormal_behavior: str
    causes: tuple[str, ...]
    evidence_for: tuple[str, ...]
    evidence_against: tuple[str, ...]
    alternatives: tuple[str, ...]
    confidence: str
    unverified: tuple[str, ...]
    investigation_steps: tuple[InvestigationStep, ...]
    resolution_options: tuple[ResolutionOption, ...]
    post_validation: tuple[str, ...]
    prevention: tuple[str, ...]
    jira_status: str = "PROPOSTA — AGUARDANDO APROVAÇÃO"
    extra: dict[str, Any] = field(default_factory=dict)
