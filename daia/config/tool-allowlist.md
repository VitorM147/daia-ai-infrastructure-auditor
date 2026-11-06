# Allowlist de ferramentas (especificação)

> Este arquivo documenta a política. O bloqueio real precisa existir fora do LLM: credenciais somente leitura (API/Application key com escopos de leitura), configuração de ferramentas permitidas do MCP, e validação no backend. Ferramenta ausente desta lista = bloqueada.
> Não classificar como segura por conter `get`, `list`, `search` ou `query` no nome.

## Classes
`READ_ONLY_VERIFIED` · `JIRA_CREATE_APPROVED` · `KNOWLEDGE_WRITE_APPROVED` · `RESTRICTED` · `FORBIDDEN`

## Campos obrigatórios por entrada
Ferramenta · Sistema de destino · Endpoint/operação · Transporte (método) · Tipo de permissão · Identidade autorizada · Escopo (ambientes/orgs) · Efeitos esperados · Limites de uso (rate, volume, timeout) · Restrições de dados · Política de auditoria · Verificado por/em.

## Entradas

| Ferramenta | Sistema | Endpoint/operação | Método | Classe | Identidade | Escopo | Efeitos | Limites | Verificado por/em |
|---|---|---|---|---|---|---|---|---|---|
Fonte: power `datadog` (servidor MCP remoto oficial), descoberta em 2026-11-06. Classificação baseada na **descrição da ferramenta**. Só `search_datadog_monitors` foi chamada de fato (teste de conectividade). As demais ficam como `READ_ONLY_VERIFIED (doc)` até o primeiro uso confirmar o comportamento e até a chave de API ter o escopo confirmado como somente leitura.

### Permitidas (leitura)
| Ferramenta | Sistema | Operação | Classe | Observação |
|---|---|---|---|---|
| search_datadog_monitors | Datadog | Lista/consulta monitores | READ_ONLY_VERIFIED (testada 2026-11-06) | Exige `telemetry` (objeto; `{}` aceito) |
| search_datadog_hosts | Datadog | SQL sobre inventário de hosts | READ_ONLY_VERIFIED (doc) | Somente SELECT |
| search_datadog_logs | Datadog | Busca logs/padrões | READ_ONLY_VERIFIED (doc) | |
| analyze_datadog_logs | Datadog | SQL sobre logs | READ_ONLY_VERIFIED (doc) | Somente SELECT |
| search_datadog_spans / aggregate_spans | Datadog | Spans APM | READ_ONLY_VERIFIED (doc) | |
| get_datadog_trace | Datadog | Trace por ID | READ_ONLY_VERIFIED (doc) | |
| get_datadog_metric / get_datadog_metric_context / search_datadog_metrics | Datadog | Métricas | READ_ONLY_VERIFIED (doc) | |
| search_datadog_events / aggregate_events | Datadog | Eventos | READ_ONLY_VERIFIED (doc) | |
| get_change_stories | Datadog | Mudanças por serviço APM | READ_ONLY_VERIFIED (doc) | |
| search_datadog_incidents / get_datadog_incident | Datadog | Incidentes (consulta) | READ_ONLY_VERIFIED (doc) | |
| search_datadog_dashboards / get_datadog_dashboard | Datadog | Dashboards (consulta) | READ_ONLY_VERIFIED (doc) | |
| search_datadog_notebooks / get_datadog_notebook | Datadog | Notebooks (consulta) | READ_ONLY_VERIFIED (doc) | |
| search_datadog_entities | Datadog | Entity graph / catálogo | READ_ONLY_VERIFIED (doc) | Útil para ownership |
| search_datadog_rum_events / aggregate_rum_events | Datadog | RUM | READ_ONLY_VERIFIED (doc) | |
| list_datadog_skills / load_datadog_skill | Datadog | Guias de uso das ferramentas | READ_ONLY_VERIFIED (doc) | Só documentação |

### Bloqueadas
| Ferramenta | Motivo | Classe |
|---|---|---|
| create_datadog_notebook | Cria recurso no Datadog | FORBIDDEN |
| edit_datadog_notebook | Altera recurso no Datadog | FORBIDDEN |
| delete_datadog_notebook | Exclui (soft) recurso | FORBIDDEN |
| recover_datadog_notebook | Altera estado de recurso | FORBIDDEN |
| upsert_datadog_dashboard | Cria/atualiza dashboard | FORBIDDEN |
| submit_mcp_feedback | Envia dados a terceiro (efeito externo) | FORBIDDEN (sem autorização) |
| _dd_gff, _dd_guc, _dd_wfd | Marcadas “do-not-call”; `_dd_wfd` aceita method/url/body arbitrários (proxy HTTP genérico) | FORBIDDEN |
| execute_code | Executa JavaScript no servidor com SDK; pode haver variante de escrita (`execute_code_write`) | RESTRICTED (bloqueada; reavaliar só com SDK restrito a leitura comprovada) |
| search_datadog_sdk | Descoberta de APIs do `execute_code` | RESTRICTED (sem uso) |
| ask_widget_expert / get_widget_reference | Passos de construção de widgets (escrita) | RESTRICTED (sem uso) |

### Ação necessária fora do LLM
Esta lista é uma regra de comportamento. O servidor MCP expõe ferramentas de escrita, então o bloqueio técnico precisa ser feito na configuração do MCP do Kiro (desativar/não aprovar automaticamente as ferramentas FORBIDDEN e RESTRICTED) e com chaves de API/Application de escopo somente leitura. Estado atual: **NÃO VERIFICADO**.

## Regras de classificação
1. Documentação do endpoint comprova ausência de efeito de escrita? Se não, `RESTRICTED`.
2. Cria, altera, apaga, silencia, executa, dispara workflow/notificação? `FORBIDDEN`.
3. Consulta analítica via POST sem efeito de estado: permitida somente com evidência documental registrada na coluna “Verificado por/em”.
4. Jira: somente `create issue` em projeto autorizado (`JIRA_CREATE_APPROVED`), com identidade separada da identidade de leitura. Demais operações de escrita = `FORBIDDEN` sem autorização específica e separada.
5. Base de conhecimento: apenas o diretório `daia/` (`KNOWLEDGE_WRITE_APPROVED`).
6. Shell/execução de código: `RESTRICTED`; só em ambiente isolado e sem credenciais de escrita. Nunca contra infraestrutura.

## Antes de habilitar Nível 3 no Jira
- [ ] Inventariar automações e webhooks do projeto destino
- [ ] Confirmar que nenhum modifica outros sistemas
- [ ] Autorização explícita da organização registrada em `policy.md`
