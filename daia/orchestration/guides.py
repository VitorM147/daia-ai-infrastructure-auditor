"""Human investigation/resolution guides built with daia.resolution and validated."""
from __future__ import annotations

from typing import Any, Mapping

from daia.resolution.generator import render_guide
from daia.resolution.models import FindingGuide, InvestigationStep, ResolutionOption
from daia.resolution.validator import validate_guide

LABEL = "EXECUÇÃO HUMANA — NÃO EXECUTAR PELO AGENTE"

# action, risks, rollback, validation, alternatives
TEMPLATES: dict[str, tuple[str, list[str], str, str, list[str]]] = {
    "error_rate_regression": ("Se a regressão coincidir com deploy confirmado, avaliar rollback pela esteira aprovada.",
                              ["rollback pode reverter correções de dados/migrações"], "Reaplicar a versão anterior ao rollback",
                              "Taxa de erro volta ao baseline por 2h", ["Feature flag para desativar o código novo", "Mitigar na dependência"]),
    "latency_regression": ("Identificar endpoint/dependência com maior contribuição e escalar ao time dono.",
                           ["mudar timeouts pode mascarar o problema"], "Restaurar configuração anterior", "p95 volta ao baseline",
                           ["Aumentar capacidade temporariamente com aprovação"]),
    "disk_saturation": ("Restaurar a política de retenção/rotação anterior via processo de mudança aprovado.",
                        ["perda de dados se a retenção ficar abaixo do exigido por consumidores/compliance", "não apagar segmentos manualmente"],
                        "Reverter a configuração de retenção", "Uso de disco estabiliza abaixo de 85%",
                        ["Expandir o volume temporariamente", "Rebalancear partições"]),
    "disk_saturation_risk": ("Planejar expansão ou ajuste de retenção antes do limiar, com o dono do serviço.",
                             ["expansão tem custo; retenção menor pode afetar consumidores"], "Reverter ajuste", "Projeção acima de 30 dias",
                             ["Arquivar dados frios"]),
    "hpa_at_max": ("Avaliar aumento de maxReplicas ou de recursos com o time dono, conforme capacidade do cluster.",
                   ["mais réplicas pressionam nós e banco"], "Restaurar maxReplicas anterior", "Réplicas abaixo do máximo e CPU abaixo do alvo",
                   ["Otimizar o endpoint mais custoso", "Cache"]),
    "oom_kill": ("Analisar crescimento de memória (heap/profile) antes de alterar limites; ajustar limite só com aprovação.",
                 ["aumentar limite sem corrigir vazamento apenas adia o OOM"], "Restaurar limite anterior", "Zero OOMKilled por 24h",
                 ["Rollback da última versão se houver correlação"]),
    "pod_crashloop": ("Corrigir a configuração/dependência ausente indicada nos logs de saída pela esteira aprovada.",
                      ["reinícios em massa podem ampliar o impacto"], "Reverter a configuração alterada", "Pods Ready sem reinícios por 1h",
                      ["Rollback do deploy"]),
    "kafka_consumer_lag": ("Verificar saúde e número de consumidores; escalar consumidores só com aprovação do time dono.",
                           ["rebalance causa pausa temporária"], "Restaurar número anterior de consumidores", "Lag decrescente por 2h",
                           ["Investigar mensagens venenosas/retentativas"]),
    "db_connection_pool_exhaustion": ("Restaurar o tamanho de pool anterior via mudança aprovada, respeitando max_connections do banco.",
                                      ["pool grande demais pode esgotar o banco"], "Reverter configuração do pool",
                                      "Erros de aquisição zerados e pool < 80%", ["Reduzir retenção de conexões", "Réplicas de leitura"]),
    "network_retransmission": ("Abrir chamado com rede/provedor com as evidências; avaliar drenar o host do balanceador com aprovação.",
                               ["drenar reduz capacidade"], "Reinserir o host", "Razão de retransmissão no baseline", ["Trocar instância/NIC"]),
    "dns_resolution_failure": ("Validar resolvedores e TTL; acionar parceiro/provedor DNS.", ["cache longo pode reter IP inválido"],
                               "Remover cache temporário", "Zero EAI_AGAIN por 1h", ["Resolvedor secundário"]),
    "monitor_misconfigured": ("Corrigir a query do monitor para a métrica existente via processo do time de observabilidade.",
                              ["monitor corrigido pode disparar imediatamente"], "Restaurar query anterior", "Monitor sai de No Data",
                              ["Monitor composto temporário"]),
    "monitor_flapping": ("Ajustar janela/limiar ou adicionar histerese pelo dono do monitor (não silenciar sem análise).",
                         ["limiar frouxo pode esconder degradação real"], "Restaurar configuração anterior", "Menos de 5 trocas de estado/24h",
                         ["Monitor de anomalia com baseline"]),
    "secret_exposed_in_logs": ("Rotacionar a credencial exposta e aplicar mascaramento no logger; restringir acesso aos índices afetados.",
                               ["rotação pode interromper integrações"], "Reativar credencial anterior só em emergência aprovada",
                               "Nenhum novo log com padrão sensível por 24h", ["Regra de scrubbing no pipeline de logs"]),
}


