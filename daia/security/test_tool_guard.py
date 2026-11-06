import json
import unittest
from pathlib import Path

from daia.security.tool_guard import ToolGuard


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "daia" / "config" / "tool-allowlist.json"


def request(**overrides):
    value = {
        "tool_id": "search_datadog_monitors",
        "system": "Datadog",
        "operation": "read_monitors",
        "identity": "datadog-readonly",
        "state_effect": "none",
        "method": "MCP",
        "pages": 1,
        "items": 1,
        "timeout_ms": 1000,
    }
    value.update(overrides)
    return value


class ToolGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = ToolGuard(POLICY)

    def assertDenied(self, req, reason):
        decision = self.guard.authorize(req)
        self.assertFalse(decision.allowed)
        self.assertIn(reason, decision.reason)
        return decision

    def test_known_datadog_read_is_allowed(self):
        self.assertTrue(self.guard.authorize(request()).allowed)

    def test_unknown_tool_is_default_deny(self):
        self.assertDenied(request(tool_id="not_in_policy"), "default-deny")

    def test_datadog_write_is_blocked_independent_of_method(self):
        decision = self.assertDenied(
            request(
                tool_id="create_datadog_notebook",
                system="Datadog",
                operation="create_notebook",
                identity="datadog-readonly",
                state_effect="create",
                method="GET",
            ),
            "explicitly blocked",
        )
        self.assertFalse(decision.allowed)

    def test_arbitrary_code_is_blocked(self):
        self.assertDenied(
            request(
                tool_id="execute_code",
                system="Datadog",
                operation="execute",
                identity="datadog-readonly",
                state_effect="execute",
                method="MCP",
            ),
            "explicitly blocked",
        )

    def test_effect_mismatch_is_denied(self):
        self.assertDenied(request(state_effect="update"), "exceeds policy")

    def test_identity_mismatch_is_denied(self):
        self.assertDenied(request(identity="jira-read"), "identity mismatch")

    def test_limits_are_enforced_before_dispatch(self):
        self.assertDenied(request(pages=16), "page limit")
        self.assertDenied(request(timeout_ms=30001), "timeout limit")

    def test_jira_requires_approval_and_authorized_project(self):
        base = request(
            tool_id="create_jira_issue",
            system="Jira",
            operation="create_issue",
            identity="jira-create-approved",
            state_effect="create",
            method="API",
            jira_project="OPS",
        )
        self.assertDenied(base, "verification or configuration")
        self.assertDenied({**base, "human_approval": True}, "verification or configuration")

    def test_local_write_requires_approved_path(self):
        base = request(
            tool_id="write_daia_knowledge",
            system="DAIA_LOCAL",
            operation="write_knowledge",
            identity="daia-local-writer",
            state_effect="create",
            method="LOCAL",
            path="C:/tmp/escape.md",
        )
        self.assertDenied(base, "outside approved scope")
        allowed = self.guard.authorize({**base, "path": "daia/knowledge/finding.md"})
        self.assertTrue(allowed.allowed)

    def test_missing_request_fields_are_denied(self):
        self.assertDenied({"tool_id": "search_datadog_monitors"}, "missing request fields")

    def test_audit_record_contains_no_payload(self):
        req = request(payload="SECRET_SHOULD_NOT_BE_LOGGED")
        decision = self.guard.authorize(req)
        record = self.guard.audit_record(req, decision)
        self.assertNotIn("payload", json.dumps(record))
        self.assertNotIn("SECRET", json.dumps(record))


if __name__ == "__main__":
    unittest.main()
