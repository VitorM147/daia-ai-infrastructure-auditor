import unittest

from daia.diagnostics.models import MetricPoint, utc
from daia.proactive.risk import classify_risk
from daia.proactive.trend import analyze_trend, estimate_exhaustion


class ProactiveTests(unittest.TestCase):
    def points(self, values, unit="percent"):
        return [MetricPoint("capacity", utc(2026, 1, 5, i), value, unit, "resource-a", "svc", "prod", (), "synthetic") for i, value in enumerate(values)]

    def test_upward_trend_is_future_risk_below_threshold(self):
        trend = analyze_trend(self.points([40, 45, 50, 55, 60]), expected_points=5)
        risk = classify_risk(
            risk_id="cpu-growth", current_value=60, threshold=80, trend=trend,
            telemetry_quality="SUFFICIENT", evidence=["five ordered points"],
            counter_evidence=["below threshold"], accelerators=["load growth"],
            mitigators=["scaling headroom"], preventive_actions=["review capacity"],
            follow_up_indicators=["cpu percent"],
        )
        self.assertEqual(risk.state, "RISCO_FUTURO")
        self.assertNotEqual(risk.state, "PROBLEMA_ATUAL")

    def test_threshold_reached_is_current_problem_not_prediction(self):
        trend = analyze_trend(self.points([70, 75, 80, 85, 90]), expected_points=5)
        risk = classify_risk(
            risk_id="disk", current_value=90, threshold=80, trend=trend,
            telemetry_quality="SUFFICIENT", evidence=["current value"],
            counter_evidence=[], accelerators=[], mitigators=[], preventive_actions=[], follow_up_indicators=[],
        )
        self.assertEqual(risk.state, "PROBLEMA_ATUAL")

    def test_insufficient_points_do_not_create_prediction(self):
        trend = analyze_trend(self.points([40, 50, 60]), min_points=5, expected_points=5)
        estimate = estimate_exhaustion(self.points([40, 50, 60]), threshold=80, min_points=5, expected_points=5)
        self.assertEqual(trend.status, "NOT_CALCULABLE")
        self.assertEqual(estimate.status, "NOT_CALCULABLE")

    def test_partial_coverage_is_not_a_future_risk(self):
        trend = analyze_trend(self.points([40, 45, 50, 55, 60]), expected_points=10)
        risk = classify_risk(
            risk_id="queue", current_value=60, threshold=80, trend=trend,
            telemetry_quality="INSUFFICIENT", evidence=["partial series"],
            counter_evidence=[], accelerators=[], mitigators=[], preventive_actions=[], follow_up_indicators=[],
        )
        self.assertEqual(risk.state, "NÃO_VERIFICADO")

    def test_exhaustion_includes_interval(self):
        estimate = estimate_exhaustion(self.points([40, 45, 50, 55, 60]), threshold=80, expected_points=5)
        self.assertEqual(estimate.status, "ESTIMATE")
        self.assertIsNotNone(estimate.lower_seconds)
        self.assertIsNotNone(estimate.upper_seconds)
        self.assertLessEqual(estimate.lower_seconds, estimate.seconds_to_threshold)
        self.assertGreaterEqual(estimate.upper_seconds, estimate.seconds_to_threshold)

    def test_duplicate_timestamps_are_rejected(self):
        points = self.points([40, 50, 60, 70, 80])
        points[1] = MetricPoint("capacity", points[0].timestamp_utc, 50, "percent", "resource-a", "svc", "prod", (), "synthetic")
        with self.assertRaises(ValueError):
            analyze_trend(points)

    def test_zero_start_does_not_invent_relative_change(self):
        trend = analyze_trend(self.points([0, 1, 2, 3, 4]), expected_points=5)
        self.assertIsNone(trend.relative_change)


if __name__ == "__main__":
    unittest.main()
