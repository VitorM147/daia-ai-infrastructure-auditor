"""Eval adapter: runs the V4-08 audit orchestrator as the agent under test."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Mapping

from daia.orchestration import AuditOrchestrator, AuditRequest, AuditStore, FindingRegistry, to_audit_output
from daia.orchestration.orchestrator import ORCHESTRATOR_VERSION

from .base import ToolPort


class OrchestratorAgent:
    name = "daia-orchestrator"
    version = ORCHESTRATOR_VERSION

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "model": None, "kind": "deterministic-orchestrator",
                "config": {"limits": "daia/config/orchestration-limits.json", "rate_limit_sleep": "desativado no sandbox"}}

    def run(self, context: Mapping[str, Any], call_tool: ToolPort) -> dict[str, Any]:
        now = datetime.strptime(context["now_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        text = context["input_text"]
        approval = next((a for a in context.get("approvals", []) if a.get("approved")), None)
        create = bool(re.search(r"(?i)criar atividades aprovadas", text)) and approval is not None
        orch = AuditOrchestrator(call_tool, AuditStore(f"eval-{context['task_id']}", root=None), registry=FindingRegistry(path=None),
                                 now=lambda: now, sleep=lambda s: None)
        cp = orch.start(AuditRequest(environment=context.get("environment", "prod"), task_text=text,
                                     create_approved_jira=create, jira_approval=approval if create else None,
                                     trigger={"type": "manual", "requested_by": "eval-suite"}))
        out = to_audit_output(cp)
        out["agent"] = self.describe()
        return out
