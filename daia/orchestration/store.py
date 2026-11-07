"""Durable audit state: checkpoints, query cache, event log and finding registry.

Everything needed to resume lives on disk (not in the LLM conversation).
Writes are atomic (temp file + rename) so an interruption mid-write never
leaves a corrupted checkpoint.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping

DAIA_DIR = Path(__file__).resolve().parent.parent
AUDITS_DIR = DAIA_DIR / "audits"
REGISTRY_PATH = DAIA_DIR / "findings" / "registry.json"

CHECKPOINT_SCHEMA = "audit-checkpoint-v1"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def query_key(tool: str, args: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({"tool": tool, "args": dict(args)}).encode("utf-8")).hexdigest()[:32]


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


class AuditStore:
    """Per-audit persistence. ``root=None`` keeps everything in memory (tests/evals)."""

    def __init__(self, audit_id: str, root: Path | None = AUDITS_DIR):
        self.audit_id = audit_id
        self.dir = (root / audit_id) if root is not None else None
        self._mem_checkpoint: dict[str, Any] | None = None
        self._mem_queries: dict[str, dict[str, Any]] = {}
        self._mem_events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    # checkpoints
    def save_checkpoint(self, checkpoint: Mapping[str, Any]) -> None:
        data = json.loads(canonical(checkpoint))
        if self.dir is None:
            self._mem_checkpoint = data
            return
        _atomic_write(self.dir / "checkpoint.json", json.dumps(data, ensure_ascii=False, indent=1) + "\n")

    def load_checkpoint(self) -> dict[str, Any] | None:
        if self.dir is None:
            return json.loads(canonical(self._mem_checkpoint)) if self._mem_checkpoint else None
        path = self.dir / "checkpoint.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != CHECKPOINT_SCHEMA:
            raise ValueError(f"checkpoint com schema não suportado: {data.get('schema')}")
        return data

    # query cache
    def put_query(self, record: Mapping[str, Any]) -> None:
        with self._lock:
            if self.dir is None:
                self._mem_queries[record["key"]] = json.loads(canonical(record))
                return
            _atomic_write(self.dir / "queries" / f"{record['key']}.json", canonical(record))

    def get_query(self, key: str) -> dict[str, Any] | None:
        if self.dir is None:
            return self._mem_queries.get(key)
        path = self.dir / "queries" / f"{key}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    # event log (append-only)
    def event(self, event_type: str, **data: Any) -> None:
        entry = {"event": event_type, **data}
        with self._lock:
            if self.dir is None:
                self._mem_events.append(entry)
                return
            self.dir.mkdir(parents=True, exist_ok=True)
            with (self.dir / "events.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(canonical(entry) + "\n")

    def events(self) -> list[dict[str, Any]]:
        if self.dir is None:
            return list(self._mem_events)
        path = self.dir / "events.jsonl"
        return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()] if path.exists() else []

    def write_report(self, name: str, text: str) -> Path | None:
        if self.dir is None:
            return None
        path = self.dir / name
        _atomic_write(path, text)
        return path


def list_audits(root: Path = AUDITS_DIR) -> list[dict[str, Any]]:
    out = []
    if not root.exists():
        return out
    for d in sorted(root.iterdir()):
        cp = d / "checkpoint.json"
        if cp.exists():
            data = json.loads(cp.read_text(encoding="utf-8"))
            out.append({"audit_id": data["audit_id"], "status": data["status"], "mode": data["request"]["mode"],
                        "environment": data["request"]["environment"], "updated_at": data["updated_at_utc"],
                        "stages_done": sum(1 for s in data["stages"].values() if s["status"] in ("CONCLUÍDA", "NÃO SOLICITADO"))})
    return out


class FindingRegistry:
    """Fingerprint registry used to detect recurrence across audits."""

    def __init__(self, path: Path | None = REGISTRY_PATH):
        self.path = path
        self._mem: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        if self.path is None:
            return json.loads(canonical(self._mem)) if self._mem else {"schema": "finding-registry-v1", "fingerprints": {}}
        if not self.path.exists():
            return {"schema": "finding-registry-v1", "fingerprints": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def lookup(self, fingerprints: Iterable[str]) -> dict[str, Any]:
        data = self.load()["fingerprints"]
        return {fp: data[fp] for fp in fingerprints if fp in data}

    def record(self, audit_id: str, at_utc: str, findings: Iterable[Mapping[str, Any]]) -> None:
        data = self.load()
        fps = data["fingerprints"]
        for f in findings:
            entry = fps.setdefault(f["fingerprint"], {"problem_class": f["problem_class"], "resource": f["resource"],
                                                      "first_seen_utc": at_utc, "occurrences": 0, "audits": []})
            if audit_id in entry["audits"]:
                continue
            entry["occurrences"] += 1
            entry["audits"] = (entry["audits"] + [audit_id])[-50:]
            entry["last_seen_utc"] = at_utc
            entry["last_severity"] = f["severity"]
            entry["last_classification"] = f["classification"]
        if self.path is None:
            self._mem = json.loads(canonical(data))
            return
        _atomic_write(self.path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")
