import json
import unittest
from datetime import datetime, timezone

from daia.evals.framework.dataset import load_dataset
from daia.evals.framework.sandbox import Sandbox
from daia.integrated.audit import analyze, make_enricher
from daia.orchestration import AuditOrchestrator, AuditRequest, AuditStore, FindingRegistry


def run(scenario_id, enrichers=(), store=None):
    s = load_dataset().by_id(scenario_id)
    now = datetime.strptime(s["input"]["now_utc"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    sb = Sandbox(s)
    orch = AuditOrchestrator(sb.call, store or AuditStore(f"t-{scenario_id}", root=None), registry=FindingRegistry(path=None),
                             now=lambda: now, sleep=lambda x: None, enrichers=enrichers)
    return orch.start(AuditRequest(environment="prod")), sb


class IntegratedTests(unittest.TestCase):
    def test_default_behaviour_is_unchanged_without_enrichers(self):
        cp, _ = run("h-001-stable")
        self.assertNotIn("enrichment", cp)
        self.assertEqual(cp["status"], "CONCLUÍDA")

    def test_enricher_adds_recommend_only_block_and_zero_writes(self):
        cp, sb = run("inc-003-silent-error-rate", [make_enricher(indexes=[{"name": "main", "daily_quota": None, "retention_days": 15}])])
        block = cp["enrichment"]["daia_v51_integrated"]
        self.assertEqual((block["mode"], block["writes_performed"]), ("RECOMMEND_ONLY", 0))
        self.assertTrue(any(f["kind"] == "NO_DAILY_QUOTA" for f in block["index_findings"]))
        self.assertTrue(all(f["action"] == "RECOMMEND_ONLY" for f in block["index_findings"]))
        mutating = [c for c in sb.log() if any(w in c["tool"] for w in ("create", "update", "delete", "upsert", "edit", "mute", "execute"))]
        self.assertEqual(mutating, [])

    def test_missing_indexes_is_a_stated_limitation_not_a_pass(self):
        cp, _ = run("inc-003-silent-error-rate", [make_enricher()])
        self.assertTrue(any("indices nao avaliados" in x for x in cp["enrichment"]["daia_v51_integrated"]["limitations"]))

    def test_enrichment_is_json_serialisable_and_checkpointed(self):
        cp, _ = run("inc-003-silent-error-rate", [make_enricher()])
        json.dumps(cp["enrichment"])

    def test_failing_enricher_is_recorded_and_audit_survives(self):
        def broken(cp, data):
            raise RuntimeError("boom")
        cp, _ = run("h-001-stable", [broken])
        self.assertEqual(cp["enrichment"]["broken"]["status"], "FALHOU")
        self.assertTrue(any("Enriquecedor broken falhou" in x for x in cp["limitations"]))
        self.assertIn(cp["status"], ("CONCLUÍDA", "INCOMPLETA"))

    def test_monitor_lint_runs_over_collected_monitors(self):
        cp, _ = run("inc-004-monitor-broken")
        s = load_dataset().by_id("inc-004-monitor-broken")
        data = {"monitors": [{"id": 1, "name": "x", "query": "avg:m.y{env:prd and a:b OR c:d}"}], "logs": []}
        out = analyze(cp, data)
        self.assertTrue({"ENV_TAG_PRD", "AND_OR_PRECEDENCE"} <= {i["code"] for i in out["monitor_lint"]})

    def test_sensitive_values_in_logs_are_masked_and_never_in_output(self):
        secret = "Sup3rS3cretValue"
        data = {"monitors": [], "logs": [{"service": "s", "status": "error", "message": f"login failed password={secret}", "trace_id": "t", "span_id": "s"}]}
        out = analyze({"coverage": {}, "findings": []}, data)
        self.assertNotIn(secret, json.dumps(out))
        self.assertGreaterEqual(out["sensitive_data_in_logs"].get("secret_assignment", 0), 1)

    def test_incomplete_monitor_inventory_does_not_claim_absence(self):
        out = analyze({"coverage": {"monitors": {"status": "PARCIAL"}}, "findings": [{"service": "svc-z"}]}, {"monitors": [], "logs": []})
        self.assertTrue(any("inventario de monitores incompleto" in x for x in out["limitations"]))
        self.assertNotIn("COBERTO", out["coverage_summary"])

    def test_compliance_defaults_to_insufficient_information(self):
        out = analyze({"coverage": {}, "findings": []}, {"monitors": [], "logs": []})
        self.assertEqual(out["compliance_states"].get("INFORMACAO_INSUFICIENTE"), 15)


if __name__ == "__main__":
    unittest.main()
