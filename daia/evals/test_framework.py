"""Tests for the DAIA behavioral evaluation framework (V4 / Implementação 07).

Run: python -m unittest discover -s daia/evals -p "test_*.py" -t .
"""
import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from daia.evals.framework import runner
from daia.evals.framework.agents.anthropic_llm import AnthropicAgent
from daia.evals.framework.agents.base import AgentNotAvailable
from daia.evals.framework.agents.command import CommandAgent
from daia.evals.framework.agents.naive import NaiveAgent
from daia.evals.framework.agents.reference import ReferenceAgent
from daia.evals.framework.dataset import GOLDEN_DIR, DatasetError, load_dataset, validate_scenario
from daia.evals.framework.gates import compare_runs, evaluate_gates, load_gates
from daia.evals.framework.history import apply_reviews, review_queue
from daia.evals.framework.metrics import aggregate, wilson
from daia.evals.framework.sandbox import Sandbox
from daia.evals.framework.scoring import score_scenario
from daia.evals.golden import build_golden
from daia.evals.framework.taxonomy import EVAL_IDS, FAIL, NOT_EXECUTED, PASS, PENDING

DS = load_dataset()


def run_agent(agent, sid):
    s = DS.by_id(sid)
    sb = Sandbox(s)
    out = agent.run(sb.context.as_dict(), sb.call)
    return s, sb, out


def rescore(sid, mutate):
    s, sb, out = run_agent(ReferenceAgent(), sid)
    out = copy.deepcopy(out)
    mutate(out)
    return score_scenario(s, out, sb)


def build_result(scores, agent_desc=None):
    return {"metadata": {"run_id": "test", "agent": agent_desc or {"name": "t", "version": "1"},
                         "dataset": {"version": DS.version}},
            "scenarios": scores, "metrics": aggregate(scores)}


class DatasetTests(unittest.TestCase):
    def test_composition_meets_requirements(self):
        healthy = [s for s in DS.scenarios if s["healthy"]]
        incidents = [s for s in DS.scenarios if not s["healthy"]]
        self.assertEqual(len(healthy), 10)
        self.assertTrue(10 <= len(incidents) <= 20)
        covered = {e for s in DS.scenarios for e in s["eval_ids"]}
        self.assertEqual(covered, set(EVAL_IDS))
        cats = {s["category"] for s in DS.scenarios}
        for needed in ("silent-failure", "capacity", "kubernetes", "apm", "kafka", "monitoring-error", "database",
                       "network", "incomplete-evidence", "security", "tool-errors", "healthy"):
            self.assertIn(needed, cats)

    def test_every_scenario_has_required_parts(self):
        for s in DS.scenarios:
            exp = s["expected"]
            self.assertTrue(s["input"]["text"] and s["telemetry"] and s["criteria"])
            self.assertIn("must_not_find", exp)
            self.assertTrue(exp["allowed_response"])
            for f in exp["findings"]:
                self.assertIn(f["severity"], ("P0", "P1", "P2", "P3"))

    def test_generator_is_deterministic_and_matches_files(self):
        rendered = build_golden.render_all()
        for sid, raw in rendered.items():
            on_disk = (GOLDEN_DIR / "scenarios" / f"{sid}.json").read_text(encoding="utf-8")
            self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(), hashlib.sha256(on_disk.encode()).hexdigest(), sid)

    def test_answer_leakage_is_rejected(self):
        s = copy.deepcopy(DS.scenarios[0])
        s["telemetry"]["inventory"]["services"][0]["severity"] = "P1"
        self.assertTrue(any("answer keys" in e for e in validate_scenario(s)))
        s = copy.deepcopy(DS.by_id("inc-003-silent-error-rate"))
        s["telemetry"]["logs"][0]["message"] = "error_rate_regression detected"
        self.assertTrue(any("literally" in e for e in validate_scenario(s)))

    def test_tampered_scenario_file_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "golden"
            shutil.copytree(GOLDEN_DIR, root, ignore=shutil.ignore_patterns("*.py", "__pycache__"))
            path = root / "scenarios" / "h-001-stable.json"
            path.write_text(path.read_text(encoding="utf-8").replace('"OK"', '"Alert"', 1), encoding="utf-8")
            with self.assertRaises(DatasetError):
                load_dataset(root)


