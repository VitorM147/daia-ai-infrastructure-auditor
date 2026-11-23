import unittest
from datetime import datetime, timedelta, timezone

from daia.patterns.growth import detect_growth, restarts_rising
from daia.patterns.hypothesis import build_hypothesis, deploy_impact, pearson
from daia.patterns.instances import find_outliers
from daia.patterns.seasonal import evaluate, slot_of

UTC = timezone.utc
T0 = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)   # a Monday


def weekly_history(weeks=4, batch_hour=2, batch_level=900.0, base=100.0):
    pts = []
    for w in range(weeks):
        for d in range(7):
            for h in range(24):
                ts = T0 + timedelta(weeks=w, days=d, hours=h)
                v = batch_level if h == batch_hour else base
                v += (h % 3)                       # tiny deterministic jitter
                pts.append((ts, v))
    return pts


class SeasonalTests(unittest.TestCase):
    def test_batch_spike_at_usual_hour_is_not_an_anomaly(self):
        hist = weekly_history()
        ts = T0 + timedelta(weeks=5, hours=2)
        v = evaluate(905.0, ts, hist)
        self.assertEqual(v.status, "SEASONAL_NORMAL")
        self.assertEqual(v.seasonality_used, "weekday+hour")

    def test_same_value_at_unusual_hour_is_an_anomaly(self):
        hist = weekly_history()
        ts = T0 + timedelta(weeks=5, hours=14)
        self.assertEqual(evaluate(905.0, ts, hist).status, "ANOMALY")

    def test_falls_back_to_hour_of_day_when_weekday_slot_is_sparse(self):
        hist = [(T0 + timedelta(days=d, hours=10), 50.0 + d % 2) for d in range(10)]
        ts = T0 + timedelta(days=30, hours=10)
        self.assertEqual(evaluate(51.0, ts, hist).seasonality_used, "hour-of-day")

    def test_insufficient_history_is_not_calculable(self):
        v = evaluate(5.0, T0, [(T0 - timedelta(days=1), 5.0)])
        self.assertEqual(v.status, "NOT_CALCULABLE")

    def test_naive_timestamps_rejected(self):
        with self.assertRaises(ValueError):
            slot_of(datetime(2026, 1, 1))

    def test_flat_series_does_not_explode_on_tiny_change(self):
        hist = [(T0 + timedelta(days=d, hours=3), 100.0) for d in range(8)]
        self.assertEqual(evaluate(101.0, T0 + timedelta(days=20, hours=3), hist).status, "SEASONAL_NORMAL")


class InstanceTests(unittest.TestCase):
    def test_single_bad_instance_is_found(self):
        vals = {f"pod-{i}": 0.5 + i * 0.01 for i in range(7)}
        vals["pod-bad"] = 40.0
        r = find_outliers(vals)
        self.assertEqual(r.status, "OUTLIERS")
        self.assertEqual([o.instance for o in r.outliers], ["pod-bad"])

    def test_service_wide_is_not_called_partial(self):
        vals = {"a": 1.0, "b": 1.1, "c": 50.0, "d": 52.0, "e": 55.0, "f": 49.0}
        self.assertNotEqual(find_outliers(vals).status, "OUTLIERS")

    def test_uniform_and_too_few(self):
        self.assertEqual(find_outliers({f"p{i}": 1.0 + i * 0.01 for i in range(6)}).status, "UNIFORM")
        self.assertEqual(find_outliers({"a": 1, "b": 99}).status, "NOT_CALCULABLE")


class GrowthTests(unittest.TestCase):
    def test_continuous_growth(self):
        self.assertEqual(detect_growth([100, 110, 121, 133, 146, 160, 176, 193, 212]).status, "CONTINUOUS_GROWTH")

    def test_sawtooth_after_restarts_is_still_flagged(self):
        v = [100, 130, 170, 220, 60, 90, 130, 180, 40, 70, 110, 160]
        self.assertEqual(detect_growth(v).status, "SAWTOOTH_RESTARTS")

    def test_stable_and_short(self):
        self.assertEqual(detect_growth([100, 101, 99, 100, 102, 100, 99, 101, 100]).status, "STABLE")
        self.assertEqual(detect_growth([1, 2, 3]).status, "NOT_CALCULABLE")

    def test_restart_rise(self):
        self.assertTrue(restarts_rising([0, 0, 1, 0, 0, 0, 3, 4, 5]))
        self.assertFalse(restarts_rising([1, 1, 1, 1, 1, 1, 1, 1, 1]))


class HypothesisTests(unittest.TestCase):
    def pts(self, shift_after=True):
        d = T0 + timedelta(hours=10)
        out = []
        for i in range(20):
            ts = d - timedelta(hours=10) + timedelta(hours=i)
            out.append((ts, 100.0 if ts < d or not shift_after else 300.0))
        return out, d

    def test_deploy_correlation_detected_but_only_correlation(self):
        pts, d = self.pts()
        imp = deploy_impact(pts, d, timedelta(hours=8))
        self.assertEqual(imp.status, "CHANGED")
        h = build_hypothesis("latency rose after deploy", ["median 100->300"], [], [], "before/after median", [])
        self.assertEqual(h.status, "NAO_VERIFICADO")
        self.assertIn("no counter-evidence", " ".join(h.reasons))

    def test_no_change_and_sparse(self):
        pts, d = self.pts(shift_after=False)
        self.assertEqual(deploy_impact(pts, d, timedelta(hours=8)).status, "NO_CHANGE")
        self.assertEqual(deploy_impact(pts, d, timedelta(minutes=30)).status, "NOT_CALCULABLE")

    def test_complete_hypothesis_never_becomes_confirmed(self):
        h = build_hypothesis("db latency drives app latency", ["same window"], ["other service unaffected"], ["network jitter"],
                             "cross-correlation + trace ids", ["12 samples"], same_identifier_proof=True)
        self.assertEqual(h.status, "INFERIDO_FRACO")
        self.assertEqual(h.confidence, "MEDIA")
        h2 = build_hypothesis("x", ["a"], ["b"], ["c"], "m", ["l"])
        self.assertEqual((h2.status, h2.confidence), ("HIPOTESE", "BAIXA"))

    def test_pearson_guards(self):
        self.assertAlmostEqual(pearson([1, 2, 3, 4, 5, 6], [2, 4, 6, 8, 10, 12]), 1.0)
        self.assertIsNone(pearson([1, 1, 1, 1, 1, 1], [1, 2, 3, 4, 5, 6]))
        self.assertIsNone(pearson([1, 2], [1, 2]))


if __name__ == "__main__":
    unittest.main()
