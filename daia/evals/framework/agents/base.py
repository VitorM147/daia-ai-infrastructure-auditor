"""Agent-under-test protocol.

An agent receives the task context (never the expected answer) and a tool port.
It must return an audit-output-v1 object (see ``framework/output.py``).
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol

ToolPort = Callable[[str, Mapping[str, Any]], dict[str, Any]]


class AgentNotAvailable(RuntimeError):
    """Raised when an agent cannot run (no credentials, no binary, no network).

    The runner records the affected scenarios as NOT_EXECUTED, never as PASS.
    """


class Agent(Protocol):
    name: str
    version: str

    def describe(self) -> dict[str, Any]:
        """Return name, version, model and configuration (recorded per run)."""

    def run(self, context: Mapping[str, Any], call_tool: ToolPort) -> dict[str, Any]:
        """Investigate using only ``call_tool`` and return audit-output-v1."""
