"""Render structured findings into detailed human-run guides."""
from __future__ import annotations

from .models import FindingGuide


def _bullets(items: tuple[str, ...]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- NÃO VERIFICADO"


def render_guide(guide: FindingGuide) -> str:
    steps = []
    for step in guide.investigation_steps:
        label = "SOMENTE LEITURA" if step.read_only else "ALTERAÇÃO — EXECUÇÃO HUMANA — NÃO EXECUTAR PELO AGENTE"
        steps.append(f"| {step.number} | {step.objective} | {step.interface} · {step.location} | `{step.command_or_query}`<br>{label} | {step.expected} | {step.interpretation} | {step.if_different} |")
    options = []
    for option in guide.resolution_options:
        options.append(f"### Opção: {option.name}\n- **Ação:** {option.action}\n- **Por que:** {option.why}\n- **Pré-requisitos:** {_bullets(option.prerequisites)}\n- **Riscos/efeitos colaterais:** {_bullets(option.risks)}\n- **Aprovação:** {option.approval}\n- **Execução manual:**\n\n> **EXECUÇÃO HUMANA — NÃO EXECUTAR PELO AGENTE**\n> `{option.manual_command}`\n\n- **Validação:** {option.validation}\n- **Condição de parada:** {option.stop_condition}\n- **Rollback:** {option.rollback}")
    return f"""# {guide.finding_id} — {guide.title}

## Camada executiva
- **Problema:** {guide.executive_summary}
- **Prioridade/status:** {guide.priority} / {guide.status}
- **Impacto no negócio:** {guide.business_impact}
- **Equipe:** {guide.team} ({guide.team_validation})
- **Jira:** {guide.jira_status}

## IDENTIFICAÇÃO
- **Ambiente:** {guide.environment}
- **Serviço:** {guide.service}
- **Recurso:** {guide.resource}
- **Timestamp:** {guide.analysis_timestamp}
- **Janela:** {guide.analysis_window}
- **Fingerprint:** `{guide.fingerprint}`

## EVIDÊNCIAS
{_bullets(guide.evidence)}

### Métricas e consultas
{_bullets(guide.metrics_queries)}

### Logs sanitizados
{_bullets(guide.sanitized_logs)}

### Traces
{_bullets(guide.traces)}

### Eventos, mudanças e histórico
{_bullets(guide.events_changes)}
{_bullets(guide.history)}

### Alertas relacionados
{_bullets(guide.alerting)}

### Links diretos
{_bullets(guide.links)}

## DIAGNÓSTICO
- **Sintomas:**\n{_bullets(guide.symptoms)}
- **Comportamento esperado:** {guide.expected_behavior}
- **Comportamento anormal:** {guide.abnormal_behavior}
- **Causas possíveis:**\n{_bullets(guide.causes)}
- **Evidências a favor:**\n{_bullets(guide.evidence_for)}
- **Evidências contra:**\n{_bullets(guide.evidence_against)}
- **Hipóteses alternativas:**\n{_bullets(guide.alternatives)}
- **Confiança:** {guide.confidence}
- **Não verificado:**\n{_bullets(guide.unverified)}

## GUIA DE INVESTIGAÇÃO HUMANA — SOMENTE LEITURA

| # | Objetivo | Interface · Onde | Comando/consulta | Esperado | Interpretação | Se diferente |
|---|---|---|---|---|---|---|
{''.join(steps)}

## CORREÇÃO — EXECUÇÃO HUMANA

Nenhuma opção deve ser executada pelo agente. As opções abaixo são condicionais ao diagnóstico e exigem aprovação humana.

{chr(10).join(options) if options else "NÃO VERIFICADO — não há resolução segura suficiente."}

## VALIDAÇÃO PÓS-CORREÇÃO E ACEITE
{_bullets(guide.post_validation)}

## PREVENÇÃO E ACOMPANHAMENTO
{_bullets(guide.prevention)}

## ENCAMINHAMENTO
- **Jira:** {guide.jira_status}
- **Duplicidade:** NÃO VERIFICADO sem acesso ao Jira; pesquisar pelo fingerprint antes de criar.
"""
