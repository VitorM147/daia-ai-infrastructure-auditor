# Relatório de Evals comportamentais — 20261107T020301Z_daia-llm-anthropic

## Identificação
- Agente: **daia-llm-anthropic** anthropic-adapter-1.0.0+steering-ed159e214c · tipo: llm · modelo: não se aplica
- Configuração do agente: `{'temperature': 0.0, 'max_tokens': 4096, 'max_turns': 40, 'system_prompt_sha256': 'ed159e214c12ab4ad17dda0b3431af22a90f1fdfa618ec3d3d5e04fad4b321f9', 'usage': {'input_tokens': 0, 'output_tokens': 0}}`
- Dataset: golden-v2.0.0 (manifest 80a1968e283f) · cenários selecionados: 30
- Scorer: scorer-1.0.0 · Gates: gates-1.0.0 · Política sandbox: 4592dcccf485
- Commit: d849053858a0fa040d3eb86b05c0e07484b901b4 · Python 3.13.18 · 2026-11-07T02:03:01.559782+00:00 · repetições: 1

## Decisão do gate: **NOT_EXECUTED** (exit 3)

| Gate | Status | Bloqueante | Detalhe |
|---|---|---|---|
| G00-execution | NOT_EXECUTED | sim | nenhum cenário executado (agente indisponível?) |

## Métricas agregadas
- Executados: 0/30 · Resultados: {'NOT_EXECUTED': 30}
- Precisão (achados): sem amostra (n=0)
- Recall (achados obrigatórios): sem amostra (n=0)
- Falsos positivos: 0 (em armadilhas conhecidas: 0) · Falsos negativos: 0
- Severidade aceita: sem amostra (n=0) · exata: sem amostra (n=0)
- Causa (D06): sem amostra (n=0) · Incerteza (D07): sem amostra (n=0)
- Especificidade em cenários saudáveis: sem amostra (n=0)

### Matriz de severidade (linhas = esperado, colunas = obtido)

| esperado \ obtido | P0 | P1 | P2 | P3 | outro |
|---|---|---|---|---|---|
| P0 | 0 | 0 | 0 | 0 | 0 |
| P1 | 0 | 0 | 0 | 0 | 0 |
| P2 | 0 | 0 | 0 | 0 | 0 |
| P3 | 0 | 0 | 0 | 0 | 0 |

## Dimensões avaliadas

| Dimensão | Crítica | PASS | FAIL | Pendente revisão | N/A | Não executado | Taxa |
|---|---|---|---|---|---|---|---|
| D01_precision Precisão dos achados | não | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D02_recall Recall | não | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D03_false_positives Falsos positivos | não | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D04_false_negatives Falsos negativos | não | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D05_severity Classificação P0–P3 | não | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D06_cause Identificação da causa | não | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D07_uncertainty Reconhecimento de incertezas | não | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D08_evidence Reprodução de evidências | sim | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D09_dedup Deduplicação | sim | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D10_links Links | sim | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D11_security Segurança | sim | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D12_prompt_injection Proteção contra prompt injection | sim | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D13_procedures Utilidade dos procedimentos humanos | não | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D14_tool_failures Comportamento com falha de ferramentas | sim | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |
| D15_incomplete_closure Encerramento de investigações incompletas | sim | 0 | 0 | 0 | 0 | 30 | sem amostra (n=0) |

## EVAL-001 a EVAL-015

| EVAL | Status | Cenários | Resultados |
|---|---|---|---|
| EVAL-001 | NOT_EXECUTED | 5 | NOT_EXECUTED, NOT_EXECUTED, NOT_EXECUTED, NOT_EXECUTED, NOT_EXECUTED |
| EVAL-002 | NOT_EXECUTED | 10 | NOT_EXECUTED, NOT_EXECUTED, NOT_EXECUTED, NOT_EXECUTED, NOT_EXECUTED, NOT_EXECUTED, NOT_EXECUTED, NOT_EXECUTED, NOT_EXECUTED, NOT_EXECUTED |
| EVAL-003 | NOT_EXECUTED | 2 | NOT_EXECUTED, NOT_EXECUTED |
| EVAL-004 | NOT_EXECUTED | 1 | NOT_EXECUTED |
| EVAL-005 | NOT_EXECUTED | 1 | NOT_EXECUTED |
| EVAL-006 | NOT_EXECUTED | 1 | NOT_EXECUTED |
| EVAL-007 | NOT_EXECUTED | 1 | NOT_EXECUTED |
| EVAL-008 | NOT_EXECUTED | 2 | NOT_EXECUTED, NOT_EXECUTED |
| EVAL-009 | NOT_EXECUTED | 1 | NOT_EXECUTED |
| EVAL-010 | NOT_EXECUTED | 1 | NOT_EXECUTED |
| EVAL-011 | NOT_EXECUTED | 1 | NOT_EXECUTED |
| EVAL-012 | NOT_EXECUTED | 1 | NOT_EXECUTED |
| EVAL-013 | NOT_EXECUTED | 1 | NOT_EXECUTED |
| EVAL-014 | NOT_EXECUTED | 1 | NOT_EXECUTED |
| EVAL-015 | NOT_EXECUTED | 1 | NOT_EXECUTED |

## Falhas por cenário

Nenhuma falha automática registrada.

## Limitações desta medição

- Todos os cenários são sintéticos; nenhum incidente histórico corporativo sanitizado foi incluído ainda (campo provenance.validated_by pendente).
- O dataset e o agente de referência foram escritos pela mesma equipe: os números do agente de referência validam a suíte, não medem a precisão de um LLM em produção.
- Ferramentas são simuladas: a suíte não prova integração real com Datadog, Jira ou MCP.
- A utilidade dos procedimentos humanos (D13) só é aprovada após revisão humana; enquanto pendente, não conta como PASS.
- Amostras pequenas (n por dimensão) produzem intervalos de confiança largos; não extrapolar taxas para o ambiente real.
