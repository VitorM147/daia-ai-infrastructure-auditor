# V4 — Riscos residuais de segurança e governança

**Status:** implementação local parcial. **Não declarar proteção completa.**

| Risco | Estado | Mitigação implementada | Lacuna |
|---|---|---|---|
| LLM solicitar escrita no Datadog | Parcialmente mitigado | JSON bloqueia mutações e testes simulam `create_datadog_notebook` | O servidor MCP/backend ainda precisa aplicar o bloqueio técnico |
| MCP expor ferramenta não listada | Mitigado no guardião | Ausência resulta em deny | Só vale se o adaptador consultar o guardião antes do despacho |
| Credencial Datadog com escrita | Não verificado | Política exige identidade `datadog-readonly` | Escopos reais da chave não foram inspecionados nesta implementação |
| Proxy HTTP genérico | Mitigado na política | `_dd_wfd`, `_dd_gff`, `_dd_guc` bloqueados | Cliente MCP deve não expor ou negar esses tools |
| Execução arbitrária de código | Mitigado na política | `execute_code` bloqueado | Não há sandbox/backend implementado neste repositório |
| Criação Jira indevida | Parcialmente mitigado | Aprovação humana e projeto autorizado são obrigatórios; nenhum projeto configurado | Integração Jira e reconciliação pós-timeout não implementadas |
| Escrita local fora do escopo | Mitigado localmente | Caminhos aprovados são verificados | Adaptador deve usar o guardião, não escrever diretamente |
| Prompt injection em payload | Parcialmente mitigado | Autorização usa request estruturado, não texto do payload; teste simulado | O pipeline de análise deve manter logs como dados e nunca como instruções |
| Rate limit/auth/error contornado | Não implementado no transporte | Política exige erro terminal | Adaptador deve registrar 401/403/429 e não fazer retry de contorno |
| Inventário MCP desatualizado | Não verificado | JSON tem data/status de verificação | Reexecutar inventário no cliente alvo e atualizar com evidência |

## Critério para declarar proteção técnica concluída

Só declarar proteção técnica concluída quando um gateway/backend ou configuração do cliente MCP demonstrar, em teste controlado, que uma chamada mutante no Datadog é bloqueada antes do despacho, independentemente do prompt do LLM, e quando as credenciais forem comprovadamente somente leitura.
