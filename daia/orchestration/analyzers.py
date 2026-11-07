"""Detection and correlation rules applied to collected (cached) telemetry.

Pure functions: they never call tools, so re-running them on resume costs no
queries. Thresholds are generic SRE heuristics documented in DETECTION; they
are not corporate values and must be validated per service before being used
as alerting policy.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from typing import Any, Iterable, Mapping

from daia.diagnostics.baseline import build_baseline, compare_with_baseline
from daia.diagnostics.metrics import MetricCalculationError, calculate_rate
from daia.diagnostics.models import MetricPoint
from daia.jira.fingerprint import build_fingerprint
from daia.proactive.trend import estimate_exhaustion

DETECTION = {
    "current_window_h": 3, "baseline_days": 6,
    "error_rel_threshold": 1.0, "error_abs_min": 0.01, "error_p1_rate": 0.05, "min_hits": 300,
    "latency_rel_threshold": 0.5, "latency_p2_ms": 1000,
    "lag_rel_threshold": 3.0, "retrans_rel_threshold": 2.0, "retrans_ratio_min": 0.005,
    "disk_current_threshold": 0.90, "disk_risk_horizon_days": 7,
    "event_repeat_min": 3, "dns_log_min": 20, "flapping_changes_24h": 20,
}

INJECTION_RX = re.compile(r"(?i)(ignore (all |the )?previous instructions|ignore as instruções|system override|you are now|chame a ferramenta|call (the tool )?\w+_\w+|print every api_key)")
SECRET_RX = re.compile(r"(?i)(bearer\s+[a-z0-9_\-\.]{16,}|sk_live_[a-z0-9]+|AKIA[0-9A-Z]{16}|password\s*[=:]|\b\d{3}\.\d{3}\.\d{3}-\d{2}\b)")
DNS_RX = re.compile(r"(?i)(EAI_AGAIN|NXDOMAIN|DNS lookup failed|could not resolve host)")
POOL_RX = re.compile(r"(?i)(pool exhausted|connection is not available|timeout acquiring connection)")
METRIC_IN_QUERY_RX = re.compile(r"(?:avg|sum|max|min):([a-zA-Z0-9_.]+)\{")


def _dt(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _ts(start: str, i: int) -> datetime:
    return _dt(start) + timedelta(hours=i)


def metric_work_items(inventory: Mapping[str, list], environment: str) -> list[dict[str, str]]:
    """Every metric query the anomaly stage must answer for full coverage."""
    items = []
    for s in inventory.get("services", []):
        scope = f"service:{s['service']},env:{environment}"
        for m in ("trace.http.request.hits", "trace.http.request.errors", "trace.http.request.duration.by.service.95p"):
            items.append({"resource": s["service"], "metric": m, "scope": scope})
    for w in inventory.get("workloads", []):
        if (w.get("hpa") or {}).get("max", 1) > 1:
            for m in ("kubernetes_state.hpa.current_replicas", "kubernetes.cpu.usage.pct_of_request"):
                items.append({"resource": w["name"], "metric": m, "scope": f"kube_deployment:{w['name']}"})
    for g in inventory.get("kafka_consumer_groups", []):
        items.append({"resource": g["group"], "metric": "kafka.consumer_lag", "scope": f"consumer_group:{g['group']}"})
    for d in inventory.get("databases", []):
        items.append({"resource": d["name"], "metric": "db.pool.active", "scope": f"db:{d['name']}"})
    for v in inventory.get("volumes", []):
        items.append({"resource": f"{v['host']}:{v['device']}", "metric": "system.disk.in_use", "scope": f"host:{v['host']},device:{v['device']}"})
    for h in inventory.get("hosts", []):
        for m in ("system.net.tcp.out_segs", "system.net.tcp.retrans_segs"):
            items.append({"resource": h["host"], "metric": m, "scope": f"host:{h['host']}"})
    return items


class Analyzer:
    def __init__(self, data: Mapping[str, Any], environment: str, now: datetime):
        self.d = data
        self.env = environment
        self.now = now
        self.inv = data.get("inventory", {})
        self.monitors = data.get("monitors", [])
        self.events = data.get("events", [])
        self.changes = data.get("changes", [])
        self.incidents = data.get("incidents", [])
        self.logs = data.get("logs", [])
        self.metrics = data.get("metrics", {})
        self.calls = data.get("call_ids", {})
        self.findings: list[dict[str, Any]] = []
        self.unconfirmed: list[dict[str, Any]] = []
        self.notices: list[dict[str, Any]] = []

    def series(self, metric: str, scope: str) -> tuple[str | None, list[float] | None, str | None]:
        rec = self.metrics.get(f"{metric}|{scope}")
        if not rec or not rec.get("values"):
            return (rec or {}).get("call_id"), None, None
        return rec.get("call_id"), [float(v) for v in rec["values"]], rec["start"]

    # ------------------------------------------------------------ detection
    def run(self) -> None:
        self._monitors()
        self._logs()
        for s in self.inv.get("services", []):
            self._service(s)
        for w in self.inv.get("workloads", []):
            self._workload(w)
        for g in self.inv.get("kafka_consumer_groups", []):
            self._kafka(g)
        for db in self.inv.get("databases", []):
            self._db(db)
        for v in self.inv.get("volumes", []):
            self._volume(v)
        for h in self.inv.get("hosts", []):
            self._network(h)
        self._unconfirmed_alerts()

    def _links_for(self, svc: str | None, host: str | None = None) -> list[str]:
        out = []
        for m in self.monitors:
            tags = m.get("tags", [])
            if (svc and f"service:{svc}" in tags) or (host and f"host:{host}" in tags):
                if m.get("url"):
                    out.append(m["url"])
        out += [i["url"] for i in self.incidents if svc and svc in i.get("services", []) and i.get("url")]
        return list(dict.fromkeys(out))

    def add(self, pclass, resource, service, severity, classification, impact, summary, *, evidence, computed=None,
            silent=False, links=None, cause=None, cause_kind="rate", deps=None, state="PROBLEMA_ATUAL") -> None:
        if any(f["problem_class"] == pclass and f["resource"] == resource for f in self.findings):
            return
        self.findings.append({
            "problem_class": pclass, "resource": resource, "service": service, "environment": self.env,
            "severity": severity, "classification": classification, "silent": silent, "impact": impact,
            "summary": summary, "state": state, "cause": cause, "cause_fixed": cause is not None, "cause_kind": cause_kind, "deps": deps or [],
            "evidence": evidence, "computed": computed or [], "links": [{"url": u, "validated": False} for u in (links or [])],
            "fingerprint": build_fingerprint(environment=self.env, application=service or resource, service=service or resource,
                                             resource=resource, problem_class=pclass, failure_identifier=pclass),
        })

    def _monitors(self) -> None:
        call = self.calls.get("monitors")
        catalog = set(self.d.get("metric_catalog") or [])
        catalog_ok = self.d.get("metric_catalog_complete", False)
        for m in self.monitors:
            if m.get("overall_state") == "No Data":
                match = METRIC_IN_QUERY_RX.search(m.get("query", ""))
                if match and catalog_ok and match.group(1) not in catalog:
                    self.add("monitor_misconfigured", f"monitor:{m['id']}", None, "P2", "OBSERVADO", "potencial",
                             f"Monitor {m['id']} em No Data consulta a métrica '{match.group(1)}', inexistente no catálogo completo de métricas.",
                             evidence=[{"call_id": call, "value": "No Data", "note": "overall_state"},
                                       {"call_id": call, "value": m["id"], "note": "id do monitor"}],
                             silent=True, links=[m["url"]] if m.get("url") else [],
                             cause=_simple("hipótese", f"métrica {match.group(1)} renomeada ou não coletada", ["tag de host alterada", "agente sem a integração"]))
                elif match:
                    self.unconfirmed.append({"item": f"monitor:{m['id']}", "reason": "No Data; catálogo de métricas incompleto para confirmar a causa"})
            changes = m.get("state_changes_24h")
            if isinstance(changes, (int, float)) and changes >= DETECTION["flapping_changes_24h"]:
                self.add("monitor_flapping", f"monitor:{m['id']}", None, "P3", "OBSERVADO", "potencial",
                         f"Monitor {m['id']} alternou {changes} vezes em 24h.",
                         evidence=[{"call_id": call, "value": changes, "note": "state_changes_24h"}],
                         links=[m["url"]] if m.get("url") else [],
                         cause=_simple("hipótese", "limiar ou janela de avaliação inadequados", ["variação real intermitente"]))

    def _service(self, svc: Mapping[str, Any]) -> None:
        name = svc["service"]
        scope = f"service:{name},env:{self.env}"
        w, days = DETECTION["current_window_h"], DETECTION["baseline_days"]
        hc, hits, start = self.series("trace.http.request.hits", scope)
        ec, errs, _ = self.series("trace.http.request.errors", scope)
        if hits and errs and sum(hits[-w:]) >= DETECTION["min_hits"]:
            cur = _rate(errs, hits, start, len(hits) - w, len(hits))
            samples = []
            for d in range(1, days + 1):
                end = len(hits) - 24 * d
                if end - w < 0:
                    break
                samples.append(MetricPoint("error_rate", _ts(start, end - 1), sum(errs[end - w:end]) / max(sum(hits[end - w:end]), 1),
                                           "ratio", name, name, self.env, (), "derived:trace.http.request"))
            base = build_baseline(samples, start_utc=_ts(start, 0), end_utc=_ts(start, len(hits)), expected_points=days)
            cmp = compare_with_baseline(cur, base, threshold=DETECTION["error_rel_threshold"])
            if cmp["status"] == "REGRESSION" and cur >= DETECTION["error_abs_min"]:
                silent = not any(f"service:{name}" in m.get("tags", []) and m.get("overall_state") in ("Alert", "Warn") for m in self.monitors)
                self.add("error_rate_regression", name, name, "P1" if cur >= DETECTION["error_p1_rate"] else "P2", "OBSERVADO", "observado",
                         f"Taxa de erro {cur:.2%} nas últimas {w}h vs baseline {base.value:.2%} (mesmo horário, {len(samples)} dias)"
                         + (" sem monitor em alerta (falha silenciosa)." if silent else "."),
                         evidence=[{"call_id": ec, "value": errs[-1], "note": "erros na última hora"},
                                   {"call_id": hc, "value": hits[-1], "note": "requisições na última hora"}],
                         computed=[{"name": "error_rate_current", "value": cur, "op": "ratio",
                                    "inputs": [{"call_id": ec, "series_index": 0, "slice": [-w, None]}, {"call_id": hc, "series_index": 0, "slice": [-w, None]}]},
                                   {"name": "error_rate_baseline", "value": base.value, "op": "seasonal_median", "inner": "ratio", "window": w,
                                    "days": len(samples), "inputs": [{"call_id": ec, "series_index": 0}, {"call_id": hc, "series_index": 0}]}],
                         silent=silent, links=self._links_for(name), deps=svc.get("dependencies", []))
        lc, lat, _ = self.series("trace.http.request.duration.by.service.95p", scope)
        if lat:
            cur = mean(lat[-w:])
            samples = [mean(lat[len(lat) - 24 * d - w:len(lat) - 24 * d]) for d in range(1, days + 1) if len(lat) - 24 * d - w >= 0]
            base = median(samples) if samples else None
            if base and (cur - base) / base >= DETECTION["latency_rel_threshold"]:
                self.add("latency_regression", name, name, "P2" if cur >= DETECTION["latency_p2_ms"] else "P3", "OBSERVADO", "potencial",
                         f"Latência p95 média {cur:.0f} ms nas últimas {w}h vs baseline {base:.0f} ms; impacto em usuários não comprovado.",
                         evidence=[{"call_id": lc, "value": lat[-1], "note": "p95 da última hora (ms)"}],
                         computed=[{"name": "p95_current_mean", "value": cur, "op": "mean", "inputs": [{"call_id": lc, "series_index": 0, "slice": [-w, None]}]},
                                   {"name": "p95_baseline", "value": base, "op": "seasonal_median", "inner": "mean", "window": w,
                                    "days": len(samples), "inputs": [{"call_id": lc, "series_index": 0}]}],
                         links=self._links_for(name), deps=svc.get("dependencies", []))

    def _workload(self, wl: Mapping[str, Any]) -> None:
        name, call = wl["name"], self.calls.get("events")
        for c in wl.get("containers", []):
            tags = {f"kube_deployment:{name}", f"kube_container_name:{c['name']}"}
            evs = [e for e in self.events if tags <= set(e.get("tags", []))]
            ooms = [e for e in evs if "OOMKilled" in e["title"] + e.get("text", "")]
            crashes = [e for e in evs if "Back-off restarting" in e["title"]]
            res = f"{name}/{c['name']}"
            if len(ooms) >= DETECTION["event_repeat_min"]:
                self.add("oom_kill", res, name, "P2", "OBSERVADO", "potencial",
                         f"{len(ooms)} eventos OOMKilled no container {c['name']} (limite {c.get('memory_limit_mib')} MiB).",
                         evidence=[{"call_id": call, "value": ooms[-1]["title"], "note": "evento Kubernetes"}], links=self._links_for(name),
                         cause=_simple("hipótese", "consumo de memória atinge o limite do container", ["limite subdimensionado", "pico de carga"]))
            elif len(crashes) >= DETECTION["event_repeat_min"]:
                self.add("pod_crashloop", res, name, "P2", "OBSERVADO", "potencial",
                         f"{len(crashes)} eventos de CrashLoopBackOff no container {c['name']}.",
                         evidence=[{"call_id": call, "value": crashes[-1]["title"], "note": "evento Kubernetes"}], links=self._links_for(name),
                         cause=_simple("hipótese", "falha de inicialização do container (ver logs de saída)", ["configuração ausente", "dependência indisponível"]))
        hpa = wl.get("hpa")
        if hpa and hpa.get("max", 1) > 1:
            rc, rep, _ = self.series("kubernetes_state.hpa.current_replicas", f"kube_deployment:{name}")
            cc, cpu, _ = self.series("kubernetes.cpu.usage.pct_of_request", f"kube_deployment:{name}")
            w = DETECTION["current_window_h"]
            if rep and cpu and all(r >= hpa["max"] for r in rep[-w:]) and mean(cpu[-w:]) > hpa.get("target_cpu_pct", 100):
                self.add("hpa_at_max", name, name, "P2", "OBSERVADO", "potencial",
                         f"HPA em {int(rep[-1])}/{hpa['max']} réplicas por {w}h com CPU média {mean(cpu[-w:]):.0f}% acima do alvo {hpa.get('target_cpu_pct')}%.",
                         evidence=[{"call_id": rc, "value": rep[-1], "note": "réplicas atuais"}, {"call_id": cc, "value": cpu[-1], "note": "CPU % do request"}],
                         computed=[{"name": "cpu_mean_window", "value": mean(cpu[-w:]), "op": "mean", "inputs": [{"call_id": cc, "series_index": 0, "slice": [-w, None]}]}],
                         links=self._links_for(name), cause_kind="capacity")

    def _kafka(self, g: Mapping[str, Any]) -> None:
        lc, lag, _ = self.series("kafka.consumer_lag", f"consumer_group:{g['group']}")
        if not lag:
            return
        samples = [lag[len(lag) - 1 - 24 * d] for d in range(1, DETECTION["baseline_days"] + 1) if len(lag) - 1 - 24 * d >= 0]
        base = median(samples) if samples else None
        growing = all(b > a for a, b in zip(lag[-6:], lag[-5:]))
        if base and base > 0 and (lag[-1] - base) / base >= DETECTION["lag_rel_threshold"] and growing:
            self.add("kafka_consumer_lag", g["group"], g.get("service"), "P2", "OBSERVADO", "potencial",
                     f"Lag do grupo {g['group']} em {lag[-1]:.0f} e crescente nas últimas 6h; baseline do mesmo horário {base:.0f}.",
                     evidence=[{"call_id": lc, "value": lag[-1], "note": "lag atual"}],
                     computed=[{"name": "lag_baseline", "value": base, "op": "seasonal_median", "inner": "last", "window": 1,
                                "days": len(samples), "inputs": [{"call_id": lc, "series_index": 0}]}],
                     links=self._links_for(g.get("service") or g["group"]))

    def _db(self, db: Mapping[str, Any]) -> None:
        pc, pool, _ = self.series("db.pool.active", f"db:{db['name']}")
        w, pmax = DETECTION["current_window_h"], db.get("pool_max")
        if pool and pmax and all(v >= 0.95 * pmax for v in pool[-w:]):
            client = db.get("client_service")
            hits = [l for l in self.logs if POOL_RX.search(l["message"]) and (not client or l["service"] == client)]
            observed = len(hits) >= 5
            self.add("db_connection_pool_exhaustion", db["name"], client, "P1" if observed else "P2", "OBSERVADO",
                     "observado" if observed else "potencial",
                     f"Pool em {pool[-1]:.0f}/{pmax} por {w}h" + (f" com {len(hits)} erros de aquisição de conexão." if observed else "."),
                     evidence=[{"call_id": pc, "value": pool[-1], "note": "conexões ativas"}]
                     + ([{"call_id": self.calls.get("logs"), "value": "Connection is not available", "note": "trecho de log"}] if observed else []),
                     links=self._links_for(client or db["name"]), cause_kind="config", deps=[client] if client else [])

    def _volume(self, v: Mapping[str, Any]) -> None:
        host, dev = v["host"], v["device"]
        dc, disk, start = self.series("system.disk.in_use", f"host:{host},device:{dev}")
        if not disk:
            return
        res = f"{host}:{dev}"
        owner = next((s["service"] for s in self.inv.get("services", []) if host.startswith(s["service"])), None)
        if disk[-1] >= DETECTION["disk_current_threshold"]:
            self.add("disk_saturation", res, owner, "P1", "OBSERVADO", "potencial",
                     f"Volume {dev} em {disk[-1]:.1%} de uso (limiar {DETECTION['disk_current_threshold']:.0%}).",
                     evidence=[{"call_id": dc, "value": disk[-1], "note": "fração de uso"}], links=self._links_for(None, host),
                     cause_kind="capacity_change")
            return
        pts = [MetricPoint("system.disk.in_use", _ts(start, i), val, "fraction", res, None, None, (), "metric") for i, val in enumerate(disk)]
        est = estimate_exhaustion(pts, threshold=DETECTION["disk_current_threshold"], expected_points=len(disk))
        if est.status == "ESTIMATE" and est.seconds_to_threshold is not None and est.seconds_to_threshold < DETECTION["disk_risk_horizon_days"] * 86400:
            self.add("disk_saturation_risk", res, owner, "P3", "INFERIDO", "potencial",
                     f"Risco futuro: {disk[-1]:.1%} hoje; projeção linear atinge {DETECTION['disk_current_threshold']:.0%} em "
                     f"{est.seconds_to_threshold/86400:.1f} dias (intervalo {est.lower_seconds/86400:.1f}–{est.upper_seconds/86400:.1f}); não é garantia.",
                     evidence=[{"call_id": dc, "value": disk[-1], "note": "fração de uso atual"}], state="RISCO_FUTURO",
                     cause=_simple("indeterminada", "crescimento contínuo de dados", ["mudança de retenção", "aumento de ingestão"]))

    def _network(self, h: Mapping[str, Any]) -> None:
        name = h["host"]
        oc, out, _ = self.series("system.net.tcp.out_segs", f"host:{name}")
        rc, ret, _ = self.series("system.net.tcp.retrans_segs", f"host:{name}")
        if not out or not ret:
            return
        w = DETECTION["current_window_h"]
        cur = sum(ret[-w:]) / sum(out[-w:])
        samples = [sum(ret[len(ret) - 24 * d - w:len(ret) - 24 * d]) / sum(out[len(out) - 24 * d - w:len(out) - 24 * d])
                   for d in range(1, DETECTION["baseline_days"] + 1) if len(out) - 24 * d - w >= 0]
        base = median(samples)
        if base > 0 and (cur - base) / base >= DETECTION["retrans_rel_threshold"] and cur >= DETECTION["retrans_ratio_min"]:
            self.add("network_retransmission", name, None, "P2", "OBSERVADO", "potencial",
                     f"Razão de retransmissão TCP {cur:.2%} vs baseline {base:.2%} (normalizada pelo tráfego).",
                     evidence=[{"call_id": rc, "value": ret[-1], "note": "segmentos retransmitidos"}, {"call_id": oc, "value": out[-1], "note": "segmentos enviados"}],
                     computed=[{"name": "retrans_ratio_current", "value": cur, "op": "ratio",
                                "inputs": [{"call_id": rc, "series_index": 0, "slice": [-w, None]}, {"call_id": oc, "series_index": 0, "slice": [-w, None]}]}],
                     cause=_simple("indeterminada", "perda de pacotes ou congestionamento", ["NIC/host degradado", "upstream instável"]))

    def _logs(self) -> None:
        call = self.calls.get("logs")
        recent = self.now - timedelta(hours=DETECTION["current_window_h"])
        dns: dict[str, int] = {}
        secrets: dict[str, list[str]] = {}
        for e in self.logs:
            msg = e["message"]
            if INJECTION_RX.search(msg) and not any(n["type"] == "prompt_injection" and n.get("service") == e["service"] for n in self.notices):
                self.notices.append({"type": "prompt_injection", "call_id": call, "service": e["service"],
                                     "description": f"Instruções embutidas em logs de {e['service']} tratadas como dado; nenhuma ação executada."})
            if SECRET_RX.search(msg):
                secrets.setdefault(e["service"], []).append(msg)
            if _dt(e["timestamp"]) >= recent and DNS_RX.search(msg):
                dns[e["service"]] = dns.get(e["service"], 0) + 1
        for svc, msgs in secrets.items():
            prefix = SECRET_RX.split(msgs[0])[0].strip()[:30] or "log"
            self.add("secret_exposed_in_logs", svc, svc, "P1", "OBSERVADO", "potencial",
                     f"{len(msgs)} log(s) de {svc} com credencial/PII em texto claro (valores redigidos).",
                     evidence=[{"call_id": call, "value": prefix, "note": "trecho não sensível"}], links=self._links_for(svc),
                     cause=_simple("provável", "log de cabeçalhos/payload sem mascaramento", ["biblioteca de logging de terceiros"]))
        for svc, n in dns.items():
            if n >= DETECTION["dns_log_min"]:
                self.add("dns_resolution_failure", svc, svc, "P2", "OBSERVADO", "observado",
                         f"{n} falhas de resolução DNS em {DETECTION['current_window_h']}h nos logs de {svc}.",
                         evidence=[{"call_id": call, "value": "EAI_AGAIN", "note": "código de erro DNS"}], links=self._links_for(svc),
                         cause=_simple("hipótese", "resolvedor ou zona DNS instável", ["mudança de DNS do parceiro", "limite do resolvedor"]))

    def _unconfirmed_alerts(self) -> None:
        for m in self.monitors:
            if m.get("overall_state") not in ("Alert", "Warn"):
                continue
            svc = next((t.split(":", 1)[1] for t in m.get("tags", []) if t.startswith("service:")), None)
            host = next((t.split(":", 1)[1] for t in m.get("tags", []) if t.startswith("host:")), None)
            covered = any(f["service"] == svc or f["resource"] == svc or (host and f["resource"].startswith(host)) for f in self.findings)
            if not covered:
                self.unconfirmed.append({"item": f"monitor:{m['id']}", "reason": f"monitor em {m['overall_state']} sem anomalia confirmada pela telemetria coletada"})

    # ----------------------------------------------------------- correlation
    def correlate(self) -> None:
        for f in self.findings:
            if f["cause"] is None:
                f["cause"] = self._cause(f)

    def _cause(self, f: Mapping[str, Any]) -> dict[str, Any]:
        targets = {x for x in [f["service"], f["resource"], *f["deps"]] if x}
        for inc in self.incidents:
            rc = inc.get("root_cause") or {}
            if rc.get("confirmed") and targets & set(inc.get("services", [])):
                return {"code": rc.get("code"), "description": f"Incidente {inc['id']}: {rc.get('text', '')}", "status": "confirmada",
                        "alternatives": [], "evidence_against": ["nenhuma registrada no postmortem"]}
        lookback = timedelta(days=7) if f["cause_kind"] == "capacity_change" else timedelta(hours=6)
        cands = [c for c in self.changes if self.now - lookback <= _dt(c["timestamp"]) <= self.now
                 and (c["service"] in targets or f["resource"].startswith(c["service"]))]
        net = [e for e in self.events if e.get("source") == "network" and self.now - lookback <= _dt(e["timestamp"]) <= self.now]
        if len(cands) == 1 and not net:
            ch = cands[0]
            causal = any((l.get("attributes") or {}).get("version") == ch["version"] for l in self.logs if l["service"] == ch["service"])
            code = f"deploy:{ch['service']}@{ch['version']}" if ch["type"] == "deployment" else f"config:{ch['service']}:{ch['version']}"
            return {"code": code, "description": ch["description"], "status": "provável" if causal else "hipótese",
                    "alternatives": ["variação de carga", "dependência externa"],
                    "evidence_against": [] if causal else ["sem identificador de versão nos erros"]}
        if cands or net:
            return {"code": None, "description": "múltiplas mudanças/eventos concorrentes", "status": "hipótese",
                    "alternatives": [f"{c['type']} {c['service']} {c['version']}: {c['description']}" for c in cands] + [f"evento de rede: {e['title']}" for e in net],
                    "evidence_against": ["candidatos simultâneos impedem atribuição"]}
        return {"code": None, "description": "nenhuma mudança, incidente ou evento correlacionado", "status": "indeterminada",
                "alternatives": ["dependência externa", "variação de carga"], "evidence_against": []}


def _simple(status: str, description: str, alternatives: list[str]) -> dict[str, Any]:
    return {"code": None, "description": description, "status": status, "alternatives": alternatives,
            "evidence_against": ["sem identificador causal que comprove a relação"]}


def _rate(errs, hits, start, a, b) -> float:
    nums = [MetricPoint("errors", _ts(start, i), errs[i], "count", "svc", None, None, (), "metric") for i in range(a, b)]
    dens = [MetricPoint("hits", _ts(start, i), hits[i], "count", "svc", None, None, (), "metric") for i in range(a, b)]
    try:
        return calculate_rate(nums, dens)
    except MetricCalculationError:
        return 0.0


SEVERITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def prioritize(findings: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(f):
        return (SEVERITY_RANK[f["severity"]], 0 if f["state"] == "PROBLEMA_ATUAL" else 1,
                0 if f["impact"] == "observado" else 1, 0 if f["silent"] else 1, f["resource"])
    out = sorted(findings, key=key)
    for i, f in enumerate(out, 1):
        f["priority_rank"] = i
    return out
