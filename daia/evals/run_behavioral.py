"""CLI for reproducible synthetic behavioral evaluation.

Usage: python -m daia.evals.run_behavioral
A real agent can be scored by passing a JSON prediction file with one object
per scenario to --predictions. No network or credentials are used.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

from .behavioral import compare_results, evaluate, load_dataset, quality_gate, score_prediction


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default=str(Path(__file__).with_name("golden_dataset.json")))
    parser.add_argument("--predictions", help="JSON object keyed by scenario_id, produced by an agent adapter")
    parser.add_argument("--output", default=str(Path(__file__).with_name("behavioral-last-run.json")))
    parser.add_argument("--previous", help="previous result JSON for metric comparison")
    args = parser.parse_args()
    version, scenarios = load_dataset(args.dataset)
    metadata = {"dataset_version": version, "agent_version": "daia-v4-eval-framework-1", "model": "reference-baseline" if not args.predictions else "external-agent-adapter", "python": platform.python_version(), "timestamp_utc": datetime.now(timezone.utc).isoformat()}
    if args.predictions:
        predictions = json.loads(Path(args.predictions).read_text(encoding="utf-8"))
        scores = [score_prediction(s, predictions[s.scenario_id]) for s in scenarios]
        result = {"cases": len(scores), "passed": sum(s.passed for s in scores), "failed": sum(not s.passed for s in scores), "precision": sum(s.precision for s in scores) / len(scores), "recall": sum(s.recall for s in scores) / len(scores), "false_positives": sum(s.false_positives for s in scores), "false_negatives": sum(s.false_negatives for s in scores), "severity_accuracy": sum(s.severity_match for s in scores) / len(scores), "cause_accuracy": sum(s.cause_match for s in scores) / len(scores), "uncertainty_accuracy": sum(s.uncertainty_match for s in scores) / len(scores), "security_gate": all(s.security_pass for s in scores), "scores": [s.__dict__ for s in scores]}
    else:
        result = evaluate(scenarios)
    passed, failures = quality_gate(result)
    output = {"metadata": metadata, "result": result, "gate": {"passed": passed, "failures": failures}}
    if args.previous:
        previous_data = json.loads(Path(args.previous).read_text(encoding="utf-8-sig"))
        previous_result = previous_data.get("result", previous_data)
        output["comparison"] = compare_results(previous_result, result)
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
