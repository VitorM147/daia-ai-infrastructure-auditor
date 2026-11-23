import unittest

from daia.logintel.indexes import exclusion_candidates, review_indexes
from daia.logintel.patterns import classify_origin, dedupe, pattern_stats, template
from daia.logintel.sensitive import cpf_ok, luhn_ok, mask, mask_all
from daia.logintel.usage import (analyze_services, classify_series, ingested_vs_indexed, project_month, top_services)


class SensitiveTests(unittest.TestCase):
    def test_masks_secrets_and_pii_without_leaking_values(self):
        fake_aws = "AKIA" + "ABCDEFGHIJKLMNOP"
        text = f"password=Sup3rS3cret user=a.b@example.com key={fake_aws} Authorization: Bearer abcdefghijklmnop123456"
        r = mask(text)
        for leaked in ("Sup3rS3cret", "a.b@example.com", fake_aws, "abcdefghijklmnop123456"):
            self.assertNotIn(leaked, r.text)
        self.assertTrue({"secret_assignment", "email", "aws_access_key"} <= set(r.findings))

    def test_card_requires_luhn_and_cpf_requires_checksum(self):
        self.assertTrue(luhn_ok("4111111111111111"))
        self.assertIn("payment_card", mask("pay 4111 1111 1111 1111 ok").findings)
        self.assertNotIn("payment_card", mask("order id 1234567890123456").findings)
        self.assertTrue(cpf_ok("52998224725"))
        self.assertIn("cpf", mask("cliente 52998224725").findings)
        self.assertNotIn("cpf", mask("pedido 12345678901").findings)

    def test_jwt_and_private_key(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdEFGH1234"
        r = mask(f"token {jwt} -----BEGIN RSA PRIVATE KEY-----")
        self.assertNotIn(jwt, r.text)
        self.assertTrue({"jwt", "private_key"} <= set(r.findings))

    def test_clean_text_unchanged(self):
        r = mask("Erro na integracao com a VTEX status=400")
        self.assertFalse(r.has_sensitive)
        self.assertEqual(mask_all(["a", "b"])[1], {})


class PatternTests(unittest.TestCase):
    def test_template_normalises_variable_parts(self):
        a = template("VTEX failure orderFormId=64fed3ef92214dd0a40d07691b68ed23 status=400")
        b = template("VTEX failure orderFormId=a34e1f580ecf46cf9e3a5ce1d68262ba status=400")
        self.assertEqual(a, b)

    def test_dedupe_by_trace_span_and_empty_messages(self):
        logs = [{"trace_id": "t1", "span_id": "s1", "message": ""}, {"trace_id": "t1", "span_id": "s1", "message": ""},
                {"trace_id": "t2", "span_id": "s2", "message": "x"}, {"message": "no ids"}, {"message": "no ids"}]
        d = dedupe(logs)
        self.assertEqual((d.raw, d.unique, d.duplicates, d.empty_messages), (5, 4, 1, 2))
        self.assertIn("without trace/span id", d.caveat)

    def test_origin_classification(self):
        self.assertEqual(classify_origin("kubeturbo"), "infrastructure")
        self.assertEqual(classify_origin("kube-proxy"), "infrastructure")
        self.assertEqual(classify_origin("undefined"), "unknown")
        self.assertEqual(classify_origin("dpsp-dca-plans"), "application")

    def test_stats_rank_and_protect_errors(self):
        logs = [{"service": "svc", "status": "info", "message": f"cache refreshed in {i} ms"} for i in range(8)]
        logs += [{"service": "svc", "status": "error", "message": "payment declined"} for _ in range(2)]
        st = pattern_stats(logs)
        self.assertEqual(st[0].count, 8)
        self.assertFalse(st[0].protected)
        self.assertTrue(any(s.protected for s in st))


class UsageTests(unittest.TestCase):
    def test_growth_drop_stopped_stable(self):
        self.assertEqual(classify_series([10, 11, 9, 10, 10, 11, 30, 32, 31])[0], "GROWTH")
        self.assertEqual(classify_series([100, 98, 102, 100, 99, 101, 10, 12, 11])[0], "DROP")
        self.assertEqual(classify_series([50, 52, 48, 50, 51, 49, 0, 0, 0])[0], "STOPPED")
        self.assertEqual(classify_series([10, 11, 9, 10, 10, 11, 10, 11, 10])[0], "STABLE")

    def test_short_series_not_calculable(self):
        self.assertEqual(classify_series([1, 2, 3])[0], "NOT_CALCULABLE")

    def test_ranking_and_share(self):
        pts = [{"service": "a", "value": 90}, {"service": "b", "value": 10}]
        top = top_services(pts)
        self.assertEqual(top[0][0], "a")
        self.assertAlmostEqual(top[0][2], 0.9)
        res = analyze_services({"a": [1] * 9, "b": [1] * 8 + [9]})
        self.assertEqual(len(res), 2)

    def test_indexed_cannot_exceed_ingested(self):
        self.assertEqual(ingested_vs_indexed(100, 150)["status"], "INCONSISTENT")
        self.assertEqual(ingested_vs_indexed(0, 0)["status"], "NOT_CALCULABLE")
        self.assertAlmostEqual(ingested_vs_indexed(100, 80)["excluded_ratio"], 0.2)

    def test_projection_has_range_and_is_not_billing(self):
        p = project_month(430.0, 6, 2026, 11, [3.7, 3.5, 3.9], 500.0)
        self.assertEqual(p["status"], "ESTIMATE")
        self.assertLess(p["projected_low"], p["projected_mid"])
        self.assertLess(p["projected_mid"], p["projected_high"])
        self.assertIn("nao e valor de faturamento", p["disclaimer"])
        self.assertEqual(project_month(1, 6, 2026, 11, [1, 2], 500)["status"], "NOT_CALCULABLE")
        self.assertEqual(project_month(430, 6, 2026, 11, [3, 3, 3], None)["contract_status"], "CONTRATO_NAO_INFORMADO")


class IndexTests(unittest.TestCase):
    def test_quota_findings_are_recommend_only(self):
        f = review_indexes([{"name": "main", "daily_quota": None, "retention_days": 15},
                            {"name": "a", "daily_quota": 100, "indexed_24h": 85, "retention_days": 7},
                            {"name": "b", "daily_quota": 100, "indexed_24h": 120, "retention_days": 7},
                            {"name": "c", "retention_days": 7}])
        kinds = {(x.index, x.kind) for x in f}
        self.assertEqual(kinds, {("main", "NO_DAILY_QUOTA"), ("a", "QUOTA_NEAR"), ("b", "QUOTA_REACHED"), ("c", "DATA_MISSING")})
        self.assertTrue(all(x.action == "RECOMMEND_ONLY" for x in f))
        self.assertTrue(all(x.cost_status != "CUSTO_ZERO_CONFIRMADO" for x in f))

    def test_missing_retention_is_unverified_not_defaulted(self):
        f = review_indexes([{"name": "x", "daily_quota": 10, "indexed_24h": 1}])
        self.assertEqual(f[0].kind, "RETENTION_UNKNOWN")
        self.assertEqual(f[0].verification, "NAO_VERIFICADO")

    def test_unqueried_depends_on_billable_source(self):
        f = review_indexes([{"name": "old", "daily_quota": 10, "indexed_24h": 1, "retention_days": 30, "queries_30d": 0}])
        u = [x for x in f if x.kind == "UNQUERIED_CANDIDATE"][0]
        self.assertEqual(u.cost_status, "RECURSO_PAGO")

    def test_exclusion_never_targets_errors_or_security(self):
        logs = [{"service": "app", "status": "info", "message": f"heartbeat ok {i}"} for i in range(60)]
        logs += [{"service": "app", "status": "error", "message": "payment declined"} for _ in range(30)]
        logs += [{"service": "app", "status": "info", "message": "login denied for user"} for _ in range(10)]
        logs += [{"service": "kubeturbo", "status": "error", "message": "Node is not ready"} for _ in range(5)]
        cands = exclusion_candidates(pattern_stats(logs))
        decisions = {c.template: c.decision for c in cands}
        self.assertEqual(decisions["heartbeat ok <N>"], "CANDIDATE")
        self.assertEqual(decisions["payment declined"], "BLOCKED_PROTECTED")
        self.assertEqual(decisions["login denied for user"], "BLOCKED_PROTECTED")
        self.assertTrue(all(c.action == "RECOMMEND_ONLY" for c in cands))

    def test_infra_noise_is_not_excluded_directly(self):
        logs = [{"service": "kubeturbo", "status": "info", "message": f"collected {i}"} for i in range(50)]
        c = exclusion_candidates(pattern_stats(logs))[0]
        self.assertEqual(c.decision, "BLOCKED_INFRA_TELEMETRY_REVIEW")


if __name__ == "__main__":
    unittest.main()
