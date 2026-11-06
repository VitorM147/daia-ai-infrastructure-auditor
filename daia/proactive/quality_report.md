# Relatório de qualidade — Proactive SRE Intelligence

## Implementado

- catálogo com 14 verificações preventivas;
- tendência linear determinística com cobertura mínima;
- baseline operacional reaproveitável pelo pacote `daia.diagnostics`;
- classificação separada entre problema atual e risco futuro;
- estado explícito para telemetria insuficiente;
- intervalo de incerteza para estimativas de esgotamento;
- ações preventivas e indicadores de acompanhamento como campos obrigatórios da avaliação;
- nenhuma remediação automática.

## Garantias

O motor não transforma uma tendência em incidente atual. Um valor acima do limiar é `PROBLEMA_ATUAL`; um valor abaixo com tendência positiva é `RISCO_FUTURO`. Amostra parcial, série curta ou telemetria insuficiente não produz previsão.

## Não implementado neste pacote

- coleta real do Datadog;
- seasonalidade automática além do campo de cobertura disponível no diagnóstico;
- modelo probabilístico calibrado;
- previsão de prazo sem dados suficientes;
- criação ou atualização de Jira;
- execução automática de remediação;
- validação externa de contratos, certificados ou ownership.

Não há base para afirmar redução quantitativa de incidentes ou falsos positivos. A medição precisa usar um golden dataset e revisão humana.
