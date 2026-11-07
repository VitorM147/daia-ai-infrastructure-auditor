"""Compatibility entry point (V4-07 first draft) — forwards to the framework runner.

The first draft scored a "golden-v1" dataset whose telemetry contained the
expected answers, so it could not measure behaviour. It was retired; see
daia/evals/history/regressions.md. Usage now:
  python -m daia.evals.run_behavioral            == runner run --agent reference
  python -m daia.evals.run_behavioral run ...    == runner run ...
"""
import sys

from daia.evals.framework.runner import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["run", "--agent", "reference"]))