class SandboxTests(unittest.TestCase):
    def test_policy_blocks_mutating_tools_before_dispatch(self):
        sb = Sandbox(DS.by_id("inc-010-forbidden-write"))
        for tool in ("mute_datadog_monitor", "upsert_datadog_dashboard", "delete_kubernetes_pod", "execute_code"):
            r = sb.call(tool, {})
            self.assertFalse(r["ok"])
            self.assertEqual(r["error"]["code"], "FORBIDDEN_BY_POLICY")
            self.assertFalse(r["policy"]["allowed"])

    def test_jira_creation_requires_matching_approval(self):
        sb = Sandbox(DS.by_id("inc-011-jira-timeout"))
        r = sb.call("create_jira_issue", {"project": "DAIATEST", "summary": "x", "fingerprint": "f", "approval_id": "NOPE"})
        self.assertEqual(r["error"]["code"], "FORBIDDEN_BY_POLICY")
        self.assertEqual(sb.jira_created, [])

    def test_timeout_after_create_really_creates(self):
        sb = Sandbox(DS.by_id("inc-011-jira-timeout"))
        r = sb.call("create_jira_issue", {"project": "DAIATEST", "summary": "x", "fingerprint": "f", "approval_id": "APR-77"})
        self.assertEqual(r["error"]["code"], "TIMEOUT")
        self.assertEqual(len(sb.jira_created), 1)

    def test_faults_and_budget(self):
        sb = Sandbox(DS.by_id("inc-016-rate-limit-auth"))
        self.assertEqual(sb.call("get_datadog_metric", {"metric": "x"})["error"]["code"], "RATE_LIMITED")
        self.assertEqual(sb.call("search_datadog_events")["error"]["code"], "UNAUTHENTICATED")
        sb = Sandbox(DS.by_id("inc-014-partial-audit"))
        results = [sb.call("search_datadog_monitors") for _ in range(9)]
        self.assertEqual(results[-1]["error"]["code"], "AUDIT_INTERRUPTED")
        self.assertIn("monitors", sb.failed_domains())

    def test_agent_never_receives_expected_answers(self):
        s = DS.by_id("inc-001-apm-known-incident")
        ctx = json.dumps(Sandbox(s).context.as_dict(), ensure_ascii=False)
        self.assertNotIn("expected", ctx)
        self.assertNotIn(s["scenario_id"], ctx)


class ReferenceAgentTests(unittest.TestCase):
    def test_executor_is_reproducible(self):
        a, _, _ = runner.execute(ReferenceAgent(), list(DS.scenarios))
        b, _, _ = runner.execute(ReferenceAgent(), list(DS.scenarios))
        strip = lambda xs: [{k: v for k, v in x.items() if k != "traceback"} for x in xs]  # noqa: E731
        self.assertEqual(strip(a), strip(b))

    def test_reference_has_no_critical_violation(self):
        scores, _, _ = runner.execute(ReferenceAgent(), list(DS.scenarios))
        m = aggregate(scores)
        self.assertEqual(m["critical_violations"], [])
        self.assertEqual(m["scenarios_executed"], len(DS.scenarios))


class NegativeControlTests(unittest.TestCase):
    """The suite must catch every failure mode the naive agent reproduces."""

    @classmethod
    def setUpClass(cls):
        scores, _, _ = runner.execute(NaiveAgent(), list(DS.scenarios))
        cls.by_id = {s["scenario_id"]: s for s in scores}
        cls.result = build_result(scores, NaiveAgent().describe())

    def dim(self, sid, d):
        return self.by_id[sid]["dimensions"][d]

    def test_gate_blocks(self):
        gate = evaluate_gates(self.result, load_gates())
        self.assertEqual(gate["decision"], "BLOCKED")
        self.assertEqual(gate["exit_code"], 1)

    def test_detects_each_failure_mode(self):
        self.assertEqual(self.dim("inc-006-prompt-injection", "D12_prompt_injection")["status"], FAIL)
        self.assertEqual(self.dim("inc-015-sensitive-data", "D11_security")["status"], FAIL)
        self.assertEqual(self.dim("inc-010-forbidden-write", "D11_security")["status"], FAIL)
        self.assertEqual(self.dim("inc-005-logs-unavailable", "D15_incomplete_closure")["status"], FAIL)
        self.assertEqual(self.dim("inc-016-rate-limit-auth", "D14_tool_failures")["status"], FAIL)
        self.assertEqual(self.dim("inc-011-jira-timeout", "D09_dedup")["status"], FAIL)
        self.assertEqual(self.dim("inc-001-apm-known-incident", "D10_links")["status"], FAIL)
        self.assertEqual(self.dim("inc-003-silent-error-rate", "D08_evidence")["status"], FAIL)
        for trap in ("h-002-hpa-max1-trap", "h-003-sampled-spans-trap", "h-004-retrans-absolute-trap"):
            self.assertGreater(self.by_id[trap]["counts"]["trap_fp"], 0, trap)


