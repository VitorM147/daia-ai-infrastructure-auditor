# DAIA V5.1 — Documentation-Driven SRE Intelligence

Camada de inteligência **independente e somente leitura** sobre o orquestrador existente. Não copia o Datadog:
interpreta dados já coletados por caminhos autorizados e produz **recomendações**. Nada é criado, alterado ou ativado.

## Módulos

| Pacote | Função | Rede | Escreve arquivos |
|---|---|---|---|
| `docs_intel/` | Catálogo de 15 regras com fonte oficial, verificação de atualidade, cache de índices `llms.txt` | só `cli.py`, sob demanda | só catálogo/cache locais |
| `logintel/` | Mascaramento local, padrões, deduplicação, uso/projeção, cotas, candidatos a exclusão | não | não |
| `patterns/` | Sazonalidade, instância fora do padrão, crescimento contínuo, deploy, hipótese | não | não |
| `costgov/` | Classificação de custo (R$ 0 incremental) | não | não |
| `gaps/` | Lint de queries, matriz de cobertura, propostas de monitor/dashboard, conformidade | não | não |
| `alertnoise/` | Deduplicação, agrupamento, cooldown, agravamento, decisão de notificar | não | não |
| `integrated/` | Enriquecedor do orquestrador (checkpoint e retomada herdados) | não | não |
| `qualitygate/` | Gates de segurança, custo e qualidade dos detectores | não | não |

## Como usar

```powershell
# conhecimento documental (offline)
python -m daia.docs_intel.cli status
# verificação sob demanda, com orçamento de requisições (só docs.datadoghq.com)
python -m daia.docs_intel.cli verify --budget 5 --write
python -m daia.docs_intel.cli index  --budget 20 --write
# auditoria com a camada V5.1 (enriquecedor opcional; vazio por padrão)
#   AuditOrchestrator(..., enrichers=[daia.integrated.audit.make_enricher(indexes=[...])])
# métricas dos detectores em casos sintéticos
python -m daia.qualitygate.report_metrics
```

## Regras que o código impõe (e os testes provam)

- Regra do catálogo só aceita `inspection=READ_ONLY` e `action=RECOMMEND_ONLY`; `APPLY/EXECUTE` não são representáveis.
- Catálogo **nunca** afirma `CUSTO_ZERO_CONFIRMADO`; isso exige validação humana de contrato (`costgov`).
- Produto cobrado à parte (Sensitive Data Scanner, Audit Trail, Flex Logs, Synthetics, RUM…) é sempre `RECURSO_PAGO` e bloqueado.
- Criar monitor/dashboard/índice/filtro/métrica sem validação contratual é `BLOQUEADO_POR_CUSTO`.
- HTTP 429 interrompe a verificação, sem retry. Orçamento de requisições é obrigatório.
- Hipótese sem evidência contrária, alternativas, método e limitações é rebaixada para `NAO_VERIFICADO`.
- Ausência de monitor só é reportada como lacuna se o inventário de monitores estiver completo.
- Candidato a exclusão de logs nunca inclui erro, segurança, pagamento ou auditoria.

## O que NÃO é

Não há coletor Datadog ao vivo neste pacote. As funções recebem dados já coletados. Métricas dos detectores
(`qualitygate`) vêm de **fixtures sintéticos rotulados pelos autores** e não representam precisão em produção.
