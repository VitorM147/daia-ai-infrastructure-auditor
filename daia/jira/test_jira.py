import unittest
import threading
from dataclasses import replace

from daia.jira.client import JiraAuthError, JiraTimeoutError
from daia.jira.controller import JiraController
from daia.jira.fingerprint import build_fingerprint
from daia.jira.models import CreationApproval, JiraConfig, JiraIssueProposal, JiraIssueSearchResult


class FakeJira:
    def __init__(self):
        self.issues = []
        self.create_calls = 0
        self.timeout_after_create = False
        self.auth_error = False
        self.create_started = None
        self.create_release = None

    def list_projects(self): return [{"key": "OPS"}]
    def get_issue_metadata(self, project): return {"required_fields": ["summary", "description"]}
    def search_by_fingerprint(self, fingerprint):
        if self.auth_error: raise JiraAuthError("401 unauthorized")
        return [i for i in self.issues if i.fingerprint == fingerprint]
    def get_issue_by_fingerprint(self, fingerprint): return [i for i in self.issues if i.fingerprint == fingerprint]
    def create_issue(self, project, payload):
        if self.auth_error: raise JiraAuthError("401 unauthorized")
        self.create_calls += 1
        if self.create_started: self.create_started.set()
        if self.create_release: self.create_release.wait(timeout=2)
        issue = JiraIssueSearchResult(str(self.create_calls), f"{project}-{self.create_calls}", f"https://jira.example/{project}-{self.create_calls}", payload["labels"][1], "Open")
        self.issues.append(issue)
        if self.timeout_after_create: raise JiraTimeoutError("response timeout")
        return issue


def proposal():
    fp = build_fingerprint(environment="prod", application="app", service="payments", resource="endpoint", problem_class="http-error", failure_identifier="vtex-400")
    return JiraIssueProposal("[DAIA][P2][PROD] payments — HTTP errors", "error", "synthetic", "P2", ("OBS synthetic",), ("HIP synthetic",), "none", "potential", ("read query",), ("conditional fix",), ("risk and rollback",), ("https://app.datadoghq.com/apm/traces (not validated)",), ("error rate normal",), "team-synthetic", fp, "AUD-SYN", "prod", "payments", "endpoint")


class JiraTests(unittest.TestCase):
    def controller(self, client=None):
        return JiraController(JiraConfig(base_url="https://jira.invalid", authorized_projects=("OPS",), configured=True), client or FakeJira())

    def test_proposal_is_structured(self):
        result = self.controller().propose(proposal())
        self.assertEqual(result["status"], "PROPOSTA")
        self.assertIn("fingerprint", result["payload"]["description"])

    def test_unauthorized_project_is_blocked(self):
        result = self.controller().preflight(proposal(), "SEC")
        self.assertEqual(result.status, "BLOQUEADO")

    def test_duplicate_is_not_created(self):
        client = FakeJira(); controller = self.controller(client); p = proposal()
        existing = JiraIssueSearchResult("1", "OPS-1", "https://jira.invalid/OPS-1", p.fingerprint, "Open")
        client.issues.append(existing)
        approval = CreationApproval("A1", True, p.fingerprint, "OPS", "human", "one issue")
        result = controller.create(p, "OPS", approval)
        self.assertEqual(result.status, "DUPLICATA")
        self.assertEqual(client.create_calls, 0)

    def test_denied_approval_is_blocked(self):
        p = proposal(); result = self.controller().create(p, "OPS", CreationApproval("A1", False, p.fingerprint, "OPS", "human", "one"))
        self.assertEqual(result.status, "BLOQUEADO")

    def test_timeout_reconciles_without_retry(self):
        client = FakeJira(); client.timeout_after_create = True; controller = self.controller(client); p = proposal()
        approval = CreationApproval("A1", True, p.fingerprint, "OPS", "human", "one issue")
        result = controller.create(p, "OPS", approval)
        self.assertEqual(result.status, "CRIADA_RECONCILIADA")
        self.assertEqual(client.create_calls, 1)

    def test_auth_failure_is_terminal(self):
        client = FakeJira(); client.auth_error = True; controller = self.controller(client); p = proposal()
        result = controller.preflight(p, "OPS")
        self.assertEqual(result.status, "NÃO_VERIFICADO")
        self.assertEqual(client.create_calls, 0)

    def test_simultaneous_creation_is_serialized(self):
        client = FakeJira(); client.create_started = threading.Event(); client.create_release = threading.Event()
        controller = self.controller(client); p = proposal()
        approval = CreationApproval("A1", True, p.fingerprint, "OPS", "human", "one issue")
        results = []
        first = threading.Thread(target=lambda: results.append(controller.create(p, "OPS", approval)))
        first.start(); self.assertTrue(client.create_started.wait(timeout=1))
        second = controller.create(p, "OPS", approval)
        client.create_release.set(); first.join(timeout=2)
        self.assertEqual(second.status, "CONCORRÊNCIA")
        self.assertEqual(client.create_calls, 1)

    def test_unconfigured_jira_is_not_claimed_as_connected(self):
        client = FakeJira(); controller = JiraController(JiraConfig(), client)
        result = controller.preflight(proposal(), "OPS")
        self.assertEqual(result.status, "NÃO_VERIFICADO")

    def test_missing_field_and_sensitive_payload(self):
        p = proposal()
        with self.assertRaises(ValueError):
            self.controller().propose(replace(p, title="<missing>"))
        payload = p.payload()
        self.assertNotIn("password", str(payload).lower())
        self.assertNotIn("token", str(payload).lower())


if __name__ == "__main__":
    unittest.main()
