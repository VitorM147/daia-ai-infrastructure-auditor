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

## V4 — Enforcement executável
- Fonte de decisão estruturada: `config/tool-allowlist.json`.
- Decisão padrão: **deny**. Ferramenta ausente, identidade divergente, efeito divergente, escopo não autorizado, limite excedido ou verificação incompleta deve ser bloqueado.
- Ponto de decisão local: `daia/security/tool_guard.py`. O guardião é offline e não despacha chamadas; o adaptador MCP/API deve chamar `authorize()` antes do despacho e interromper quando `allowed=false`.
- Identidades separadas: `datadog-readonly`, `jira-read`, `jira-create-approved` e `daia-local-writer`.
- Datadog: todas as mutações, execução de código e proxies genéricos permanecem bloqueados.
- Jira: `create_jira_issue` permanece bloqueado até projeto autorizado e aprovação humana serem fornecidos no request. Nenhum projeto está autorizado atualmente.
- Local: escritas só podem usar escopos explícitos de conhecimento/auditoria; relatórios não recebem autorização implícita.
- Esta implementação não prova o bloqueio do servidor MCP nem das credenciais. Essa integração externa continua **NÃO VERIFICADA** até ser configurada e testada no cliente/backend.

## V4 — Diagnostic Accuracy Engine
- Cálculos de taxa exigem fonte, unidade, recurso, janela UTC e denominador compatível.
- Spans amostrados não representam 100% do tráfego sem evidência de cobertura e semântica da métrica.
- Baseline não calculável por cobertura insuficiente não pode sustentar regressão ou encerramento.
- Tendência exige série bruta; agregações como `.weighted()` não podem ser tratadas como tendência sem validação.
- Causalidade exige identificadores reais compartilhados; correspondência textual é somente hipótese.
- Amostra parcial não pode sustentar afirmação global sobre Jobs, disponibilidade ou encerramento.
- O engine não confirma causa raiz automaticamente; sempre exige evidências contrárias e alternativas.

## V4 — Human Resolution Intelligence
- Todo achado relevante deve conter identificação, evidências, diagnóstico, guia de investigação, opções condicionais de resolução, validação, aceite e prevenção.
- Diagnóstico é somente leitura. Correções são instruções para humanos e devem conter `EXECUÇÃO HUMANA — NÃO EXECUTAR PELO AGENTE`.
- Causa confirmada exige evidências contra e hipóteses alternativas registradas; sem isso, o guia é rejeitado ou rebaixado.
- Links devem ser reais e provenientes de evidência; quando não houver URL validada, usar caminho manual e filtros exatos.
- O validador local verifica completude e salvaguardas textuais, mas não substitui revisão técnica, acesso ao ambiente ou validação de links.

## V4 — Jira Intelligence & Controlled Issue Creation
- Modo padrão: Nível 2, com aprovação humana específica por fingerprint/projeto.
- Nível 1 somente propõe; Nível 3 é bloqueado até autorização corporativa separada.
- Fingerprint não inclui timestamp variável; a busca Jira deve ser feita antes da criação e novamente após aprovação.
- Timeout após criação exige reconciliação por fingerprint; nunca repetir cegamente.
- Projeto, tipo, campos, componentes, responsáveis, automações e webhooks devem ser descobertos no Jira real; valores ausentes permanecem `NÃO VERIFICADO`.
- Credenciais devem vir do runtime/secret manager e não podem ser versionadas.

## V4 — Enterprise Context Intelligence
- Modelo de contexto: Empresa → Unidade de negócio → Processo → Jornada → Aplicação → Serviço → Infraestrutura → Equipe.
- Entidades e relacionamentos exigem fonte, evidência, coleta UTC, validação, confiança, responsável, ambiente e status.
- Contexto é isolado por `organization_id`; relações entre organizações são inválidas.
- Fonte desconectada não é presumida. Resultado obrigatório: `NÃO VERIFICADO — CONTEXTO EMPRESARIAL INSUFICIENTE`.
- Contradições e dados desatualizados devem ser reportados, não resolvidos por inferência silenciosa.
- Não executar fine-tuning automático com dados corporativos.
