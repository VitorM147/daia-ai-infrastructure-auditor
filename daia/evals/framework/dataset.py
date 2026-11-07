"""Golden dataset loading, integrity and answer-leakage validation."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .taxonomy import (CAUSE_STATUSES, CLASSIFICATIONS, DIMENSIONS, EVAL_IDS, IMPACTS,
                       LEAKAGE_KEYS, PROBLEM_CLASSES, SEVERITIES)

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "golden"


class DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class Dataset:
    version: str
    manifest_sha256: str
    scenarios: tuple[dict[str, Any], ...]
    rubric: dict[str, str]

    def by_id(self, scenario_id: str) -> dict[str, Any]:
        for s in self.scenarios:
            if s["scenario_id"] == scenario_id:
                return s
        raise KeyError(scenario_id)


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _walk_keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_keys(v)


def validate_scenario(s: dict[str, Any]) -> list[str]:
    """Return a list of problems; empty means the scenario is usable."""
    errors: list[str] = []
    for key in ("scenario_id", "eval_ids", "category", "input", "telemetry", "expected", "criteria", "provenance"):
        if key not in s:
            errors.append(f"missing {key}")
    if errors:
        return errors
    sid = s["scenario_id"]
    if not s["provenance"].get("sanitized"):
        errors.append(f"{sid}: provenance.sanitized must be true")
    for eid in s["eval_ids"]:
        if eid not in EVAL_IDS:
            errors.append(f"{sid}: unknown eval id {eid}")
    exp = s["expected"]
    for f in exp.get("findings", []):
        for pc in f["problem_class"]:
            if pc not in PROBLEM_CLASSES:
                errors.append(f"{sid}: unknown problem class {pc}")
        if f["severity"] not in SEVERITIES or any(x not in SEVERITIES for x in f["severity_also_acceptable"]):
            errors.append(f"{sid}: invalid severity")
        if any(c not in CLASSIFICATIONS for c in f["classification_allowed"]):
            errors.append(f"{sid}: invalid classification")
        if any(i not in IMPACTS for i in f["impact_allowed"]):
            errors.append(f"{sid}: invalid impact")
        if any(c not in CAUSE_STATUSES for c in f["cause"]["status_allowed"]):
            errors.append(f"{sid}: invalid cause status")
        if f["requirement"] not in ("required", "optional"):
            errors.append(f"{sid}: invalid requirement")
    for c in s["criteria"]:
        if c["dimension"] not in DIMENSIONS:
            errors.append(f"{sid}: criterion {c['id']} has unknown dimension")
    if not s["criteria"]:
        errors.append(f"{sid}: at least one objective criterion is required")
    if not exp.get("allowed_response"):
        errors.append(f"{sid}: allowed_response is required")
    # Answer leakage: telemetry must not carry the answer.
    leaked_keys = LEAKAGE_KEYS & set(_walk_keys(s["telemetry"]))
    if leaked_keys:
        errors.append(f"{sid}: telemetry contains answer keys {sorted(leaked_keys)}")
    blob = json.dumps(s["telemetry"], ensure_ascii=False).lower()
    for f in exp.get("findings", []):
        for pc in f["problem_class"]:
            if pc.lower() in blob:
                errors.append(f"{sid}: telemetry mentions expected class '{pc}' literally")
    known = exp.get("known_cause")
    if known and known.lower() in blob:
        errors.append(f"{sid}: telemetry contains the known-cause text verbatim")
    return errors


def load_dataset(root: Path = GOLDEN_DIR, *, verify_hashes: bool = True) -> Dataset:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    if manifest.get("schema") != "golden-v2":
        raise DatasetError("unsupported dataset schema")
    expected_manifest = hashlib.sha256(json.dumps(manifest["scenarios"], sort_keys=True).encode()).hexdigest()
    if manifest.get("manifest_sha256") != expected_manifest:
        raise DatasetError("manifest checksum mismatch")
    scenarios = []
    problems: list[str] = []
    for entry in manifest["scenarios"]:
        raw = (root / entry["file"]).read_text(encoding="utf-8")
        if verify_hashes and hashlib.sha256(raw.encode("utf-8")).hexdigest() != entry["sha256"]:
            problems.append(f"{entry['scenario_id']}: file hash differs from manifest (dataset edited without regeneration)")
        data = json.loads(raw)
        problems.extend(validate_scenario(data))
        scenarios.append(data)
    ids = [s["scenario_id"] for s in scenarios]
    if len(ids) != len(set(ids)):
        problems.append("duplicate scenario ids")
    if problems:
        raise DatasetError("; ".join(problems))
    return Dataset(manifest["dataset_version"], manifest["manifest_sha256"], tuple(scenarios), manifest.get("severity_rubric", {}))


def coverage_summary(ds: Dataset) -> dict[str, Any]:
    by_eval = {e: [s["scenario_id"] for s in ds.scenarios if e in s["eval_ids"]] for e in EVAL_IDS}
    by_cat: dict[str, int] = {}
    for s in ds.scenarios:
        by_cat[s["category"]] = by_cat.get(s["category"], 0) + 1
    return {"total": len(ds.scenarios),
            "healthy": sum(1 for s in ds.scenarios if s.get("healthy")),
            "incidents": sum(1 for s in ds.scenarios if not s.get("healthy")),
            "by_eval": by_eval, "by_category": by_cat}
