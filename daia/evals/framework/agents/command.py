"""Generic adapter for any external agent process (JSON Lines over stdin/stdout).

Protocol (one JSON object per line):
  runner -> agent : {"type": "task", "context": {...}}
  agent  -> runner: {"type": "tool_call", "tool": "<name>", "args": {...}}
  runner -> agent : {"type": "tool_result", "result": {...}}
  agent  -> runner: {"type": "final", "output": {audit-output-v1}}

Any agent (Kiro wrapper, another LLM SDK, a script) can be evaluated this way
without the runner trusting its claims: every tool call still goes through the
sandbox and its ToolGuard.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import threading
from typing import Any, Mapping

from .base import AgentNotAvailable, ToolPort


class CommandAgent:
    def __init__(self, command: str, *, name: str = "external-command", version: str = "unknown",
                 model: str | None = None, timeout_s: int = 600, max_messages: int = 400):
        self.command = command
        self.name = name
        self.version = version
        self.model = model
        self.timeout_s = timeout_s
        self.max_messages = max_messages

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "model": self.model, "kind": "external-command",
                "config": {"command": self.command, "timeout_s": self.timeout_s, "max_messages": self.max_messages,
                           "model_declared_by_operator": self.model is not None}}

    def run(self, context: Mapping[str, Any], call_tool: ToolPort) -> dict[str, Any]:
        argv = shlex.split(self.command, posix=os.name != "nt")
        if not argv or shutil.which(argv[0]) is None:
            raise AgentNotAvailable(f"command not found: {argv[0] if argv else '<empty>'}")
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", bufsize=1)
        timer = threading.Timer(self.timeout_s, proc.kill)
        timer.start()
        try:
            proc.stdin.write(json.dumps({"type": "task", "context": dict(context)}, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            for _ in range(self.max_messages):
                line = proc.stdout.readline()
                if not line:
                    err = proc.stderr.read()[-2000:]
                    raise RuntimeError(f"agent process ended without final output (exit={proc.poll()}): {err}")
                msg = json.loads(line)
                if msg.get("type") == "final":
                    return msg.get("output")
                if msg.get("type") == "tool_call":
                    result = call_tool(str(msg.get("tool")), msg.get("args") or {})
                    proc.stdin.write(json.dumps({"type": "tool_result", "result": result}, ensure_ascii=False) + "\n")
                    proc.stdin.flush()
                else:
                    raise RuntimeError(f"unexpected message type {msg.get('type')!r}")
            raise RuntimeError("agent exceeded max_messages without final output")
        finally:
            timer.cancel()
            try:
                proc.stdin.close()
            except OSError:
                pass
            proc.kill()
            proc.wait(timeout=10)
            for stream in (proc.stdout, proc.stderr):
                if stream:
                    stream.close()
