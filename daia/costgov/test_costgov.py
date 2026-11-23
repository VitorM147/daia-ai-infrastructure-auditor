import unittest

from daia.costgov.classifier import (BLOCKED, PAID, POTENTIAL, UNKNOWN, ZERO, ContractValidation, CostProposal,
                                     classify, summarize)

OK = ContractValidation("fin-ops-approver", "2026-11-01", "ticket-REF-1", "monitors included in plan")


class CostTests(unittest.TestCase):
    def test_offline_analysis_is_zero_and_not_blocked(self):
        d = classify(CostProposal("trend report", "offline_analysis"))
        self.assertEqual((d.status, d.blocked, d.eligible_for_future_implementation), (ZERO, False, True))
        self.assertTrue(d.requires_human_approval)

    def test_new_monitor_without_contract_is_blocked(self):
        d = classify(CostProposal("hpa monitor", "monitor", creates_or_enables_datadog_resource=True))
        self.assertEqual((d.status, d.blocked, d.label), (UNKNOWN, True, BLOCKED))
        self.assertFalse(d.eligible_for_future_implementation)

    def test_new_monitor_with_valid_contract_is_eligible_but_still_needs_approval(self):
        d = classify(CostProposal("hpa monitor", "monitor", creates_or_enables_datadog_resource=True, validation=OK))
        self.assertEqual(d.status, ZERO)
        self.assertTrue(d.eligible_for_future_implementation)
        self.assertTrue(d.requires_human_approval)

    def test_incomplete_validation_does_not_count(self):
        bad = ContractValidation("x", "not-a-date", "ref", "scope")
        d = classify(CostProposal("m", "monitor", creates_or_enables_datadog_resource=True, validation=bad))
        self.assertEqual(d.status, UNKNOWN)
        self.assertIn("incomplete", " ".join(d.reasons))
        blank = ContractValidation("", "2026-11-01", "ref", "scope")
        self.assertFalse(blank.is_valid())

    def test_paid_products_always_blocked_even_with_contract(self):
        for prod in ("sensitive_data_scanner", "audit_trail", "synthetics", "flex_logs"):
            d = classify(CostProposal("x", "monitor", products_required=(prod,), validation=OK))
            self.assertEqual((d.status, d.blocked), (PAID, True), prod)

    def test_log_based_and_custom_metrics_never_eligible(self):
        for kind in ("log_based_metric", "custom_metric"):
            d = classify(CostProposal("x", kind, creates_or_enables_datadog_resource=True, validation=OK))
            self.assertEqual((d.status, d.blocked, d.eligible_for_future_implementation), (POTENTIAL, True, False), kind)

    def test_new_queries_without_reuse_are_potential_cost(self):
        d = classify(CostProposal("deep dive", "analysis_with_queries", new_datadog_queries=40))
        self.assertEqual((d.status, d.blocked), (POTENTIAL, True))

    def test_reuse_of_existing_metrics_needs_validation_to_be_zero(self):
        d = classify(CostProposal("read existing", "analysis_with_queries", reuses_existing_metrics_only=True))
        self.assertEqual((d.status, d.blocked), (POTENTIAL, True))
        d = classify(CostProposal("read existing", "analysis_with_queries", reuses_existing_metrics_only=True, validation=OK))
        self.assertEqual((d.status, d.blocked), (ZERO, False))

    def test_unknown_defaults_to_blocked(self):
        d = classify(CostProposal("???", "something_new"))
        self.assertEqual((d.status, d.blocked), (UNKNOWN, True))

    def test_only_zero_is_ever_eligible(self):
        ds = [classify(CostProposal("a", "offline_analysis")), classify(CostProposal("b", "monitor", creates_or_enables_datadog_resource=True)),
              classify(CostProposal("c", "monitor", products_required=("rum",)))]
        self.assertEqual([d.eligible_for_future_implementation for d in ds], [True, False, False])
        self.assertEqual(summarize(ds), {ZERO: 1, UNKNOWN: 1, PAID: 1})


if __name__ == "__main__":
    unittest.main()
