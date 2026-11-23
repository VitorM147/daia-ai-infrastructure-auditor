import unittest
from datetime import datetime, timedelta, timezone

from daia.alertnoise.engine import (Alert, Finding, History, decide, dedupe_alerts, group_alerts, group_key,
                                    noise_summary, suppress_redundant_recommendations)

T = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)
EMPTY = History({})


def alert(mon="m1", svc="svc-a", prob="error_rate", sev="P2", dt=0, val=None):
    return Alert(mon, svc, prob, sev, T + timedelta(minutes=dt), val)


class DedupGroupTests(unittest.TestCase):
    def test_flapping_collapses_inside_window_only(self):
        out = dedupe_alerts([alert(dt=0), alert(dt=1), alert(dt=2), alert(dt=30)])
        self.assertEqual(len(out), 2)

    def test_different_monitors_are_kept_then_grouped_together(self):
        al = dedupe_alerts([alert("m1"), alert("m2"), alert("m3", prob="latency")])
        g = group_alerts(al)
        self.assertEqual(len(g), 2)
        self.assertEqual(g[group_key("svc-a", "error_rate")].monitors, {"m1", "m2"})

    def test_worst_severity_of_group(self):
        g = group_alerts([alert(sev="P3"), alert("m2", sev="P1")])
        self.assertEqual(list(g.values())[0].worst, "P1")


class DecisionTests(unittest.TestCase):
    def test_critical_undetected_notifies_once_then_cools_down(self):
        f = Finding("svc-a", "error_rate", "P1", detected_by_monitor=False)
        d = decide(f, None, EMPTY, T)
        self.assertEqual((d.notify, d.reason), (True, "CRITICAL_UNDETECTED"))
        h = History({group_key("svc-a", "error_rate"): (T, "P1", None, False)})
        d2 = decide(f, None, h, T + timedelta(hours=2))
        self.assertEqual((d2.notify, d2.reason), (False, "SUPPRESSED_COOLDOWN"))

    def test_already_alerted_by_monitor_is_not_repeated(self):
        f = Finding("svc-a", "error_rate", "P2", detected_by_monitor=True)
        d = decide(f, group_alerts([alert()]).popitem()[1], EMPTY, T)
        self.assertEqual((d.notify, d.reason), (False, "SUPPRESSED_ALREADY_ALERTED"))

    def test_worsening_breaks_cooldown(self):
        key = group_key("svc-a", "error_rate")
        h = History({key: (T, "P3", 10.0, False)})
        g = group_alerts([alert(sev="P1", dt=60, val=30.0)])[key]
        d = decide(Finding("svc-a", "error_rate", "P1", True), g, h, T + timedelta(hours=1))
        self.assertEqual((d.notify, d.reason), (True, "SIGNIFICANT_WORSENING"))

    def test_value_growth_without_severity_change_counts_as_worsening(self):
        key = group_key("svc-a", "error_rate")
        h = History({key: (T, "P2", 10.0, False)})
        g = group_alerts([alert(sev="P2", val=16.0)])[key]
        self.assertEqual(decide(Finding("svc-a", "error_rate", "P2", True), g, h, T + timedelta(hours=1)).reason, "SIGNIFICANT_WORSENING")
        g2 = group_alerts([alert(sev="P2", val=11.0)])[key]
        self.assertEqual(decide(Finding("svc-a", "error_rate", "P2", True), g2, h, T + timedelta(hours=1)).reason, "SUPPRESSED_COOLDOWN")

    def test_silent_failure_and_strong_hypothesis(self):
        self.assertEqual(decide(Finding("s", "latency", "P2", False, silent=True), None, EMPTY, T).reason, "SILENT_FAILURE")
        self.assertEqual(decide(Finding("s", "latency", "P3", False, hypothesis_strength="STRONG"), None, EMPTY, T).reason, "NEW_STRONG_HYPOTHESIS")
        self.assertFalse(decide(Finding("s", "latency", "P3", False, hypothesis_strength="WEAK"), None, EMPTY, T).notify)

    def test_recurrent_unresolved_after_cooldown(self):
        h = History({group_key("s", "disk"): (T - timedelta(days=3), "P2", None, False)})
        self.assertEqual(decide(Finding("s", "disk", "P2", False), None, h, T).reason, "RECURRENT_UNRESOLVED")

    def test_resolved_is_suppressed(self):
        self.assertEqual(decide(Finding("s", "disk", "P1", False, resolved=True), None, EMPTY, T).reason, "SUPPRESSED_RESOLVED")

    def test_no_external_delivery_without_explicit_channel(self):
        f = Finding("svc-a", "error_rate", "P0", False)
        self.assertFalse(decide(f, None, EMPTY, T).external_delivery)
        self.assertTrue(decide(f, None, EMPTY, T, channel_enabled=True).external_delivery)
        self.assertFalse(decide(Finding("s", "x", "P3", True), None, EMPTY, T, channel_enabled=True).external_delivery)


class SummaryTests(unittest.TestCase):
    def test_noise_reduction_is_measured_not_claimed(self):
        raw = [alert(dt=i % 3) for i in range(40)] + [alert("m9", "svc-b", "latency")]
        deduped = dedupe_alerts(raw)
        groups = group_alerts(deduped)
        decisions = [decide(Finding(g.service, g.problem, g.worst, True), g, EMPTY, T) for g in groups.values()]
        s = noise_summary(raw, deduped, groups, decisions)
        self.assertEqual(s["raw_alerts"], 41)
        self.assertLess(s["after_dedup"], s["raw_alerts"])
        self.assertEqual(s["external_deliveries"], 0)
        self.assertGreater(s["reduction_pct"], 90)

    def test_redundant_recommendations(self):
        recs = [{"service": "A", "action": "review quota"}, {"service": "a", "action": "Review quota"}, {"service": "a", "action": "other"}]
        self.assertEqual(len(suppress_redundant_recommendations(recs)), 2)


if __name__ == "__main__":
    unittest.main()