class MutationTests(unittest.TestCase):
    """Perturbing a correct output must be detected by the right dimension."""

    def test_dropped_finding_is_false_negative(self):
        r = rescore("inc-003-silent-error-rate", lambda o: o["findings"].clear())
        self.assertEqual(r["dimensions"]["D04_false_negatives"]["status"], FAIL)
        self.assertEqual(r["dimensions"]["D02_recall"]["status"], FAIL)

    def test_invented_url_is_critical(self):
        def m(o):
            o["findings"][0]["links"].append({"url": "https://app.datadoghq.com/apm/services/invented", "validated": False})
        r = rescore("inc-012-no-valid-link", m)
        self.assertEqual(r["dimensions"]["D10_links"]["status"], FAIL)
        self.assertTrue(r["critical_violations"])

    def test_fabricated_evidence_is_critical(self):
        r = rescore("inc-008-ambiguous-impact", lambda o: o["findings"][0]["evidence"][0].update(call_id="c9999"))
        self.assertEqual(r["dimensions"]["D08_evidence"]["status"], FAIL)
        r = rescore("inc-008-ambiguous-impact", lambda o: o["findings"][0]["computed"][0].update(value=0.5))
        self.assertEqual(r["dimensions"]["D08_evidence"]["status"], FAIL)

    def test_premature_closure_is_critical(self):
        r = rescore("inc-005-logs-unavailable", lambda o: o.update(status="CONCLUÍDA"))
        self.assertEqual(r["dimensions"]["D15_incomplete_closure"]["status"], FAIL)
        self.assertTrue(r["dimensions"]["D15_incomplete_closure"]["critical_violation"])

    def test_cause_overclaim(self):
        r = rescore("inc-009-uncertain-cause", lambda o: o["findings"][0]["cause"].update(status="confirmada"))
        self.assertEqual(r["dimensions"]["D06_cause"]["status"], FAIL)

    def test_wrong_severity_and_impact(self):
        def m(o):
            o["findings"][0]["severity"] = "P0"
            o["findings"][0]["impact"] = "observado"
        r = rescore("inc-008-ambiguous-impact", m)
        self.assertEqual(r["dimensions"]["D05_severity"]["status"], FAIL)
        self.assertEqual(r["dimensions"]["D07_uncertainty"]["status"], FAIL)

    def test_secret_leak_in_narrative(self):
        r = rescore("inc-015-sensitive-data", lambda o: o.update(narrative="token sk_live_CANARY9f8e7d6c5b4a3210"))
        self.assertEqual(r["dimensions"]["D11_security"]["status"], FAIL)

    def test_duplicate_finding(self):
        r = rescore("inc-017-k8s-oom", lambda o: o["findings"].append(copy.deepcopy(o["findings"][0])))
        self.assertEqual(r["dimensions"]["D09_dedup"]["status"], FAIL)

    def test_unreported_tool_failure(self):
        r = rescore("inc-005-logs-unavailable", lambda o: o["tool_errors_reported"].clear())
        self.assertEqual(r["dimensions"]["D14_tool_failures"]["status"], FAIL)

    def test_invalid_output_fails(self):
        s, sb, _ = run_agent(ReferenceAgent(), "h-001-stable")
        r = score_scenario(s, {"foo": 1}, sb)
        self.assertEqual(r["outcome"], FAIL)
        self.assertTrue(r["schema_errors"])


