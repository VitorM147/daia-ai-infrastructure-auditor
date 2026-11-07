"""Example external agent speaking the JSON Lines protocol.

It wraps the reference agent so the protocol can be tested end to end:
  python -m daia.evals.framework.runner run --agent command \
      --agent-cmd "python -m daia.evals.framework.agents.jsonl_reference_example"
Use it as a template for wrapping a real LLM agent.
"""
from __future__ import annotations

import json
import sys

from daia.evals.framework.agents.reference import ReferenceAgent


def main() -> None:
    task = json.loads(sys.stdin.readline())

    def call_tool(tool, args):
        sys.stdout.write(json.dumps({"type": "tool_call", "tool": tool, "args": dict(args)}, ensure_ascii=False) + "\n")
        sys.stdout.flush()
        return json.loads(sys.stdin.readline())["result"]

    output = ReferenceAgent().run(task["context"], call_tool)
    sys.stdout.write(json.dumps({"type": "final", "output": output}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
