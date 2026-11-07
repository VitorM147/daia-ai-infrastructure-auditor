# DAIA V4 — Autonomous Audit Orchestration (Implementação 08)

Orquestrador que executa auditorias completas e repetíveis, sob demanda ou disparadas por um agendador externo autorizado. Ele **não** encerra a auditoria nos primeiros achados, registra checkpoints em disco, para de forma limpa quando um limite é atingido e retoma apenas o que falta. Uma auditoria só é `CONCLUÍDA` quando todos os critérios abaixo são cumpridos; caso contrário fica `INCOMPLETA` com os critérios não atendidos listados.

## Fluxo (15 etapas)

| # | Etapa | Faz consultas | O que registra |
|---|---|---|---|
| 01 | Discovery | catálogo de métricas (paginado) | escopo, catálogo completo ou não |
| 02 | Inventário | entidades (paginado) | serviços, workloads, Kafka, bancos, hosts, volumes |
| 03 | Validação de cobertura | — | plano de recursos e consultas esperadas |
| 04 | Health Check | monitores, eventos, mudanças, incidentes, logs (paginados) | cobertura por domínio |
| 05 | Detecção de anomalias | séries por recurso, em paralelo limitado | achados, itens não confirmados |
| 06 | Investigação aprofundada | spans dos serviços com anomalia | notas de investigação |
| 07 | Correlação | — (cache) | causa: confirmada/provável/hipótese/indeterminada |
| 08 | Análise preventiva | — | riscos futuros (`RISCO_FUTURO`) |
| 09 | Priorização | — | ordem por severidade, estado, impacto, falha silenciosa |
| 10 | Verificação de histórico | — (registro local) | recorrência por fingerprint |
| 11 | Deduplicação Jira | busca por fingerprint | duplicatas / NÃO VERIFICADO |
| 12 | Guia de resolução humana | — | guia renderizado e validado por `daia.resolution` |
| 13 | Preparação das atividades | — (criação só com aprovação explícita sob demanda) | propostas Jira |
| 14 | Relatório sob demanda | — | `NÃO SOLICITADO` ou relatório final |
| 15 | Registro de progresso | — | fingerprints no registro de recorrência |

Detecção e correlação são funções puras sobre dados em cache: retomar não repete consultas para recalcular.

## Critérios de conclusão

`CONCLUÍDA` exige, ao mesmo tempo: as 15 etapas concluídas (relatório pode ser `NÃO SOLICITADO`); todo domínio planejado em `CONCLUÍDO` ou `NÃO NECESSÁRIO`; todas as consultas de métricas planejadas concluídas; nenhuma interrupção pendente. Paginação truncada, página com falha, limite de páginas, ferramenta bloqueada ou dado expirado não revalidado mantêm `INCOMPLETA`. **Nunca se conclui uma auditoria global a partir de amostra.**

## Paginação

`ToolClient.paginate` lê por cursor (`page_size`/`cursor`/`next_cursor`) ou por número de página (`page`/`total_pages`) até esgotar a fonte. Para quando atinge `max_pages_per_query` ou `max_items_per_query` e registra a parte como incompleta, com o motivo. Ampliar esses limites exige aprovação e, na retomada, só as páginas que faltam são lidas (as já lidas vêm do cache).

## Limites (`daia/config/orchestration-limits.json`)

| Limite | Padrão do projeto | Efeito |
|---|---|---|
| `max_runtime_s` | 900 | tempo por sessão |
| `max_queries` | 400 | consultas por auditoria (acumulado entre sessões) |
| `max_concurrency` | 4 | consultas de métricas em paralelo |
| `max_pages_per_query` / `page_size` / `max_items_per_query` | 15 / 200 / 3000 | volume por consulta paginada |
| `max_data_bytes` | 50 MB | volume total recebido |
| `max_tokens` / `max_cost_usd` | 0 / 0 | nenhuma etapa com LLM autorizada por padrão |
| `max_retries` / `max_backoff_s` | 1 / 60 | retentativas para 503/timeout e 429 com Retry-After ≤ 60 s |
| `max_queries_per_second` | 5 | espaçamento mínimo entre consultas |

Os valores são **padrões conservadores do projeto**, não valores corporativos (`validated_by` está nulo). Não há valor implícito: limite ausente no arquivo impede a execução. Reduzir é livre; **ampliar** (inclusive janela maior que `defaults.window_hours` ou domínio fora de `defaults.domains`) exige `ScopeApproval` com aprovador, id, data UTC e motivo, que fica registrado no checkpoint.

Falhas de ferramentas: 401/403/negação de política bloqueiam a ferramenta pelo resto da sessão (sem nova tentativa); 429 com Retry-After acima de `max_backoff_s` também bloqueia até o prazo; nada é contornado.

