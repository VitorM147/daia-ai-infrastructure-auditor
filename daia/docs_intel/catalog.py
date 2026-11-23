"""Versioned catalog of operational rules derived from official Datadog documentation.

A rule is a *paraphrased*, verifiable pointer to an official page, never a copy of it.
Nothing here executes anything: every rule is RECOMMEND_ONLY / read-only inspection.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

RULES_PATH = Path(__file__).with_name("rules.json")
OFFICIAL_HOSTS = frozenset({"docs.datadoghq.com"})
RULE_ID_RX = re.compile(r"^DAIA-DOC-[A-Z]{2,6}-\d{3}$")

APPLICABILITY = frozenset({"APPLICABLE", "REQUIRES_CONFIGURATION_VALIDATION", "NOT_APPLICABLE", "UNKNOWN"})
COST_STATUS = frozenset({"CUSTO_ZERO_CONFIRMADO", "CUSTO_POTENCIAL", "CUSTO_DESCONHECIDO", "RECURSO_PAGO"})
INSPECTION = frozenset({"READ_ONLY", "NONE"})            # REQUIRES_WRITE is deliberately not representable
ACTIONS = frozenset({"RECOMMEND_ONLY", "INFORM"})        # APPLY / EXECUTE are deliberately not representable
CONFIDENCE = frozenset({"UNVERIFIED", "DOCUMENTED", "ENVIRONMENT_VALIDATED"})
DOCUMENTED_COST = frozenset({"free", "billable", "unknown"})


class CatalogError(ValueError):
    """Raised when a rule or the catalog violates the schema."""


@dataclass(frozen=True)
class Source:
    type: str
    url: str
    section: str
    verified_at: str | None
    page_sha256: str | None = None


@dataclass(frozen=True)
class Rule:
    rule_id: str
    domain: str
    title: str
    summary: str
    source: Source
    applicability: str
    conditions: tuple[str, ...]
    risks: tuple[str, ...]
    permitted_action: str
    prohibited_action: str
    documented_cost: str
    cost_status: str
    cost_note: str
    inspection: str
    action: str
    confidence: str
    depends_on: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    history: tuple[dict[str, str], ...] = ()
    signals: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Rule":
        try:
            src = raw["source"]
            rule = cls(
                rule_id=raw["rule_id"], domain=raw["domain"], title=raw["title"], summary=raw["summary"],
                source=Source(src["type"], src["url"], src.get("section", ""), src.get("verified_at"), src.get("page_sha256")),
                applicability=raw["applicability"], conditions=tuple(raw["conditions"]), risks=tuple(raw["risks"]),
                permitted_action=raw["permitted_action"], prohibited_action=raw["prohibited_action"],
                documented_cost=raw["documented_cost"], cost_status=raw["cost_status"], cost_note=raw.get("cost_note", ""),
                inspection=raw["inspection"], action=raw["action"], confidence=raw["confidence"],
                depends_on=tuple(raw.get("depends_on", ())), tests=tuple(raw.get("tests", ())),
                history=tuple(raw.get("history", ())), signals=tuple(raw.get("signals", ())),
            )
        except KeyError as exc:
            raise CatalogError(f"rule is missing field {exc!s}: {raw.get('rule_id', '<no id>')}") from exc
        rule.validate()
        return rule

    def validate(self) -> None:
        rid = self.rule_id
        if not RULE_ID_RX.match(rid):
            raise CatalogError(f"invalid rule_id: {rid}")
        if self.source.type != "official_datadog":
            raise CatalogError(f"{rid}: source.type must be official_datadog")
        parsed = urlparse(self.source.url)
        if parsed.scheme != "https" or parsed.hostname not in OFFICIAL_HOSTS:
            raise CatalogError(f"{rid}: source must be https on an official host, got {self.source.url}")
        for name, value, allowed in (("applicability", self.applicability, APPLICABILITY),
                                     ("cost_status", self.cost_status, COST_STATUS),
                                     ("inspection", self.inspection, INSPECTION),
                                     ("action", self.action, ACTIONS),
                                     ("confidence", self.confidence, CONFIDENCE),
                                     ("documented_cost", self.documented_cost, DOCUMENTED_COST)):
            if value not in allowed:
                raise CatalogError(f"{rid}: invalid {name}={value!r}; allowed {sorted(allowed)}")
        if self.source.verified_at is not None:
            try:
                date.fromisoformat(self.source.verified_at)
            except ValueError as exc:
                raise CatalogError(f"{rid}: verified_at must be an ISO date") from exc
        if self.confidence != "UNVERIFIED" and not self.source.verified_at:
            raise CatalogError(f"{rid}: confidence {self.confidence} requires source.verified_at")
        # The catalog never *assumes* free: a rule can only claim CUSTO_ZERO_CONFIRMADO with a contract check.
        if self.cost_status == "CUSTO_ZERO_CONFIRMADO":
            raise CatalogError(f"{rid}: catalog rules cannot assert contract-level zero cost; use costgov with a human validation")
        if self.documented_cost == "billable" and self.cost_status != "RECURSO_PAGO":
            raise CatalogError(f"{rid}: documented billable product must be RECURSO_PAGO")
        for field_name in ("title", "summary", "permitted_action", "prohibited_action"):
            if not getattr(self, field_name).strip():
                raise CatalogError(f"{rid}: {field_name} is empty")
        if not self.conditions or not self.risks:
            raise CatalogError(f"{rid}: conditions and risks are required")
        if len(self.summary) > 600:
            raise CatalogError(f"{rid}: summary too long; store a paraphrase, not the page")
        if not self.history:
            raise CatalogError(f"{rid}: history is required")
        if not self.tests:
            raise CatalogError(f"{rid}: at least one associated test is required")

    def as_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id, "domain": self.domain, "title": self.title, "summary": self.summary,
            "source": {"type": self.source.type, "url": self.source.url, "section": self.source.section,
                       "verified_at": self.source.verified_at, "page_sha256": self.source.page_sha256},
            "applicability": self.applicability, "conditions": list(self.conditions), "risks": list(self.risks),
            "permitted_action": self.permitted_action, "prohibited_action": self.prohibited_action,
            "documented_cost": self.documented_cost, "cost_status": self.cost_status, "cost_note": self.cost_note,
            "inspection": self.inspection, "action": self.action, "confidence": self.confidence,
            "depends_on": list(self.depends_on), "tests": list(self.tests), "history": list(self.history),
            "signals": list(self.signals),
        }


class Catalog:
    def __init__(self, rules: Iterable[Rule], version: str = "1"):
        self.version = version
        self.rules: dict[str, Rule] = {}
        for rule in rules:
            if rule.rule_id in self.rules:
                raise CatalogError(f"duplicate rule_id: {rule.rule_id}")
            self.rules[rule.rule_id] = rule
        for rule in self.rules.values():
            for dep in rule.depends_on:
                if dep not in self.rules:
                    raise CatalogError(f"{rule.rule_id}: depends_on unknown rule {dep}")
                if dep == rule.rule_id:
                    raise CatalogError(f"{rule.rule_id}: depends on itself")

    @classmethod
    def load(cls, path: str | Path = RULES_PATH) -> "Catalog":
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return cls((Rule.from_dict(r) for r in data["rules"]), version=str(data.get("catalog_version", "1")))

    def save(self, path: str | Path = RULES_PATH) -> None:
        payload = {"catalog_version": self.version, "rules": [r.as_dict() for r in self.rules.values()]}
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    def get(self, rule_id: str) -> Rule:
        try:
            return self.rules[rule_id]
        except KeyError as exc:
            raise CatalogError(f"unknown rule_id: {rule_id}") from exc

    def by_domain(self, domain: str) -> list[Rule]:
        return [r for r in self.rules.values() if r.domain == domain]
