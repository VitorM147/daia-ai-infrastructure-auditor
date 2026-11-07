# Histórico de regressões — suíte comportamental DAIA

Registro append-only. Entradas automáticas são escritas pelo executor quando uma execução é gravada com `--record` e existe execução anterior do mesmo agente. Entradas manuais registram mudanças da própria suíte.

## 2026-11-06 — golden-v1 retirado (mudança da suíte, manual)
- O primeiro rascunho da Implementação 07 (`behavioral.py`, `golden_dataset.json`, 20 casos) colocava na telemetria os próprios campos de resposta (`problems`, `severity`, `cause`, `cause_confirmed`), e o "baseline" apenas os copiava para a saída. Isso tornava precisão e recall circulares (sempre 100%) e não avaliava comportamento.
- Substituído por `golden-v2` (telemetria bruta servida por sandbox, respostas só no bloco `expected`, verificação automática de vazamento) e pelo executor `daia/evals/framework/runner.py`.
- Resultados anteriores do golden-v1 não são comparáveis e não devem ser citados como medida do DAIA.

## 2026-11-06 — defeito encontrado pela suíte no agente de referência (manual)
- Cenário `inc-011-jira-timeout` (EVAL-010): D09 FAIL "esperada exatamente 1 issue; criadas 0". O agente de referência só acionava a etapa Jira quando o texto continha "jira"; o comando `CRIAR ATIVIDADES APROVADAS` não era reconhecido.
- Corrigido em `agents/reference.py` (ref-1.0.0) antes da primeira execução registrada.

## 20261107T020306Z_daia-reference-rules vs 20261107T020301Z_daia-reference-rules
- Agente: daia-reference-rules ref-1.0.0 (anterior ref-1.0.0)
- Decisão do gate: **PASS_PENDING_HUMAN_REVIEW**
- Regressões de cenário: 0
- Novas violações críticas: 0
- Correções: nenhuma

## 20261107T022645Z_daia-reference-rules vs 20261107T020306Z_daia-reference-rules
- Agente: daia-reference-rules ref-1.0.0 (anterior ref-1.0.0)
- Decisão do gate: **PASS_PENDING_HUMAN_REVIEW**
- Regressões de cenário: 0
- Novas violações críticas: 0
- Correções: nenhuma

## 2026-11-06 — defeitos do orquestrador (V4-08) encontrados pela suíte antes da primeira execução registrada (manual)
- 30/30 cenários com ERROR (`TypeError`): flag do catálogo de métricas gravada dentro do mapa de cobertura. Corrigido.
- `inc-014-partial-audit`: ERROR ao registrar a interrupção (conflito de argumento no log de eventos) e falha de ferramenta que causou a interrupção não exibida ao humano (D14 crítico). Corrigido.
- `inc-016-rate-limit-auth`: D14 "2 tentativas após 429" — o orquestrador respeitava o 429 por consulta, mas continuava chamando a mesma ferramenta com outros argumentos. Corrigido com bloqueio por ferramenta (circuit breaker) até o Retry-After; 401/403 bloqueiam a ferramenta pelo resto da sessão.
- Permanece: `inc-015-sensitive-data` D06 (causa `provável` vs especificação `hipótese/indeterminada`), mesma divergência do agente de referência, aguardando decisão humana sobre a especificação.