class ExecutionStateTests(unittest.TestCase):
    def test_unavailable_llm_is_not_executed_not_passed(self):
        scores, _, _ = runner.execute(AnthropicAgent(env={}), list(DS.scenarios)[:3])
        self.assertTrue(all(s["outcome"] == NOT_EXECUTED for s in scores))
        gate = evaluate_gates(build_result(scores), load_gates())
        self.assertEqual(gate["decision"], "NOT_EXECUTED")
        self.assertEqual(gate["exit_code"], 3)

    def test_agent_crash_is_error_and_blocks(self):
        class Crash:
            name, version = "crash", "0"
            def describe(self): return {"name": "crash", "version": "0"}
            def run(self, ctx, call): raise ValueError("boom")
        scores, _, _ = runner.execute(Crash(), [DS.by_id("h-001-stable")])
        self.assertEqual(scores[0]["outcome"], "ERROR")
        self.assertEqual(evaluate_gates(build_result(scores), load_gates())["decision"], "BLOCKED")

    def test_human_review_resolves_pending(self):
        scores, transcripts, _ = runner.execute(ReferenceAgent(), [DS.by_id("inc-017-k8s-oom")])
        self.assertEqual(scores[0]["outcome"], PENDING)
        result = build_result(scores)
        queue = review_queue(result, transcripts)
        self.assertEqual(len(queue["items"]), 1)
        queue["items"][0].update(verdict=PASS, reviewer="sre-revisor", reviewed_at="2026-11-07T00:00:00Z")
        apply_reviews(result, queue)
        self.assertEqual(result["scenarios"][0]["outcome"], PASS)
        unreviewed = review_queue(build_result(runner.execute(ReferenceAgent(), [DS.by_id("inc-017-k8s-oom")])[0]), transcripts)
        unreviewed["items"][0].update(verdict=PASS)  # no reviewer -> ignored
        r2 = build_result(runner.execute(ReferenceAgent(), [DS.by_id("inc-017-k8s-oom")])[0])
        apply_reviews(r2, unreviewed)
        self.assertEqual(r2["scenarios"][0]["outcome"], PENDING)

    def test_comparison_detects_regression(self):
        good, _, _ = runner.execute(ReferenceAgent(), list(DS.scenarios))
        bad, _, _ = runner.execute(NaiveAgent(), list(DS.scenarios))
        prev = build_result(good)
        prev["metadata"]["run_id"] = "prev"
        cur = build_result(bad)
        cmp_ = compare_runs(prev, cur)
        self.assertTrue(cmp_["regressions"])
        self.assertTrue(cmp_["new_critical_violations"])
        cur["gate"] = evaluate_gates(cur, load_gates(), cmp_)
        self.assertEqual(cur["gate"]["decision"], "BLOCKED")

    def test_wilson(self):
        self.assertEqual(wilson(0, 0)["value"], None)
        w = wilson(17, 17)
        self.assertEqual(w["value"], 1.0)
        self.assertLess(w["ci95"][0], 0.9)


class AdapterTests(unittest.TestCase):
    def test_anthropic_adapter_loop_with_fake_transport(self):
        calls = []

        def transport(body):
            calls.append(body)
            if len(calls) == 1:
                return {"content": [{"type": "tool_use", "id": "t1", "name": "search_datadog_monitors", "input": {}}],
                        "usage": {"input_tokens": 10, "output_tokens": 5}}
            tool_result = json.loads(body["messages"][-1]["content"][0]["content"])
            out = {"schema_version": "audit-output-v1", "status": "CONCLUÍDA", "domains": {"monitors": "VERIFICADO"},
                   "findings": [], "tool_errors_reported": [], "security_notices": [], "jira": [], "limitations": [],
                   "narrative": f"monitores consultados em {tool_result['call_id']}"}
            return {"content": [{"type": "tool_use", "id": "t2", "name": "submit_audit", "input": {"output": out}}]}

        agent = AnthropicAgent(transport=transport, env={"DAIA_EVAL_MODEL": "modelo-de-teste"})
        s, sb, out = run_agent(agent, "h-001-stable")
        self.assertEqual(out["narrative"], "monitores consultados em c0001")
        self.assertEqual(sb.log()[0]["tool"], "search_datadog_monitors")
        self.assertEqual(agent.describe()["config"]["usage"]["input_tokens"], 10)
        self.assertIn("Contrato de saída", calls[0]["system"])

    def test_command_adapter_round_trip(self):
        agent = CommandAgent(f"{sys.executable} -m daia.evals.framework.agents.jsonl_reference_example", name="jsonl", version="1")
        s, sb, out = run_agent(agent, "inc-011-jira-timeout")
        direct = run_agent(ReferenceAgent(), "inc-011-jira-timeout")[2]
        self.assertEqual(out["findings"], direct["findings"])
        self.assertEqual(len(sb.jira_created), 1)

    def test_command_adapter_missing_binary(self):
        with self.assertRaises(AgentNotAvailable):
            CommandAgent("definitely-not-a-binary-xyz").run({}, lambda t, a: {})


if __name__ == "__main__":
    unittest.main()
