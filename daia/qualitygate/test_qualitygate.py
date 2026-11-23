"""Cross-cutting V5.1 gates: security, financial governance and detector quality on synthetic labels."""
import ast
import re
import unittest
from pathlib import Path

from daia.costgov.classifier import CostProposal, classify
from daia.docs_intel.catalog import Catalog
from daia.qualitygate.labeled import metrics, run_all
from daia.security.tool_guard import ToolGuard

ROOT = Path(__file__).resolve().parents[1]
V51 = ["docs_intel", "logintel", "patterns", "costgov", "gaps", "alertnoise", "integrated", "qualitygate"]
NETWORK_ALLOWED = {ROOT / "docs_intel" / "cli.py"}
WRITE_ALLOWED = {ROOT / "docs_intel" / "cli.py", ROOT / "docs_intel" / "catalog.py", ROOT / "docs_intel" / "index_cache.py"}
BANNED_IMPORTS = {"requests", "httpx", "socket", "subprocess", "ftplib", "smtplib", "paramiko", "boto3", "kubernetes", "ctypes"}
NETWORK_IMPORTS = {"urllib.request", "http.client", "urllib3"}


def sources():
    for pkg in V51:
        for p in (ROOT / pkg).glob("*.py"):
            if not p.name.startswith("test_"):
                yield p


def imports_of(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            out.add(n.module)
    return out


class SecurityGate(unittest.TestCase):
    def test_no_banned_or_unexpected_network_imports(self):
        for p in sources():
            imps = imports_of(p)
            self.assertFalse({i.split(".")[0] for i in imps} & BANNED_IMPORTS, f"{p.name}: {imps & BANNED_IMPORTS}")
            if p not in NETWORK_ALLOWED:
                self.assertFalse(imps & NETWORK_IMPORTS, f"{p.name} imports a network module")

    def test_only_documented_modules_write_files(self):
        for p in sources():
            if p in WRITE_ALLOWED:
                continue
            text = p.read_text(encoding="utf-8")
            self.assertNotRegex(text, r"\.write_text\(|open\([^)]*['\"][wa]", f"{p.name} writes files")

    def test_no_dynamic_execution(self):
        for p in sources():
            self.assertNotRegex(p.read_text(encoding="utf-8"), r"\b(eval|exec)\(|os\.system|__import__\(", p.name)

    def test_only_official_host_is_ever_contacted(self):
        text = (ROOT / "docs_intel" / "cli.py").read_text(encoding="utf-8")
        hosts = set(re.findall(r"https?://([A-Za-z0-9.\-]+)", text))
        self.assertEqual(hosts, {"docs.datadoghq.com"})

    def test_no_secrets_or_personal_emails_in_v51_files(self):
        rx_email = re.compile(r"[A-Za-z0-9._%+\-]+@(?!example\.)[A-Za-z0-9\-]+\.[A-Za-z]{2,}")
        rx_secret = re.compile(r"AKIA[0-9A-Z]{16}|\b\d{12}\.dkr\.ecr|(?i:api[_-]?key)\s*[:=]\s*['\"]\w{8,}")
        for pkg in V51:
            for p in (ROOT / pkg).rglob("*"):
                if p.suffix in {".py", ".json", ".md"} and "__pycache__" not in p.parts and p.name != "test_qualitygate.py":
                    t = p.read_text(encoding="utf-8", errors="replace")
                    self.assertIsNone(rx_email.search(t), f"email in {p}")
                    self.assertIsNone(rx_secret.search(t), f"secret in {p}")

    def test_write_tools_remain_denied_by_the_existing_guard(self):
        g = ToolGuard(ROOT / "config" / "tool-allowlist.json")
        for tool in ("create_datadog_notebook", "upsert_datadog_dashboard", "execute_code", "_dd_wfd"):
            d = g.authorize({"tool_id": tool, "system": "Datadog", "operation": "x", "identity": "datadog-readonly",
                             "state_effect": "create", "method": "MCP"})
            self.assertFalse(d.allowed, tool)

    def test_rate_limit_429_is_never_retried(self):
        from datetime import date
        from daia.docs_intel.freshness import FetchResult, QueryBudget, verify_online
        calls = []
        verify_online(Catalog.load(), lambda u: (calls.append(u), FetchResult(429, headers={"Retry-After": "30"}))[1], QueryBudget(99), date.today())
        self.assertEqual(len(calls), 1)


class FinancialGate(unittest.TestCase):
    def test_zero_incremental_cost_invariants(self):
        cat = Catalog.load()
        self.assertFalse([r for r in cat.rules.values() if r.cost_status == "CUSTO_ZERO_CONFIRMADO"])
        self.assertTrue(all(r.action == "RECOMMEND_ONLY" and r.inspection == "READ_ONLY" for r in cat.rules.values()))
        for prod in ("sensitive_data_scanner", "audit_trail", "flex_logs", "synthetics", "rum", "apm"):
            self.assertEqual(classify(CostProposal("p", "monitor", products_required=(prod,))).status, "RECURSO_PAGO")

    def test_any_resource_creation_is_blocked_without_contract_validation(self):
        for kind in ("monitor", "dashboard", "slo", "index", "exclusion_filter", "pipeline", "custom_metric", "log_based_metric"):
            d = classify(CostProposal("x", kind, creates_or_enables_datadog_resource=True))
            self.assertTrue(d.blocked, kind)
            self.assertFalse(d.eligible_for_future_implementation, kind)


class DetectorQualityGate(unittest.TestCase):
    """Synthetic fixtures only: a failure here is a regression, a pass is not production accuracy."""

    def test_no_false_positives_or_negatives_on_labeled_fixtures(self):
        res = run_all()
        self.assertGreaterEqual(len(res), 6)
        for name, c in res.items():
            self.assertEqual(c["fp"], 0, f"{name} false positives {c}")
            self.assertEqual(c["fn"], 0, f"{name} false negatives {c}")

    def test_fixture_set_is_not_trivially_one_sided(self):
        for name, c in run_all().items():
            self.assertGreater(c["tp"], 0, name)
            self.assertGreater(c["tn"], 0, name)
        self.assertEqual(metrics({"tp": 3, "fp": 1, "fn": 0, "tn": 0})["precision"], 0.75)


if __name__ == "__main__":
    unittest.main()
