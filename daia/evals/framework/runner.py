"""Reproducible executor for DAIA behavioral evals.

Examples:
  python -m daia.evals.framework.runner validate-dataset
  python -m daia.evals.framework.runner run --agent reference
  python -m daia.evals.framework.runner run --agent reference --record          # salva em history/
  python -m daia.evals.framework.runner run --agent anthropic --repeat 3 --record
  python -m daia.evals.framework.runner run --agent command --agent-cmd "python my_agent.py" --agent-name x --agent-version 1.2
  python -m daia.evals.framework.runner compare history/runs/A/result.json history/runs/B/result.json
  python -m daia.evals.framework.runner review-apply history/runs/<id> reviews/<id>.json

Exit codes: 0 PASS · 1 BLOCKED · 2 PASS_PENDING_HUMAN_REVIEW · 3 NOT_EXECUTED/INCOMPLETE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agents.base import AgentNotAvailable
from .dataset import coverage_summary, load_dataset
from .gates import compare_runs, evaluate_gates, load_gates
from .history import HISTORY_DIR, append_regressions, apply_reviews, latest_run, run_dir, save_run
from .metrics import aggregate, stability
from .report import render
from .sandbox import POLICY_PATH, Sandbox
from .scoring import score_scenario
from .taxonomy import DIMENSIONS, NOT_EXECUTED, SCORER_VERSION

LIMITATIONS = [
    "Todos os cenários são sintéticos; nenhum incidente histórico corporativo sanitizado foi incluído ainda (campo provenance.validated_by pendente).",
    "O dataset e o agente de referência foram escritos pela mesma equipe: os números do agente de referência validam a suíte, não medem a precisão de um LLM em produção.",
    "Ferramentas são simuladas: a suíte não prova integração real com Datadog, Jira ou MCP.",
    "A utilidade dos procedimentos humanos (D13) só é aprovada após revisão humana; enquanto pendente, não conta como PASS.",
    "Amostras pequenas (n por dimensão) produzem intervalos de confiança largos; não extrapolar taxas para o ambiente real.",
]


def make_agent(args: argparse.Namespace):
    if args.agent == "reference":
        from .agents.reference import ReferenceAgent
        return ReferenceAgent()
    if args.agent == "naive":
        from .agents.naive import NaiveAgent
        return NaiveAgent()
    if args.agent == "orchestrator":
        from .agents.orchestrator_agent import OrchestratorAgent
        return OrchestratorAgent()
    if args.agent == "anthropic":
        from .agents.anthropic_llm import AnthropicAgent
        return AnthropicAgent()
    if args.agent == "command":
        from .agents.command import CommandAgent
        if not args.agent_cmd:
            raise SystemExit("--agent-cmd é obrigatório para --agent command")
        return CommandAgent(args.agent_cmd, name=args.agent_name or "external-command",
                            version=args.agent_version or "unknown", model=args.agent_model)
    raise SystemExit(f"agente desconhecido: {args.agent}")


def _git_commit() -> str | None:
    try:
        root = Path(__file__).resolve().parents[3]
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def _git_dirty() -> bool | None:
    try:
        root = Path(__file__).resolve().parents[3]
        out = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", "daia", ".kiro"],
                             capture_output=True, text=True, timeout=10)
        lines = [l for l in out.stdout.splitlines() if "daia/evals/history/" not in l]
        return bool(lines) if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _not_executed(scenario: dict[str, Any], reason: str, repeat: int) -> dict[str, Any]:
    return {"scenario_id": scenario["scenario_id"], "eval_ids": scenario["eval_ids"], "category": scenario["category"],
            "healthy": scenario.get("healthy", False), "outcome": NOT_EXECUTED, "repeat": repeat, "error": reason,
            "schema_errors": [], "counts": {"tp": 0, "fp": 0, "fn": 0, "required": 0, "tp_required": 0, "trap_fp": 0,
                                            "duplicates": 0, "tool_calls": 0, "jira_created": 0},
            "critical_violations": [], "allowed_response": scenario["expected"]["allowed_response"],
            "dimensions": {d: {"dimension": d, "title": v["title"], "status": NOT_EXECUTED, "details": [reason],
                               "critical_violation": False, "metrics": {}} for d, v in DIMENSIONS.items()}}


def execute(agent, scenarios: list[dict[str, Any]], repeat: int = 1) -> tuple[list[dict], list[dict], list[list[dict]]]:
    all_scores, transcripts, per_repeat = [], [], []
    unavailable: str | None = None
    for r in range(repeat):
        rep_scores = []
        for scenario in scenarios:
            if unavailable:
                rep_scores.append(_not_executed(scenario, unavailable, r))
                continue
            sandbox = Sandbox(scenario)
            try:
                output = agent.run(sandbox.context.as_dict(), sandbox.call)
                score = score_scenario(scenario, output, sandbox)
            except AgentNotAvailable as exc:
                unavailable = f"agente indisponível: {exc}"
                rep_scores.append(_not_executed(scenario, unavailable, r))
                continue
            except Exception as exc:  # agent crash is a measured failure, not a pass
                output = None
                score = score_scenario(scenario, None, sandbox)
                score["outcome"] = "ERROR"
                score["error"] = f"{type(exc).__name__}: {exc}"[:500]
                score["traceback"] = traceback.format_exc()[-2000:]
            score["repeat"] = r
            score["allowed_response"] = scenario["expected"]["allowed_response"]
            rep_scores.append(score)
            transcripts.append({"scenario_id": scenario["scenario_id"], "repeat": r, "context": sandbox.context.as_dict() | {"tools": "omitido"},
                                "tool_calls": [{k: v for k, v in c.items() if k != "data"} | {"data_sha256": c["data_hash"]} for c in sandbox.log()],
                                "jira_created": sandbox.jira_created, "output": output})
        per_repeat.append(rep_scores)
        all_scores.extend(rep_scores)
    return all_scores, transcripts, per_repeat


def cmd_run(args: argparse.Namespace) -> int:
    ds = load_dataset()
    scenarios = list(ds.scenarios)
    if args.scenarios:
        wanted = set(args.scenarios.split(","))
        scenarios = [s for s in scenarios if s["scenario_id"] in wanted]
    agent = make_agent(args)
    gates = load_gates()
    started = datetime.now(timezone.utc)
    scores, transcripts, per_repeat = execute(agent, scenarios, args.repeat)
    desc = agent.describe()
    run_id = f"{started.strftime('%Y%m%dT%H%M%SZ')}_{desc['name']}"
    result: dict[str, Any] = {
        "metadata": {
            "run_id": run_id, "timestamp_utc": started.isoformat(), "finished_utc": datetime.now(timezone.utc).isoformat(),
            "agent": desc, "dataset": {"version": ds.version, "manifest_sha256": ds.manifest_sha256,
                                       "scenarios": [s["scenario_id"] for s in scenarios], "coverage": coverage_summary(ds)["by_category"]},
            "scorer_version": SCORER_VERSION, "gates_version": gates["version"], "policy_sha256": _sha(POLICY_PATH),
            "git_commit": _git_commit(), "git_dirty": _git_dirty(), "python": platform.python_version(), "platform": platform.platform(),
            "repeat": args.repeat, "argv": sys.argv[1:],
        },
        "scenarios": scores,
        "metrics": aggregate(scores),
        "stability": stability(per_repeat),
        "limitations": LIMITATIONS,
    }
    previous = None
    if args.baseline:
        previous = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    elif args.record:
        previous = latest_run(desc["name"])
    if previous:
        result["comparison"] = compare_runs(previous, result)
    result["gate"] = evaluate_gates(result, gates, result.get("comparison"))
    report = render(result)
    if args.record:
        d = save_run(result, transcripts)
        (d / "report.md").write_text(report, encoding="utf-8")
        if result.get("comparison"):
            append_regressions(result["comparison"], result["gate"])
        print(f"execução registrada em {d}")
    out = Path(args.output) if args.output else None
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(report if args.verbose else _summary(result))
    return result["gate"]["exit_code"]


def _summary(result: dict[str, Any]) -> str:
    m, g = result["metrics"], result["gate"]
    p, r = m["precision"], m["recall"]
    fmt = lambda x: "n/a" if x["value"] is None else f"{x['value']:.1%} (n={x['n']})"  # noqa: E731
    return (f"{result['metadata']['run_id']} | executados {m['scenarios_executed']}/{m['scenarios_total']} | {m['outcomes']}\n"
            f"precisão {fmt(p)} · recall {fmt(r)} · FP {m['false_positives']} · FN {m['false_negatives']} · "
            f"violações críticas {len(m['critical_violations'])}\n"
            f"gate: {g['decision']} (exit {g['exit_code']})")


def cmd_validate(_args: argparse.Namespace) -> int:
    ds = load_dataset()
    print(json.dumps({"dataset_version": ds.version, "manifest_sha256": ds.manifest_sha256, **coverage_summary(ds)}, ensure_ascii=False, indent=1))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    a = json.loads(Path(args.previous).read_text(encoding="utf-8"))
    b = json.loads(Path(args.current).read_text(encoding="utf-8"))
    print(json.dumps(compare_runs(a, b), ensure_ascii=False, indent=1))
    return 0


def cmd_review_apply(args: argparse.Namespace) -> int:
    d = Path(args.run_dir)
    result = json.loads((d / "result.json").read_text(encoding="utf-8"))
    reviews = json.loads(Path(args.reviews).read_text(encoding="utf-8"))
    result = apply_reviews(result, reviews)
    result["gate"] = evaluate_gates(result, load_gates(), result.get("comparison"))
    (d / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (d / "report.md").write_text(render(result), encoding="utf-8")
    print(_summary(result))
    return result["gate"]["exit_code"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="daia-evals")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--agent", choices=["reference", "naive", "orchestrator", "anthropic", "command"], default="reference")
    run.add_argument("--agent-cmd")
    run.add_argument("--agent-name")
    run.add_argument("--agent-version")
    run.add_argument("--agent-model")
    run.add_argument("--repeat", type=int, default=1)
    run.add_argument("--scenarios", help="lista separada por vírgula")
    run.add_argument("--baseline", help="result.json de referência para comparação")
    run.add_argument("--record", action="store_true", help=f"salvar em {HISTORY_DIR} e atualizar histórico de regressões")
    run.add_argument("--output", help="grava o result.json também neste caminho")
    run.add_argument("--verbose", action="store_true", help="imprime o relatório completo")
    run.set_defaults(func=cmd_run)
    sub.add_parser("validate-dataset").set_defaults(func=cmd_validate)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("previous")
    cmp_.add_argument("current")
    cmp_.set_defaults(func=cmd_compare)
    rv = sub.add_parser("review-apply")
    rv.add_argument("run_dir")
    rv.add_argument("reviews")
    rv.set_defaults(func=cmd_review_apply)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