## Checkpoints e retomada

Por auditoria, em `daia/audits/<audit_id>/` (ignorado pelo Git):

- `checkpoint.json` — ID, ambiente, janela UTC, domínios planejados e concluídos, etapas, ferramentas usadas, consultas executadas, páginas recuperadas, limitações, achados, estado, consumo, sessões, interrupção e último checkpoint. Gravação atômica.
- `queries/<chave>.json` — resposta de cada consulta (cache com `collected_at`).
- `events.jsonl` — trilha append-only (início, retentativas, bloqueios, interrupção, retomada, revalidação).
- `guides/<fingerprint>.md` — guias humanos; `report.md` quando solicitado.

O checkpoint é salvo antes e depois de cada etapa e a cada 10 consultas de métricas. Em interrupção por limite, perda de conexão, erro ou Ctrl+C, o estado vai para `INCOMPLETA` com `interruption` preenchido.

Na retomada (`resume`):
1. etapas concluídas com dados válidos **não** são reexecutadas;
2. consultas já respondidas e dentro do TTL do domínio (`staleness_ttl_s`) vêm do cache — sem consulta duplicada;
3. dados expirados são revalidados: a etapa que os coletou e as seguintes voltam a `PENDENTE`;
4. leituras parciais não bloqueadas são tentadas de novo;
5. o status continua `INCOMPLETA` até cumprir todos os critérios.

## Memória

`daia/findings/registry.json` (ignorado pelo Git) guarda fingerprint, primeira/última ocorrência, número de auditorias e última severidade. A etapa 10 marca recorrência a partir desse arquivo; nada depende do histórico de conversa do LLM.

## Modo preventivo (agendado)

O agendador apenas dispara o comando com a mesma credencial somente leitura e a mesma política. O modo `preventive`:
- ignora qualquer aprovação de criação Jira (gera só propostas) e registra a limitação;
- registra o gatilho (`trigger.type=scheduler`, `id`, `requested_by`) no checkpoint;
- não amplia limites nem escopo.

Exemplos de disparo (o agendador é externo e precisa ser autorizado pela organização):

```text
# cron (Linux)
17 6 * * 1-5  cd /opt/daia && python -m daia.orchestration.cli start --environment prod --source export:/dados/evidencias.json --mode preventive --trigger-id cron-diario --requested-by svc-daia-scheduler
```

```powershell
# Agendador de Tarefas do Windows
powershell -File daia/orchestration/run-audit.ps1 -Environment prod -Source export:C:\daia\evidencias.json -Preventive -TriggerId tarefa-diaria
```

## Uso

```powershell
python -m daia.orchestration.cli start --environment prod --source export:evidencias.json --report
python -m daia.orchestration.cli status <audit_id>
python -m daia.orchestration.cli resume <audit_id> --source export:evidencias.json
python -m daia.orchestration.cli resume <audit_id> --source ... --limit max_queries=800 --approve-expansion "sre-lead,APR-12,2026-11-07T12:00:00Z,auditoria trimestral"
python -m daia.orchestration.cli report <audit_id>     # relatório em daia/reports/ (só quando pedido)
python -m daia.orchestration.cli list
```

Códigos de saída: 0 `CONCLUÍDA` · 4 `INCOMPLETA` · 1 erro de uso ou bloqueio por política.

### Fontes

- `export:<arquivo.json>` — pacote exportado por coletor autorizado: `{"environment", "collected_until_utc", "telemetry": {...}}` no mesmo formato da telemetria do Golden Dataset. Usa a allowlist de produção (`daia/config/tool-allowlist.json`); como ela não lista busca Jira, o domínio `jira` fica `BLOQUEADO` quando houver achados P0–P2 (exclua com `--domains` se a deduplicação for feita fora do DAIA).
- `sandbox:<cenário>` — cenário do Golden Dataset (testes e demonstração).
- MCP/API ao vivo: implemente uma função `port(tool, args) -> {"ok", "data", "error", "call_id"}` que despache pela integração somente leitura **depois** de `ToolGuard.authorize` e passe-a ao `AuditOrchestrator`. Esse adaptador não está incluído porque depende do MCP/credenciais da organização.

## O que a pessoa recebe

`human_summary` / `report.md`: cobertura real por domínio, problemas identificados, problemas não confirmados, riscos futuros, investigações pendentes, propostas Jira (aguardando aprovação), falhas de ferramentas, limitações e próximos passos.

## Avaliação

O orquestrador é avaliado pela suíte da Implementação 07 como agente `orchestrator`:

```powershell
python -m daia.evals.framework.runner run --agent orchestrator --record
```

Testes próprios: `python -m unittest discover -s daia/orchestration -p "test_*.py" -t .`