def navigation(f: Mapping[str, Any]) -> str:
    pc, res, svc = f["problem_class"], f["resource"], f.get("service")
    if pc in ("error_rate_regression", "latency_regression"):
        return f"Datadog > APM > Service Catalog > {res} > env:{f['environment']}, últimas 6h; comparar com 'Week before'."
    if pc in ("oom_kill", "pod_crashloop", "hpa_at_max"):
        return f"Datadog > Infrastructure > Kubernetes > Workloads > {res.split('/')[0]} > Events/Containers (últimas 6h)."
    if pc.startswith("monitor_"):
        return f"Datadog > Monitors > Manage Monitors > id {res.split(':')[-1]} > Status/History."
    if pc.startswith("disk_"):
        return f"Datadog > Infrastructure > Host Map > host {res.split(':')[0]} > system.disk.in_use por device (7 dias)."
    if pc == "network_retransmission":
        return f"Datadog > Metrics > Explorer > system.net.tcp.retrans_segs / system.net.tcp.out_segs, host:{res}, 7 dias."
    if pc == "kafka_consumer_lag":
        return f"Datadog > Metrics > Explorer > kafka.consumer_lag, consumer_group:{res}, 7 dias."
    if pc == "db_connection_pool_exhaustion":
        return f"Datadog > Metrics > Explorer > db.pool.active, db:{res}; Logs > service:{svc} 'pool'."
    return f"Datadog > Logs > service:{svc or res} env:{f['environment']} (últimas 6h)."


def procedure(f: Mapping[str, Any]) -> dict[str, Any]:
    action, risks, rollback, validation, alts = TEMPLATES[f["problem_class"]]
    return {"diagnostic_steps": [
                {"text": f"Confirmar o sinal no Datadog para {f['resource']} na mesma janela e comparar com período equivalente.", "read_only": True},
                {"text": "Verificar mudanças, incidentes e dependências na janela; registrar evidências a favor e contra.", "read_only": True}],
            "resolution_steps": [{"text": action, "human_execution_label": True, "label": LABEL, "risks": risks,
                                  "rollback": rollback, "validation": validation}],
            "alternatives": alts}


def build_guide(f: Mapping[str, Any], *, audit_id: str, window: str, at_utc: str, history: Mapping[str, Any] | None,
                jira_status: str) -> tuple[str, list[str]]:
    action, risks, rollback, validation, alts = TEMPLATES[f["problem_class"]]
    cause = f["cause"]
    guide = FindingGuide(
        finding_id=f["fingerprint"][-8:], title=f"{f['problem_class']} — {f['resource']}", priority=f["severity"],
        status=f["state"], environment=f["environment"], service=f.get("service") or "Não verificado", resource=f["resource"],
        team="Não verificado", team_validation="sem evidência de ownership", analysis_timestamp=at_utc, analysis_window=window,
        fingerprint=f["fingerprint"], executive_summary=f["summary"],
        business_impact=f"Impacto {f['impact']}; não quantificado.",
        evidence=tuple(f"{e.get('note', '')}: {e.get('value')} (chamada {e.get('call_id')})" for e in f["evidence"]),
        metrics_queries=tuple(f"{c['name']} = {c['value']:.6g} ({c['op']})" for c in f.get("computed", [])),
        sanitized_logs=("Logs não reproduzidos; ver navegação manual.",), traces=("Não verificado",),
        events_changes=(cause["description"],),
        history=(f"Ocorrências anteriores: {history['occurrences']} (primeira em {history['first_seen_utc']})",) if history else ("Sem registro anterior",),
        alerting=("Falha silenciosa: nenhum monitor em alerta" if f["silent"] else "Ver monitores vinculados",),
        links=tuple(l["url"] + " (não validado)" for l in f["links"]) or (f"Caminho manual: {navigation(f)}",),
        symptoms=(f["summary"],), expected_behavior="Sinal dentro do baseline do mesmo período", abnormal_behavior=f["summary"],
        causes=(f"{cause['status']}: {cause['description']}",), evidence_for=tuple(e.get("note", "") for e in f["evidence"]),
        evidence_against=tuple(cause.get("evidence_against") or ["Não verificado"]), alternatives=tuple(cause.get("alternatives") or alts),
        confidence=f"classificação {f['classification']}; causa {cause['status']}",
        unverified=("Equipe responsável", "Impacto de negócio quantificado"),
        investigation_steps=(
            InvestigationStep(1, "Confirmar o sinal", "Datadog", navigation(f), "mesma consulta da evidência", "valor anormal",
                              "confirma o achado", "registrar divergência e reavaliar", True),
            InvestigationStep(2, "Verificar mudanças e dependências", "Datadog", "Events / Change Tracking", "janela da auditoria",
                              "mudança correlacionada", "reforça hipótese", "manter causa indeterminada", True)),
        resolution_options=(ResolutionOption("Opção principal", action, "Endereça a causa mais provável sem ação destrutiva padrão",
                                             ("Aprovação do time dono",), tuple(risks), "Responsável técnico do serviço",
                                             "conforme runbook do serviço", validation, "Interromper se o indicador piorar", rollback),),
        post_validation=(validation,), prevention=tuple(alts), jira_status=jira_status,
    )
    text = render_guide(guide)
    result = validate_guide(text)
    return text, list(result.errors)
