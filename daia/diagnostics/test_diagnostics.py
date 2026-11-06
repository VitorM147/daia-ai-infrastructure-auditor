import json
import unittest
from datetime import timezone
from pathlib import Path

from daia.diagnostics.baseline import build_baseline, compare_with_baseline
from daia.diagnostics.diagnostics import assess_diagnostic
from daia.diagnostics.metrics import MetricCalculationError, calculate_percentage
from daia.diagnostics.models import EvidencePackage, MetricPoint, Provenance, utc
from daia.diagnostics.regressions import evaluate_synthetic_case


class DiagnosticAccuracyTests(unittest.TestCase):
    def point(self, value, hour, metric="requests", unit="count", source_kind="metric"):
        return MetricPoint(metric, utc(2026, 1, 5, hour), value, unit, "service-a", "service-a", "prod", (), "synthetic", source_kind)

    def package(self, points):
        return EvidencePackage(
            "evidence-v1", "synthetic-package", Provenance(
                "synthetic", "metric", "test-1", "query-hash", utc(2026, 1, 5, 12),
                utc(2026, 1, 5), utc(2026, 1, 6), utc(2026, 1, 5), utc(2026, 1, 6)
            ), tuple(points)
        )

    def test_percentage_uses_distinct_numerator_and_denominator_metrics(self):
        nums = [self.point(10, 1, "errors")]
        dens = [self.point(100, 1, "requests")]
        self.assertEqual(calculate_percentage(nums, dens), 10.0)

    def test_percentage_rejects_mismatched_resource(self):
        nums = [self.point(10, 1, "errors")]
        dens = [MetricPoint("requests", utc(2026, 1, 5, 1), 100, "count", "service-b", "service-b", "prod", (), "synthetic")]
        with self.assertRaises(MetricCalculationError):
            calculate_percentage(nums, dens)

    def test_sampled_spans_are_not_silently_mixed_with_metrics(self):
        nums = [self.point(10, 1, "errors", source_kind="span")]
        dens = [self.point(100, 1, "requests", source_kind="metric")]
        with self.assertRaises(MetricCalculationError):
            calculate_percentage(nums, dens)

    def test_baseline_rejects_insufficient_coverage(self):
        result = build_baseline([self.point(10, 1)], start_utc=utc(2026, 1, 5), end_utc=utc(2026, 1, 6), expected_points=4)
        self.assertFalse(result.calculable)
        self.assertEqual(compare_with_baseline(20, result, threshold=.2)["status"], "NOT_CALCULABLE")

    def test_baseline_uses_comparable_median(self):
        points = [self.point(10, i) for i in range(1, 5)]
        result = build_baseline(points, start_utc=utc(2026, 1, 5), end_utc=utc(2026, 1, 6), expected_points=4)
        self.assertEqual(result.value, 10)
        self.assertEqual(compare_with_baseline(13, result, threshold=.2)["status"], "REGRESSION")

    def test_partial_evidence_cannot_close_diagnostic(self):
        assessment = assess_diagnostic(
            packages=[self.package([self.point(10, 1)])], claim="job failure",
            evidence_for=["3 samples"], evidence_against=[], alternatives=["historical failure"],
            coverage_sufficient=False, causal_identifiers_match=False, current_state_confirmed=False)
        self.assertEqual(assessment.status, "INCOMPLETA")
        self.assertNotEqual(assessment.classification, "CAUSA_CONFIRMADA")

    def test_complete_correlation_still_is_probable_not_confirmed(self):
        assessment = assess_diagnostic(
            packages=[self.package([self.point(10, 1)])], claim="payment error",
            evidence_for=["same correlation id"], evidence_against=["legitimate rejection possible"],
            alternatives=["payload validation"], coverage_sufficient=True,
            causal_identifiers_match=True, current_state_confirmed=True)
        self.assertEqual(assessment.classification, "CAUSA_PROVÁVEL")

    def test_six_regression_cases(self):
        cases = {
            "DAIA-001": ({"error_rate_source": "span"}, "INCOMPLETA"),
            "DAIA-006": ({"aggregation": "weighted", "raw_series": True}, "INCOMPLETA"),
            "DAIA-007": ({"max_replicas": 1}, "CONFIGURAÇÃO"),
            "DAIA-030": ({"oom_origin": "identity-api"}, "INCOMPLETA"),
            "DAIA-038": ({"baseline_available": False}, "INCOMPLETA"),
            "DAIA-040": ({"read_points": 80, "total_points": 4158}, "INCOMPLETA"),
        }
        for case_id, (facts, classification) in cases.items():
            with self.subTest(case_id=case_id):
                finding = evaluate_synthetic_case(case_id, facts)
                if case_id == "DAIA-007":
                    self.assertEqual(finding.classification, classification)
                else:
                    self.assertEqual(finding.status, "INCOMPLETA")

    def test_provenance_requires_utc_and_current_window(self):
        package = self.package([self.point(10, 1)])
        package.validate()
        self.assertEqual(package.provenance.effective_start_utc.tzinfo, timezone.utc)


if __name__ == "__main__":
    unittest.main()
