"""Coverage matrix: service x signal x monitor, with honest statuses.

A monitor counts as DIRECT coverage for a (service, signal) only when its query names the service
and a metric/keyword that belongs to the signal. Anything weaker is PARCIALMENTE_COBERTO. Services
we have no telemetry for stay SEM_TELEMETRIA; services outside the collected scope NAO_VERIFICADO.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

COBERTO, PARCIAL, SEM_TELEMETRIA = "COBERTO", "PARCIALMENTE_COBERTO", "SEM_TELEMETRIA"
SEM_PERMISSAO, NAO_CONTRATADO, NAO_VERIFICADO = "SEM_PERMISSAO", "NAO_CONTRATADO", "NAO_VERIFICADO"
STATUSES = frozenset({COBERTO, PARCIAL, SEM_TELEMETRIA, SEM_PERMISSAO, NAO_CONTRATADO, NAO_VERIFICADO})

SIGNALS: dict[str, tuple[str, ...]] = {
    "errors": (r"\.errors\b", r"error", r"status:error", r"http\.status_code", r"5xx"),
    "latency": (r"\bp9[0-9]\b", r"percentile", r"duration", r"latency", r"latencia"),
    "availability": (r"\.hits\b", r"kubernetes_state\.deployment", r"replicas_unavailable", r"up\b", r"readiness", r"service_check", r"no data"),
    "saturation": (r"cpu", r"memory", r"working_set", r"throttl", r"hpa"),
}


@dataclass(frozen=True)
class ServiceInput:
    name: str
    env: str = "prod"
    has_apm: bool | None = None          # None = not collected
    has_logs: bool | None = None
    team: str | None = None
    team_validated: bool = False


@dataclass(frozen=True)
class MatrixRow:
    service: str
    signal: str
    status: str
    monitors: tuple[str, ...]
    reason: str


def _mentions(query: str, service: str) -> bool:
    return bool(re.search(r"(?<![A-Za-z0-9_\-])" + re.escape(service) + r"(?![A-Za-z0-9_\-])", query))


def _signal_hit(text: str, signal: str) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in SIGNALS[signal])


def build_matrix(services: Iterable[ServiceInput], monitors: Sequence[Mapping[str, object]],
                 collected_monitors_complete: bool) -> list[MatrixRow]:
    rows: list[MatrixRow] = []
    for svc in services:
        if svc.has_apm is False and svc.has_logs is False:
            for sig in SIGNALS:
                rows.append(MatrixRow(svc.name, sig, SEM_TELEMETRIA, (), "no APM and no logs observed for the service"))
            continue
        direct_by_sig: dict[str, list[str]] = {s: [] for s in SIGNALS}
        mention_ids: list[str] = []
        for m in monitors:
            text = f"{m.get('query', '')} {m.get('name', '')}"
            if not _mentions(text, svc.name):
                continue
            mention_ids.append(str(m["id"]))
            for sig in SIGNALS:
                if _signal_hit(text, sig):
                    direct_by_sig[sig].append(str(m["id"]))
        for sig in SIGNALS:
            ids = tuple(direct_by_sig[sig])
            if ids:
                rows.append(MatrixRow(svc.name, sig, COBERTO, ids, "monitor query names the service and a metric of this signal"))
            elif mention_ids:
                rows.append(MatrixRow(svc.name, sig, PARCIAL, tuple(mention_ids), "service is monitored for other signals only"))
            elif collected_monitors_complete:
                rows.append(MatrixRow(svc.name, sig, SEM_TELEMETRIA if svc.has_apm is False else NAO_VERIFICADO,
                                      (), "no monitor names this service; indirect coverage (composite, tag-based, SLO) not checked"))
            else:
                rows.append(MatrixRow(svc.name, sig, NAO_VERIFICADO, (), "monitor inventory incomplete; absence is not proof"))
    return rows


def summarize(rows: Iterable[MatrixRow]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r.status] = out.get(r.status, 0) + 1
    return out


def can_declare_complete_audit(domain_status: Mapping[str, str], required: Iterable[str]) -> tuple[bool, list[str]]:
    """An audit is complete only if every required domain was assessed (COBERTO/PARCIAL are assessments; the rest are not)."""
    missing = [d for d in required if domain_status.get(d, NAO_VERIFICADO) not in (COBERTO, PARCIAL)]
    return (not missing), missing
