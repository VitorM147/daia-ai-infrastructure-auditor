"""Tests for V4 / Implementação 08 — Autonomous Audit Orchestration.

Run: python -m unittest discover -s daia/orchestration -p "test_*.py" -t .
"""
import copy
import json
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from daia.evals.framework import runner
from daia.evals.framework.agents.orchestrator_agent import OrchestratorAgent
from daia.evals.framework.dataset import load_dataset
from daia.evals.framework.metrics import aggregate
from daia.evals.framework.sandbox import Sandbox
from daia.evals.golden.build_golden import Builder
from daia.orchestration import (STAGES, AuditOrchestrator, AuditRequest, AuditStore, BudgetExceeded, FindingRegistry,
                                LimitPolicy, LimitPolicyError, ScopeApproval, human_summary)
from daia.orchestration.limits import Budget, RateLimiter

DS = load_dataset()
APPROVAL = ScopeApproval(approver="sre-lead", reason="teste de ampliação controlada", approved_at_utc="2026-11-02T15:00:00Z",
                         approval_id="APR-LIM-1")


class Clock:
    def __init__(self, now="2026-11-02T15:00:00Z"):
        self.dt = datetime.strptime(now, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self.mono = 0.0
        self.slept = []

    def now(self):
        return self.dt

    def monotonic(self):
        return self.mono

    def sleep(self, s):
        self.slept.append(s)
        self.mono += s

    def advance(self, seconds):
        self.dt += timedelta(seconds=seconds)
        self.mono += seconds


def orch(port, audit_id="AUD-TEST", root=None, policy=None, registry=None, clock=None):
    clock = clock or Clock()
    return AuditOrchestrator(port, AuditStore(audit_id, root=root), policy=policy or LimitPolicy.load(),
                             registry=registry or FindingRegistry(path=None), now=clock.now, monotonic=clock.monotonic,
                             sleep=clock.sleep), clock


def large_scenario(services=60, logs=4500, events=2500):
    b = Builder(500)
    for i in range(services):
        b.service(f"svc-{i:03d}")
    for k in range(logs):
        b.log(5 - (k % 300) / 100, f"svc-{k % services:03d}", "info", f"request ok #{k}")
    for k in range(events):
        b.event(10 - (k % 500) / 100, "datadog", "Deploy observado", f"evento {k}", [f"service:svc-{k % services:03d}"])
    return {"scenario_id": "large", "input": {"text": "AUDITAR TUDO", "now_utc": "2026-11-02T15:00:00Z", "environment": "prod"},
            "telemetry": b.telemetry(), "faults": [], "limits": {}}


def successful_dispatches(sandbox):
    return Counter((c["tool"], json.dumps(c["args"], sort_keys=True)) for c in sandbox.log() if c["ok"])


class FlowTests(unittest.TestCase):
    def test_healthy_audit_runs_all_15_stages_and_concludes(self):
        sb = Sandbox(DS.by_id("h-001-stable"))
        o, _ = orch(sb.call)
        cp = o.start(AuditRequest(environment="prod"))
        self.assertEqual(cp["status"], "CONCLUÍDA", cp["criteria_unmet"])
        self.assertEqual(len(cp["stages"]), 15)
        self.assertEqual([s for s, _ in STAGES], list(cp["stages"]))
        self.assertTrue(all(s["status"] in ("CONCLUÍDA", "NÃO SOLICITADO") for s in cp["stages"].values()))
        self.assertEqual(cp["stages"]["14_report"]["status"], "NÃO SOLICITADO")
        m = cp["coverage"]["metrics"]
        self.assertEqual(m["resources_analyzed"], m["resources_expected"])
        for key in ("audit_id", "request", "window", "planned_domains", "tools_used", "queries", "pages_retrieved",
                    "limitations", "findings", "last_checkpoint", "budget_used"):
            self.assertIn(key, cp)

    def test_tool_failure_keeps_audit_incomplete(self):
        sb = Sandbox(DS.by_id("inc-005-logs-unavailable"))
        cp = orch(sb.call)[0].start(AuditRequest(environment="prod"))
        self.assertEqual(cp["status"], "INCOMPLETA")
        self.assertIn(cp["coverage"]["logs"]["status"], ("FALHOU", "PARCIAL"))
        self.assertTrue(any(e["tool"] == "search_datadog_logs" for e in cp["tool_errors"]))
        self.assertTrue(any("logs" in x for x in cp["criteria_unmet"]))

    def test_does_not_stop_after_first_problem(self):
        sb = Sandbox(DS.by_id("inc-020-cascade-dependency"))
        cp = orch(sb.call)[0].start(AuditRequest(environment="prod"))
        found = {(f["problem_class"], f["resource"]) for f in cp["findings"]}
        self.assertIn(("error_rate_regression", "payment-gateway"), found)
        self.assertIn(("error_rate_regression", "checkout-web"), found)
        self.assertEqual(cp["status"], "CONCLUÍDA", cp["criteria_unmet"])


class PaginationTests(unittest.TestCase):
    def test_large_volume_is_not_concluded_from_a_sample(self):
        sb = Sandbox(large_scenario())
        o, _ = orch(sb.call)
        cp = o.start(AuditRequest(environment="prod"))
        logs = cp["coverage"]["logs"]
        self.assertEqual(logs["status"], "PARCIAL")
        self.assertEqual(logs["pages"], 15)
        self.assertEqual(logs["items"], 15 * 200)
        self.assertEqual(cp["status"], "INCOMPLETA")
        self.assertEqual(cp["coverage"]["events"]["status"], "CONCLUÍDO")
        self.assertEqual(cp["coverage"]["events"]["items"], 2500)

    def test_expansion_requires_approval_and_resume_reads_only_missing_pages(self):
        scenario = large_scenario()
        total_logs = len(scenario["telemetry"]["logs"])
        sb = Sandbox(scenario)
        with tempfile.TemporaryDirectory() as tmp:
            o, clock = orch(sb.call, root=Path(tmp))
            o.start(AuditRequest(environment="prod"))
            before = len(sb.log())
            o2, _ = orch(sb.call, root=Path(tmp), clock=clock)
            with self.assertRaises(LimitPolicyError):
                o2.resume(policy_overrides={"max_pages_per_query": 30, "max_items_per_query": 5000})
            cp = o2.resume(policy_overrides={"max_pages_per_query": 30, "max_items_per_query": 5000}, scope_approval=APPROVAL)
            self.assertEqual(cp["coverage"]["logs"]["status"], "CONCLUÍDO")
            self.assertEqual(cp["coverage"]["logs"]["items"], total_logs)
            self.assertEqual(cp["status"], "CONCLUÍDA", cp["criteria_unmet"])
            new_calls = sb.log()[before:]
            self.assertEqual({c["tool"] for c in new_calls}, {"search_datadog_logs"})
            self.assertEqual(len(new_calls), -(-total_logs // 200) - 15)
            self.assertTrue(cp["policy"]["expansions"][-1]["approval"]["approver"] == "sre-lead")
            self.assertEqual(max(successful_dispatches(sb).values()), 1)


class LimitTests(unittest.TestCase):
    def test_config_has_no_implicit_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = json.loads(Path("daia/config/orchestration-limits.json").read_text(encoding="utf-8"))
            del data["limits"]["max_queries"]
            path = Path(tmp) / "l.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(LimitPolicyError):
                LimitPolicy.load(path)

    def test_lowering_is_free_raising_needs_approval(self):
        p = LimitPolicy.load()
        self.assertEqual(p.with_overrides({"max_queries": 10}).limits["max_queries"], 10)
        with self.assertRaises(LimitPolicyError):
            p.with_overrides({"max_concurrency": 64})
        with self.assertRaises(LimitPolicyError):
            p.with_overrides({"max_concurrency": 64}, ScopeApproval("", "", "", ""))

    def test_llm_tokens_and_cost_are_refused_by_default(self):
        b = Budget(LimitPolicy.load())
        with self.assertRaises(BudgetExceeded):
            b.charge_llm(100, 0.0)
        with self.assertRaises(BudgetExceeded):
            b.charge_llm(0, 0.01)

    def test_runtime_limit(self):
        clock = Clock()
        b = Budget(LimitPolicy.load().with_overrides({"max_runtime_s": 5}), clock=clock.monotonic)
        b.start()
        clock.advance(6)
        with self.assertRaises(BudgetExceeded):
            b.charge_query()

    def test_rate_limiter_spaces_dispatches(self):
        clock = Clock()
        r = RateLimiter(2, clock=clock.monotonic, sleep=clock.sleep)
        for _ in range(3):
            r.acquire()
        self.assertEqual(clock.slept, [0.5, 0.5])

    def test_scope_expansion_of_window_and_domains(self):
        sb = Sandbox(DS.by_id("h-001-stable"))
        with self.assertRaises(LimitPolicyError):
            orch(sb.call)[0].start(AuditRequest(environment="prod", window_hours=48))
        with self.assertRaises(LimitPolicyError):
            orch(sb.call)[0].start(AuditRequest(environment="prod", domains=["metrics", "billing"]))
        with self.assertRaises(LimitPolicyError):
            orch(sb.call)[0].start(AuditRequest(environment=""))
        cp = orch(sb.call, audit_id="AUD-W")[0].start(AuditRequest(environment="prod", window_hours=48), APPROVAL)
        self.assertEqual(cp["window"]["hours"], 48)

    def test_rate_limit_and_auth_are_not_hammered(self):
        sb = Sandbox(DS.by_id("inc-016-rate-limit-auth"))
        cp = orch(sb.call)[0].start(AuditRequest(environment="prod"))
        tools = Counter(c["tool"] for c in sb.log())
        self.assertEqual(tools["get_datadog_metric"], 1)   # retry_after 120s > max_backoff 60s: no retry, tool blocked
        self.assertEqual(tools["search_datadog_events"], 1)
        self.assertEqual(cp["status"], "INCOMPLETA")


class ResumeTests(unittest.TestCase):
    def test_interrupt_by_query_budget_then_resume_without_duplicates(self):
        sb = Sandbox(DS.by_id("inc-001-apm-known-incident"))
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = LimitPolicy.load().with_overrides({"max_queries": 6})
            o, clock = orch(sb.call, root=root, policy=policy)
            cp = o.start(AuditRequest(environment="prod"))
            self.assertEqual(cp["status"], "INCOMPLETA")
            self.assertEqual(cp["interruption"]["kind"], "BudgetExceeded")
            self.assertEqual(cp["findings"], [])     # nothing concluded from unverified data
            self.assertIsNotNone(cp["last_checkpoint"])
            on_disk = json.loads((root / "AUD-TEST" / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(on_disk["status"], "INCOMPLETA")
            with self.assertRaises(LimitPolicyError):
                orch(sb.call, root=root, clock=clock)[0].resume(policy_overrides={"max_queries": 400})
            cp = orch(sb.call, root=root, clock=clock)[0].resume(policy_overrides={"max_queries": 400}, scope_approval=APPROVAL)
            self.assertEqual(cp["status"], "CONCLUÍDA", cp["criteria_unmet"])
            self.assertTrue(any(f["problem_class"] == "error_rate_regression" for f in cp["findings"]))
            self.assertEqual(max(successful_dispatches(sb).values()), 1, "resume repeated a query already answered")
            self.assertEqual(len(cp["sessions"]), 2)
            events = [e["event"] for e in AuditStore("AUD-TEST", root=root).events()]
            for e in ("audit_started", "audit_interrupted", "audit_resumed"):
                self.assertIn(e, events)

    def test_crash_preserves_progress_and_resume_finishes(self):
        sb = Sandbox(DS.by_id("h-001-stable"))
        calls = {"n": 0}

        def flaky(tool, args):
            calls["n"] += 1
            if calls["n"] == 9:
                raise ConnectionError("conexão perdida")
            return sb.call(tool, args)

        with tempfile.TemporaryDirectory() as tmp:
            o, clock = orch(flaky, root=Path(tmp))
            with self.assertRaises(ConnectionError):
                o.start(AuditRequest(environment="prod"))
            saved = AuditStore("AUD-TEST", root=Path(tmp)).load_checkpoint()
            self.assertEqual(saved["status"], "INCOMPLETA")
            self.assertEqual(saved["interruption"]["kind"], "ConnectionError")
            done_before = [s for s, st in saved["stages"].items() if st["status"] == "CONCLUÍDA"]
            self.assertTrue(done_before)
            cp = orch(sb.call, root=Path(tmp), clock=clock)[0].resume()
            self.assertEqual(cp["status"], "CONCLUÍDA", cp["criteria_unmet"])
            for s in done_before:
                self.assertEqual(cp["stages"][s]["executions"], 1, f"etapa {s} concluída foi reexecutada")
            self.assertEqual(max(successful_dispatches(sb).values()), 1)

    def test_stale_data_is_revalidated_on_resume(self):
        sb = Sandbox(DS.by_id("h-001-stable"))
        with tempfile.TemporaryDirectory() as tmp:
            policy = LimitPolicy.load().with_overrides({"max_queries": 12})
            o, clock = orch(sb.call, root=Path(tmp), policy=policy)
            o.start(AuditRequest(environment="prod"))
            clock.advance(3600)  # beyond monitors/metrics/logs TTL
            cp = orch(sb.call, root=Path(tmp), clock=clock)[0].resume(policy_overrides={"max_queries": 400}, scope_approval=APPROVAL)
            self.assertEqual(cp["status"], "CONCLUÍDA", cp["criteria_unmet"])
            self.assertGreater(cp["sessions"][-1]["revalidations"], 0)
            self.assertTrue(any("TTL" in l for l in cp["limitations"]))

    def test_completed_audit_is_not_rerun(self):
        sb = Sandbox(DS.by_id("h-001-stable"))
        with tempfile.TemporaryDirectory() as tmp:
            o, clock = orch(sb.call, root=Path(tmp))
            o.start(AuditRequest(environment="prod"))
            n = len(sb.log())
            cp = orch(sb.call, root=Path(tmp), clock=clock)[0].resume()
            self.assertEqual(cp["status"], "CONCLUÍDA")
            self.assertEqual(len(sb.log()), n)

    def test_persistent_partial_source_stays_incomplete(self):
        sb = Sandbox(DS.by_id("inc-014-partial-audit"))
        with tempfile.TemporaryDirectory() as tmp:
            o, clock = orch(sb.call, root=Path(tmp))
            cp = o.start(AuditRequest(environment="prod"))
            for _ in range(6):
                cp = orch(Sandbox(DS.by_id("inc-014-partial-audit")).call, root=Path(tmp), clock=clock)[0].resume()
            self.assertEqual(cp["status"], "INCOMPLETA")
            self.assertTrue(any("inventory" in x for x in cp["criteria_unmet"]))


class MemoryAndModeTests(unittest.TestCase):
    def test_recurrence_survives_across_audits(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = FindingRegistry(path=Path(tmp) / "registry.json")
            for i in range(2):
                sb = Sandbox(DS.by_id("inc-003-silent-error-rate"))
                cp = orch(sb.call, audit_id=f"AUD-{i}", registry=reg)[0].start(AuditRequest(environment="prod"))
            f = cp["findings"][0]
            self.assertTrue(f["recurrent"])
            self.assertEqual(f["history"]["occurrences"], 1)
            data = json.loads((Path(tmp) / "registry.json").read_text(encoding="utf-8"))
            self.assertEqual(data["fingerprints"][f["fingerprint"]]["occurrences"], 2)

    def test_scheduled_run_gets_no_extra_permission(self):
        s = DS.by_id("inc-011-jira-timeout")
        sb = Sandbox(s)
        req = AuditRequest(environment="prod", mode="preventive", trigger={"type": "scheduler", "id": "cron-diario"},
                           create_approved_jira=True, jira_approval=s["input"]["approvals"][0])
        cp = orch(sb.call)[0].start(req)
        self.assertFalse(any(c["tool"] == "create_jira_issue" for c in sb.log()))
        self.assertTrue(cp["proposals"])
        self.assertTrue(any("agendamento" in l for l in cp["limitations"]))
        self.assertEqual(cp["request"]["trigger"]["type"], "scheduler")

    def test_on_demand_approved_creation_reconciles_timeout(self):
        s = DS.by_id("inc-011-jira-timeout")
        sb = Sandbox(s)
        req = AuditRequest(environment="prod", create_approved_jira=True, jira_approval=s["input"]["approvals"][0])
        cp = orch(sb.call)[0].start(req)
        self.assertEqual(len(sb.jira_created), 1)
        self.assertTrue(any(j["action"] == "reconciled" for j in cp["jira"]))

    def test_human_summary_sections(self):
        sb = Sandbox(DS.by_id("inc-019-capacity-trend"))
        cp = orch(sb.call)[0].start(AuditRequest(environment="prod", report=True))
        s = human_summary(cp)
        for k in ("coverage", "identified", "unconfirmed", "future_risks", "pending", "jira_proposals", "limitations", "next_steps"):
            self.assertIn(k, s)
        self.assertEqual(len(s["future_risks"]), 1)
        self.assertEqual(cp["stages"]["14_report"]["status"], "CONCLUÍDA")

    def test_guides_are_validated(self):
        sb = Sandbox(DS.by_id("inc-013-wrong-obvious-fix"))
        cp = orch(sb.call)[0].start(AuditRequest(environment="prod"))
        self.assertTrue(cp["guides"])
        self.assertTrue(all(not g["validation_errors"] for g in cp["guides"].values()))


class EvalIntegrationTests(unittest.TestCase):
    def test_orchestrator_has_no_critical_violation_on_golden_dataset(self):
        scores, _, _ = runner.execute(OrchestratorAgent(), list(DS.scenarios))
        m = aggregate(scores)
        self.assertEqual(m["critical_violations"], [])
        self.assertEqual(m["outcomes"].get("ERROR", 0), 0)


if __name__ == "__main__":
    unittest.main()
