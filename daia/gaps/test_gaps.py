import unittest

from daia.costgov.classifier import BLOCKED, ContractValidation
from daia.docs_intel.catalog import Catalog
from daia.gaps import compliance as comp
from daia.gaps.coverage import (COBERTO, NAO_VERIFICADO, PARCIAL, SEM_TELEMETRIA, ServiceInput, build_matrix,
                                can_declare_complete_audit, summarize)
from daia.gaps.querylint import duplicate_groups, lint_query
from daia.gaps.recommend import (DashboardCandidate, MonitorCandidate, propose_dashboard, propose_monitor)

DOC = "https://docs.datadoghq.com/monitors/"
OK = ContractValidation("fin-ops", "2026-11-01", "REF-1", "monitors included")


def codes(issues):
    return {i.code for i in issues}


class QueryLintTests(unittest.TestCase):
    def test_env_prd_tag(self):
        self.assertIn("ENV_TAG_PRD", codes(lint_query("1", "avg(last_5m):avg:x.y{env:prd,service:svc-a} > 1")))
        self.assertNotIn("ENV_TAG_PRD", codes(lint_query("1", "avg:x.y{env:prod,name:db-prd-01} > 1")))

    def test_physical_name_with_prd_is_not_flagged(self):
        self.assertEqual(codes(lint_query("2", "avg:aws.rds.cpuutilization{name:rds-sample-prd*} by {dbinstanceidentifier} > 85")), set())

    def test_and_or_precedence(self):
        self.assertIn("AND_OR_PRECEDENCE", codes(lint_query("3", "sum:m.x{env:prod and service:a* OR service:b} by {pdb}")))
        self.assertNotIn("AND_OR_PRECEDENCE", codes(lint_query("3", "sum:m.x{env:prod AND (service:a* OR service:b)} by {pdb}")))
        self.assertNotIn("AND_OR_PRECEDENCE", codes(lint_query("3", "sum:m.x{env:prod,service:a}")))

    def test_cluster_tag_name(self):
        self.assertIn("CLUSTER_TAG_NAME", codes(lint_query("4", "sum:container.cpu.usage{cluster_name:c1,pod_phase:running} by {pod_name}")))
        self.assertNotIn("CLUSTER_TAG_NAME", codes(lint_query("4", "sum:container.cpu.usage{kube_cluster_name:c1} by {pod_name}")))

    def test_legacy_api_metric(self):
        self.assertIn("LEGACY_API_USAGE_METRIC", codes(lint_query("5", "sum:datadog.apis.usage.per_org{*}")))

    def test_framework_mismatch_needs_known_framework(self):
        q = "sum:trace.http.request.hits{env:prod,service:svc-pay}.as_count()"
        self.assertIn("APM_METRIC_FRAMEWORK_MISMATCH", codes(lint_query("6", q, {"svc-pay": "netty"})))
        self.assertEqual(codes(lint_query("6", q, None)) & {"APM_METRIC_FRAMEWORK_MISMATCH"}, set())
        self.assertEqual(codes(lint_query("6", q, {"svc-pay": "http"})) & {"APM_METRIC_FRAMEWORK_MISMATCH"}, set())

    def test_issues_always_carry_a_read_only_verification(self):
        for i in lint_query("7", "avg:x.y{env:prd and a:b OR c:d}"):
            self.assertTrue(i.verify)
            self.assertIn(i.confidence, {"ALTA", "MEDIA"})

    def test_duplicates(self):
        ms = [{"id": "1", "query": "avg:a{x}>1"}, {"id": "2", "query": "avg:a{x} > 1"}, {"id": "3", "query": "avg:b{x}>1"}]
        self.assertEqual(duplicate_groups(ms), [["1", "2"]])


class CoverageTests(unittest.TestCase):
    MON = [{"id": "m1", "name": "svc-a errors", "query": "sum:trace.http.request.errors{service:svc-a}.as_count()>5"},
           {"id": "m2", "name": "svc-b cpu", "query": "avg:container.cpu.usage{kube_deployment:svc-b}>90"}]

    def test_direct_partial_and_unverified(self):
        rows = build_matrix([ServiceInput("svc-a", has_apm=True), ServiceInput("svc-b", has_apm=True), ServiceInput("svc-c", has_apm=True)], self.MON, True)
        st = {(r.service, r.signal): r.status for r in rows}
        self.assertEqual(st[("svc-a", "errors")], COBERTO)
        self.assertEqual(st[("svc-a", "latency")], PARCIAL)
        self.assertEqual(st[("svc-c", "errors")], NAO_VERIFICADO)

    def test_incomplete_inventory_never_proves_absence(self):
        rows = build_matrix([ServiceInput("svc-c", has_apm=True)], self.MON, False)
        self.assertTrue(all(r.status == NAO_VERIFICADO for r in rows))

    def test_service_without_any_telemetry(self):
        rows = build_matrix([ServiceInput("ghost", has_apm=False, has_logs=False)], self.MON, True)
        self.assertTrue(all(r.status == SEM_TELEMETRIA for r in rows))

    def test_name_substring_does_not_count_as_coverage(self):
        mon = [{"id": "m9", "name": "x", "query": "avg:trace.http.request.errors{service:svc-a-extra}>1"}]
        rows = build_matrix([ServiceInput("svc-a", has_apm=True)], mon, True)
        self.assertTrue(all(r.status != COBERTO for r in rows))

    def test_summary_and_complete_audit_gate(self):
        rows = build_matrix([ServiceInput("svc-a", has_apm=True)], self.MON, True)
        self.assertEqual(sum(summarize(rows).values()), 4)
        ok, missing = can_declare_complete_audit({"apm": COBERTO, "logs": PARCIAL, "k8s": NAO_VERIFICADO}, ["apm", "logs", "k8s"])
        self.assertFalse(ok)
        self.assertEqual(missing, ["k8s"])
        self.assertTrue(can_declare_complete_audit({"apm": COBERTO}, ["apm"])[0])
        self.assertFalse(can_declare_complete_audit({}, ["apm"])[0])


