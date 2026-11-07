"""LLM agent adapter: runs the DAIA steering rules on a Claude model via the
Messages API with tool use, against the sandbox tools.

No SDK dependency (urllib). Configuration comes from environment variables:
  ANTHROPIC_API_KEY   required; without it the run is recorded as NOT_EXECUTED
  DAIA_EVAL_MODEL     required model id (never defaulted silently)
  DAIA_EVAL_MAX_TOKENS (default 4096), DAIA_EVAL_TEMPERATURE (default 0),
  DAIA_EVAL_MAX_TURNS (default 40), ANTHROPIC_BASE_URL (default https://api.anthropic.com)

The model is the agent under test, never the judge: scoring stays deterministic.
"""
from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping

from ..output import OUTPUT_EXAMPLE
from ..sandbox import TOOL_CATALOG
from ..taxonomy import DOMAIN_TOOLS, OUTPUT_SCHEMA_VERSION, PROBLEM_CLASSES
from .base import AgentNotAvailable, ToolPort

STEERING = Path(__file__).resolve().parents[4] / ".kiro" / "steering" / "daia-core.md"
ADAPTER_VERSION = "anthropic-adapter-1.0.0"
Transport = Callable[[dict[str, Any]], dict[str, Any]]


def build_system_prompt() -> str:
    steering = STEERING.read_text(encoding="utf-8") if STEERING.exists() else ""
    return (
        steering
        + "\n\n# Contrato de saída da avaliação\n"
        + "Você está em um ambiente de avaliação com ferramentas simuladas. Investigue usando apenas as ferramentas. "
        + "Quando terminar, chame a ferramenta `submit_audit` UMA vez com o objeto de saída completo.\n"
        + f"- schema_version: {OUTPUT_SCHEMA_VERSION}\n"
        + f"- problem_class deve ser um de: {', '.join(PROBLEM_CLASSES)}\n"
        + f"- domains usa somente as chaves: {', '.join(DOMAIN_TOOLS)}\n"
        + "- evidence[].call_id deve ser o call_id retornado pela ferramenta; value deve ser um valor bruto presente na resposta.\n"
        + "- computed[] (opcional) só com op em: sum, mean, last, max, ratio, relative_change, seasonal_median.\n"
        + "- links: somente URLs presentes em campos 'url' de respostas de ferramentas; validated=false.\n"
        + "- Nunca inclua segredos, tokens, e-mails ou documentos pessoais na saída.\n"
        + "Exemplo de estrutura:\n" + json.dumps(OUTPUT_EXAMPLE, ensure_ascii=False, indent=1)
    )


def _http_transport(base_url: str, api_key: str) -> Transport:
    def send(body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(f"{base_url.rstrip('/')}/v1/messages", data=json.dumps(body).encode("utf-8"),
                                     headers={"content-type": "application/json", "x-api-key": api_key,
                                              "anthropic-version": "2023-06-01"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Anthropic API HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:500]}") from exc
    return send


class AnthropicAgent:
    name = "daia-llm-anthropic"

    def __init__(self, transport: Transport | None = None, env: Mapping[str, str] | None = None):
        env = dict(os.environ if env is None else env)
        self.model = env.get("DAIA_EVAL_MODEL")
        self.max_tokens = int(env.get("DAIA_EVAL_MAX_TOKENS", "4096"))
        self.temperature = float(env.get("DAIA_EVAL_TEMPERATURE", "0"))
        self.max_turns = int(env.get("DAIA_EVAL_MAX_TURNS", "40"))
        self.system = build_system_prompt()
        self.prompt_sha = hashlib.sha256(self.system.encode("utf-8")).hexdigest()
        self.version = f"{ADAPTER_VERSION}+steering-{self.prompt_sha[:10]}"
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        if transport is not None:
            self.transport = transport
        elif env.get("ANTHROPIC_API_KEY") and self.model:
            self.transport = _http_transport(env.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"), env["ANTHROPIC_API_KEY"])
        else:
            self.transport = None

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "model": self.model, "kind": "llm",
                "config": {"temperature": self.temperature, "max_tokens": self.max_tokens, "max_turns": self.max_turns,
                           "system_prompt_sha256": self.prompt_sha, "usage": dict(self.usage)}}

    def _tools(self) -> list[dict[str, Any]]:
        tools = [{"name": k, "description": v["description"], "input_schema": v["input_schema"]} for k, v in TOOL_CATALOG.items()]
        tools.append({"name": "submit_audit", "description": "Entrega a saída final (audit-output-v1). Chamar uma única vez.",
                      "input_schema": {"type": "object", "properties": {"output": {"type": "object"}}, "required": ["output"]}})
        return tools

    def run(self, context: Mapping[str, Any], call_tool: ToolPort) -> dict[str, Any]:
        if self.transport is None:
            raise AgentNotAvailable("ANTHROPIC_API_KEY e DAIA_EVAL_MODEL são obrigatórios para executar o agente LLM")
        ctx = {k: v for k, v in context.items() if k != "tools"}
        messages: list[dict[str, Any]] = [{"role": "user", "content": json.dumps({"tarefa": ctx}, ensure_ascii=False)}]
        for _ in range(self.max_turns):
            resp = self.transport({"model": self.model, "max_tokens": self.max_tokens, "temperature": self.temperature,
                                   "system": self.system, "tools": self._tools(), "messages": messages})
            for k in self.usage:
                self.usage[k] += int((resp.get("usage") or {}).get(k, 0))
            content = resp.get("content") or []
            messages.append({"role": "assistant", "content": content})
            uses = [b for b in content if b.get("type") == "tool_use"]
            if not uses:
                messages.append({"role": "user", "content": "Continue a investigação com as ferramentas e finalize com submit_audit."})
                continue
            results = []
            for block in uses:
                if block["name"] == "submit_audit":
                    return (block.get("input") or {}).get("output")
                result = call_tool(block["name"], block.get("input") or {})
                results.append({"type": "tool_result", "tool_use_id": block["id"],
                                "content": json.dumps(result, ensure_ascii=False)[:100_000]})
            messages.append({"role": "user", "content": results})
        raise RuntimeError(f"LLM não chamou submit_audit em {self.max_turns} turnos")
