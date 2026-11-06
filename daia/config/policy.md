# Política DAIA (configurável, validar com a organização)

## Autonomia
- Nível atual: **2** (preparar tickets e aguardar aprovação humana)
- Nível 3 autorizado pela organização? **Não**

## Janelas de investigação padrão
| Finalidade | Janela |
|---|---|
| Incidente recente | 15 min |
| Comportamento operacional | 1 h |
| Visão diária | 24 h |
| Recorrência | 7 d |
| Tendências/regressões | 30 d |

## Escopo
- Ambientes permitidos: _(preencher, ex.: prod, hml)_
- Ambientes excluídos: _(preencher)_
- Limite de consultas de alto volume por auditoria: _(preencher)_

## Jira
- Integração conectada: **Não**
- Projetos autorizados para criação: _(nenhum até confirmação; não inventar chaves)_
- Limite de tickets por execução: _(preencher)_
- Confiança mínima para propor ticket: _(preencher)_
- Regras de roteamento (serviço/componente → projeto/equipe): ver `daia/knowledge/services-teams.md`

## Pesos de risco (a validar; NÃO é fórmula estatística)
| Fator | Peso | Validado por |
|---|---|---|
| Impacto operacional | _(pendente)_ | |
| Criticidade do serviço | _(pendente)_ | |
| Severidade técnica | _(pendente)_ | |
| Frequência | _(pendente)_ | |
| Abrangência | _(pendente)_ | |
| Confiança das evidências | _(pendente)_ | |

## Regras de supressão aprovadas
_(nenhuma. Só suprimir achado com regra listada aqui, com aprovador e data.)_

## Classificação de dados em relatórios/tickets
Redigir: senhas, tokens, chaves, PII, payloads. Incluir apenas identificadores técnicos necessários.

## Permissões consolidadas (V3, prevalece sobre trechos anteriores)
| Sistema | Permissão |
|---|---|
| Datadog | Somente leitura |
| Jira | Leitura + criação de issues em projetos autorizados. Sem editar, excluir, transicionar, reatribuir, fechar ou criar projetos (salvo autorização específica e separada) |
| Base de conhecimento (`daia/`) | Gravação controlada, com proveniência |
| Infraestrutura | Nenhuma escrita |

- Controle por operação e efeito real, não pelo verbo HTTP: ver `config/tool-allowlist.md`.
- Nível inicial obrigatório: 2.
- Nível 3 exige: autorização da organização, projeto permitido, confiança mínima, deduplicação, limites de volume, roteamento validado e inventário de automações/webhooks do projeto Jira.

## Avaliação
- Casos e gates: `daia/evals/evals.md`
- Metas por versão (definidas pelo responsável técnico): _(pendente)_
