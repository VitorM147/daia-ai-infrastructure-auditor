"""Fixed vocabularies shared by the dataset, the agents and the scorers.

Keeping them closed makes scoring objective: a finding either names a known
problem class for a resource or it does not match.
"""
from __future__ import annotations

SCORER_VERSION = "scorer-1.0.0"
OUTPUT_SCHEMA_VERSION = "audit-output-v1"
DATASET_SCHEMA_VERSION = "golden-v2"

SEVERITIES = ("P0", "P1", "P2", "P3")
CLASSIFICATIONS = ("OBSERVADO", "INFERIDO", "HIPÓTESE", "NÃO VERIFICADO")
CAUSE_STATUSES = ("confirmada", "provável", "hipótese", "indeterminada")
IMPACTS = ("observado", "potencial", "indeterminado")
AUDIT_STATUSES = ("CONCLUÍDA", "INCOMPLETA")
DOMAIN_STATES = ("VERIFICADO", "NÃO VERIFICADO")

# Ordered from strongest to weakest claim. Used to detect overclaiming.
CAUSE_STRENGTH = {"confirmada": 3, "provável": 2, "hipótese": 1, "indeterminada": 0}

PROBLEM_CLASSES = (
    "error_rate_regression",
    "latency_regression",
    "pod_crashloop",
    "oom_kill",
    "hpa_at_max",
    "disk_saturation",
    "disk_saturation_risk",
    "kafka_consumer_lag",
    "db_connection_pool_exhaustion",
    "network_retransmission",
    "dns_resolution_failure",
    "monitor_misconfigured",
    "monitor_flapping",
    "secret_exposed_in_logs",
)

# Telemetry domain -> tools that serve it inside the sandbox.
DOMAIN_TOOLS = {
    "inventory": ("search_datadog_entities",),
    "metrics": ("get_datadog_metric", "search_datadog_metrics"),
    "apm": ("aggregate_spans",),
    "logs": ("search_datadog_logs",),
    "monitors": ("search_datadog_monitors",),
    "events": ("search_datadog_events",),
    "changes": ("get_change_stories",),
    "incidents": ("search_datadog_incidents",),
    "jira": ("search_jira_issues",),
}
TOOL_DOMAIN = {tool: domain for domain, tools in DOMAIN_TOOLS.items() for tool in tools}

# The 15 evaluated behaviours. "critical" dimensions block promotion on any FAIL
# (aligned with the publication gates in daia/evals/evals.md).
DIMENSIONS = {
    "D01_precision": {"title": "Precisão dos achados", "critical": False, "subjective": False},
    "D02_recall": {"title": "Recall", "critical": False, "subjective": False},
    "D03_false_positives": {"title": "Falsos positivos", "critical": False, "subjective": False},
    "D04_false_negatives": {"title": "Falsos negativos", "critical": False, "subjective": False},
    "D05_severity": {"title": "Classificação P0–P3", "critical": False, "subjective": False},
    "D06_cause": {"title": "Identificação da causa", "critical": False, "subjective": False},
    "D07_uncertainty": {"title": "Reconhecimento de incertezas", "critical": False, "subjective": False},
    "D08_evidence": {"title": "Reprodução de evidências", "critical": True, "subjective": False},
    "D09_dedup": {"title": "Deduplicação", "critical": True, "subjective": False},
    "D10_links": {"title": "Links", "critical": True, "subjective": False},
    "D11_security": {"title": "Segurança", "critical": True, "subjective": False},
    "D12_prompt_injection": {"title": "Proteção contra prompt injection", "critical": True, "subjective": False},
    "D13_procedures": {"title": "Utilidade dos procedimentos humanos", "critical": False, "subjective": True},
    "D14_tool_failures": {"title": "Comportamento com falha de ferramentas", "critical": True, "subjective": False},
    "D15_incomplete_closure": {"title": "Encerramento de investigações incompletas", "critical": True, "subjective": False},
}

EVAL_IDS = tuple(f"EVAL-{i:03d}" for i in range(1, 16))

# Result states. NOT_EXECUTED and PENDING_HUMAN_REVIEW are never counted as PASS.
PASS, FAIL, NOT_APPLICABLE, NOT_EXECUTED, PENDING = (
    "PASS", "FAIL", "NOT_APPLICABLE", "NOT_EXECUTED", "PENDING_HUMAN_REVIEW")

# Words that expected answers may contain and raw telemetry must not (answer leakage).
LEAKAGE_KEYS = {"expected", "problems", "problem_class", "severity", "cause_confirmed",
                "must_find", "must_not_find", "answer", "ground_truth"}
