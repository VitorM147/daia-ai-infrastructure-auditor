import json
import tempfile
import unittest
from pathlib import Path

from daia.evals.behavioral import evaluate, load_dataset, quality_gate, reference_predict, score_prediction


ROOT = Path(__file__).resolve().parent


class BehavioralEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.version, cls.scenarios = load_dataset(ROOT / "golden_dataset.json")

    def test_dataset_has_twenty_synthetic_cases(self):
        self.assertEqual(self.version, "golden-v1")
        self.assertEqual(len(self.scenarios), 20)
        self.assertTrue(all(s.objective is not None for s in self.scenarios))

    def test_reference_executor_is_reproducible(self):
        first = evaluate(self.scenarios)
        second = evaluate(self.scenarios)
        self.assertEqual(first, second)

    def test_reference_result_is_measurable_but_not_claimed_as_agent_accuracy(self):
        result = evaluate(self.scenarios)
        self.assertIn("precision", result)
        self.assertIn("recall", result)
        self.assertIn("security_gate", result)

    def test_critical_security_gate_blocks_regression(self):
        scenario = next(s for s in self.scenarios if s.eval_id == "EVAL-005")
        prediction = reference_predict(scenario)
        prediction["security_safe"] = False
        score = score_prediction(scenario, prediction)
        self.assertFalse(score.security_pass)
        self.assertFalse(quality_gate({"security_gate": False, "false_positives": 0, "false_negatives": 0})[0])

    def test_partial_evidence_must_remain_incomplete(self):
        scenario = next(s for s in self.scenarios if s.eval_id == "EVAL-004")
        prediction = reference_predict(scenario)
        self.assertEqual(prediction["status"], "INCOMPLETA")
        self.assertEqual(prediction["findings"], [])

    def test_prediction_file_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "predictions.json"
            path.write_text(json.dumps({s.scenario_id: reference_predict(s) for s in self.scenarios}, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))), 20)

    def test_result_comparison_is_explicit(self):
        from daia.evals.behavioral import compare_results
        result = evaluate(self.scenarios)
        comparison = compare_results(result, result)
        self.assertEqual(comparison["precision"]["delta"], 0.0)


if __name__ == "__main__":
    unittest.main()
