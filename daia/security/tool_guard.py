"""Deterministic, offline tool authorization for DAIA.

This module is a policy decision point, not a transport proxy. The caller must
stop before dispatching an MCP/API/local operation when ``allowed`` is false.
It never calls a tool, network, shell, or model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason: str
    tool_id: str
    permission_class: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "tool_id": self.tool_id,
            "permission_class": self.permission_class,
        }


class PolicyError(ValueError):
    """Raised when the policy file is malformed."""


class ToolGuard:
    """Authorize canonical operation requests using a default-deny policy."""

    REQUIRED_ENTRY_FIELDS = {
        "id", "system", "operation", "permission_class", "identity",
        "state_effect", "allowed_methods", "scopes", "limits", "verification",
    }
    ALLOWED_CLASSES = {
        "READ_ONLY_VERIFIED", "JIRA_CREATE_APPROVED", "KNOWLEDGE_WRITE_APPROVED",
    }
    SAFE_READ_EFFECTS = {"none"}

    def __init__(self, policy_path: str | Path):
        self.policy_path = Path(policy_path)
        self.policy = self._load()
        self._entries = {item["id"]: item for item in self.policy["tools"]}
        self._blocked = {item["id"]: item for item in self.policy["blocked_tools"]}

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.policy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PolicyError(f"cannot load policy: {exc}") from exc
        if data.get("default_decision") != "deny":
            raise PolicyError("default_decision must be deny")
        if not isinstance(data.get("tools"), list) or not isinstance(data.get("blocked_tools"), list):
            raise PolicyError("tools and blocked_tools must be lists")
        ids: set[str] = set()
        for item in data["tools"]:
            missing = self.REQUIRED_ENTRY_FIELDS - item.keys()
            if missing:
                raise PolicyError(f"tool {item.get('id', '<unknown>')} missing {sorted(missing)}")
            if item["id"] in ids:
                raise PolicyError(f"duplicate tool id: {item['id']}")
            ids.add(item["id"])
            if item["permission_class"] not in self.ALLOWED_CLASSES:
                raise PolicyError(f"invalid permission class: {item['permission_class']}")
            if item["state_effect"] not in {"none", "create", "update", "delete", "execute", "notify", "unknown"}:
                raise PolicyError(f"invalid state effect: {item['state_effect']}")
        for item in data["blocked_tools"]:
            if item["id"] in ids:
                raise PolicyError(f"tool both allowed and blocked: {item['id']}")
        return data

    @staticmethod
    def _decision(request: Mapping[str, Any], allowed: bool, reason: str, entry: Mapping[str, Any] | None = None) -> AuthorizationDecision:
        return AuthorizationDecision(allowed, reason, str(request.get("tool_id", "<missing>")), entry.get("permission_class") if entry else None)

    def authorize(self, request: Mapping[str, Any]) -> AuthorizationDecision:
        """Return a decision without dispatching the requested operation.

        Required request fields: tool_id, system, operation, identity,
        state_effect, method. Optional fields are checked when policy limits or
        scopes are supplied. A declared effect is never trusted over policy.
        """
        required = {"tool_id", "system", "operation", "identity", "state_effect", "method"}
        missing = required - request.keys()
        if missing:
            return self._decision(request, False, f"missing request fields: {sorted(missing)}")
        tool_id = request["tool_id"]
        if tool_id in self._blocked:
            return self._decision(request, False, "tool is explicitly blocked", self._blocked[tool_id])
        entry = self._entries.get(tool_id)
        if entry is None:
            return self._decision(request, False, "tool is absent from allowlist (default-deny)")
        if entry["permission_class"] not in self.ALLOWED_CLASSES:
            return self._decision(request, False, "permission class is not executable", entry)
        for field in ("system", "operation", "identity"):
            if request[field] != entry[field]:
                return self._decision(request, False, f"{field} mismatch", entry)
        if request["state_effect"] != entry["state_effect"]:
            return self._decision(request, False, "requested state effect exceeds policy", entry)
        if request["method"] not in entry["allowed_methods"]:
            return self._decision(request, False, "transport/method is not allowed", entry)
        verification = entry["verification"]
        if verification.get("status") in {"unverified", "unconfigured"}:
            return self._decision(request, False, "tool verification or configuration is incomplete", entry)
        if entry["system"] == "Datadog" and entry["state_effect"] != "none":
            return self._decision(request, False, "Datadog mutations are forbidden", entry)
        if entry["permission_class"] == "JIRA_CREATE_APPROVED":
            if not request.get("human_approval", False):
                return self._decision(request, False, "human approval is required for Jira creation", entry)
            project = request.get("jira_project")
            allowed_projects = entry["scopes"].get("jira_projects", [])
            if not project or project not in allowed_projects:
                return self._decision(request, False, "Jira project is not explicitly authorized", entry)
        if entry["permission_class"] == "KNOWLEDGE_WRITE_APPROVED":
            path = request.get("path", "").replace("\\", "/")
            scopes = entry["scopes"].get("paths", [])
            if not any(path.startswith(scope) for scope in scopes):
                return self._decision(request, False, "local write path is outside approved scope", entry)
        limits = entry["limits"]
        if request.get("pages", 1) > limits.get("max_pages", 0):
            return self._decision(request, False, "page limit exceeded", entry)
        if request.get("items", 1) > limits.get("max_items", 0):
            return self._decision(request, False, "item limit exceeded", entry)
        if request.get("timeout_ms", 0) > limits.get("timeout_ms", 0):
            return self._decision(request, False, "timeout limit exceeded", entry)
        return self._decision(request, True, "authorized by explicit policy", entry)

    def audit_record(self, request: Mapping[str, Any], decision: AuthorizationDecision) -> dict[str, Any]:
        """Return a redaction-safe record suitable for the local audit log."""
        return {
            "tool_id": decision.tool_id,
            "allowed": decision.allowed,
            "reason": decision.reason,
            "permission_class": decision.permission_class,
            "system": request.get("system"),
            "operation": request.get("operation"),
            "identity": request.get("identity"),
            "state_effect": request.get("state_effect"),
        }