class RecommendationTests(unittest.TestCase):
    def cand(self, **o):
        base = dict(name="HPA at max for 1h", service="svc-a", metric="kubernetes_state.hpa.desired_replicas",
                    query="avg:kubernetes_state.hpa.desired_replicas{kube_deployment:svc-a}", threshold=">= max", window="1h",
                    severity="P3", justification="saturation not covered", doc_source=DOC, expected_benefit="early warning",
                    historical_samples=100)
        base.update(o)
        return MonitorCandidate(**base)

    def test_new_monitor_is_blocked_by_cost_without_contract(self):
        p = propose_monitor(self.cand(), [], ["kubernetes_state.hpa.desired_replicas"])
        self.assertEqual(p.status, BLOCKED)
        self.assertTrue(p.blocked)
        self.assertFalse(p.created)

    def test_with_valid_contract_it_is_only_a_proposal(self):
        p = propose_monitor(self.cand(), [], ["kubernetes_state.hpa.desired_replicas"], validation=OK)
        self.assertEqual((p.status, p.blocked, p.created), ("PROPOSTA", False, False))
        self.assertIn("nothing was created", " ".join(p.notes))

    def test_duplicate_detected_by_query_and_by_service_metric(self):
        ex = [{"id": "77", "query": "avg:kubernetes_state.hpa.desired_replicas{kube_deployment:svc-a} by {x} > 3"}]
        p = propose_monitor(self.cand(), ex, None, validation=OK)
        self.assertEqual(p.status, "DUPLICADA")

    def test_nonexistent_metric(self):
        p = propose_monitor(self.cand(), [], ["other.metric"], validation=OK)
        self.assertEqual(p.status, "METRICA_INEXISTENTE")

    def test_non_official_source_or_missing_fields(self):
        self.assertEqual(propose_monitor(self.cand(doc_source="https://blog.example/x"), [], None, validation=OK).status, "EVIDENCIA_INSUFICIENTE")
        self.assertEqual(propose_monitor(self.cand(justification=""), [], None, validation=OK).status, "EVIDENCIA_INSUFICIENTE")

    def test_few_samples_flags_false_positive_risk(self):
        p = propose_monitor(self.cand(historical_samples=5), [], None, validation=OK)
        self.assertIn("provisional", " ".join(p.notes))

    def dash(self, **o):
        base = dict(objective="Kubernetes capacity overview", audience="SRE", widgets=("hpa", "cpu"), queries=("q1",),
                    data_sources=("metrics",), justification="no capacity view", gap_solved="capacity", doc_source=DOC)
        base.update(o)
        return DashboardCandidate(**base)

    def test_dashboard_blocked_then_duplicate_then_proposal(self):
        self.assertEqual(propose_dashboard(self.dash(), []).status, BLOCKED)
        self.assertEqual(propose_dashboard(self.dash(), ["Kubernetes Capacity Overview"], OK).status, "DUPLICADA")
        p = propose_dashboard(self.dash(), ["Redis - Overview"], OK)
        self.assertEqual((p.status, p.created), ("PROPOSTA", False))
        self.assertEqual(propose_dashboard(self.dash(widgets=()), [], OK).status, "EVIDENCIA_INSUFICIENTE")


class ComplianceTests(unittest.TestCase):
    def test_unobserved_rules_are_insufficient_not_assumed(self):
        rows = comp.build(Catalog.load(), {})
        self.assertTrue(all(r.state == comp.INSUFICIENTE for r in rows))

    def test_demonstrated_state_requires_evidence(self):
        with self.assertRaises(ValueError):
            comp.build(Catalog.load(), {"DAIA-DOC-LOG-002": comp.Observation(comp.NAO_CONFORME, " ")})
        with self.assertRaises(ValueError):
            comp.build(Catalog.load(), {"DAIA-DOC-LOG-002": comp.Observation("MAGIC", "x")})

    def test_markdown_has_source_and_cost(self):
        rows = comp.build(Catalog.load(), {"DAIA-DOC-LOG-002": comp.Observation(comp.OPORTUNIDADE, "index main has no daily quota", "P2")})
        md = comp.to_markdown(rows)
        self.assertIn("https://docs.datadoghq.com/", md)
        self.assertIn("CUSTO_DESCONHECIDO", md)
        self.assertTrue(any(r.state == comp.OPORTUNIDADE for r in rows))


if __name__ == "__main__":
    unittest.main()
