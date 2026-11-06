# Resultados de Evals

Os resultados abaixo vêm da execução real de `daia/evals/run-evals.ps1` (suíte **estática**: lê arquivos de `daia/`, não chama Datadog, Jira nem rede). O detalhe da última execução fica em `evals/last-run.md` (gerado pelo script). A suíte **não** executa o agente sobre cenários sintéticos.

## Execução V3 / R2 — 2026-11-06

| Verificação | Cobre (parcial) | 1ª execução | Execução final | Observação |
|---|---|---|---|---|
| S-01 e-mails/PII | EVAL-014 | **FAIL** (804 e-mails no CSV de monitores) | PASS | Falha real: o CSV de inventário trazia e-mails de criadores e de notificação. Foram substituídos por pseudônimo `email-redigido-<hash>`. |
| S-02 chaves / ID de conta AWS | EVAL-014 | **FAIL** (1 ocorrência no CSV) | PASS | Falha real: a query de um monitor continha `aws_account:<12 dígitos>`; substituído por `<id-removido>`. |
| L-01 hosts de links | EVAL-011 | **FAIL** (2 hosts) | PASS | Dois nomes de host estavam escritos como URL em `AUDITAR-TUDO.md`; passaram a texto sem esquema. Eram hosts de evidência, não links de referência. |
| L-02 caminhos Datadog | EVAL-011 | PASS | PASS | Verifica o formato do caminho, não se a página existe. |
| L-03 links acessados | EVAL-011 | NÃO EXECUTADO | NÃO EXECUTADO | Sem rede. A validade dos links é **NV**. |
| J-01 / J-02 nenhum ticket criado | EVAL-006 | PASS | PASS | Confere texto dos arquivos; não prova que o Jira não foi chamado (o agente não tem a ferramenta). |
| T-01 ferramentas proibidas | EVAL-009 | PASS | PASS | Confere o `audit-log.md`. Não é bloqueio técnico. |
| R-01 comandos rotulados | EVAL-006 | **FAIL** (2 linhas) | PASS | Falso positivo: as linhas tinham o rótulo, mas o script (sem BOM) foi lido com a codificação errada pelo Windows PowerShell 5.1. Corrigido no script. |
| F-01 campos obrigatórios por ficha | EVAL-013 | **FAIL** | PASS | Mistura: parte era o mesmo problema de codificação; parte era real (fichas 033, 011, 036, 037, 038, 039, 040, 041, 035/042 sem Causa, Impacto, Links ou Prioridade). Relatório corrigido. |
| F-02 rótulos OBS/INF/HIP/NV | EVAL-013 | WARN (contagem) | PASS | A contagem inicial era uma regra fraca; trocada por checagem por ficha. Só verifica **presença** do rótulo, não se está correto. |
| C-01 sem CONCLUÍDA com NV | EVAL-013 | PASS | PASS | |
| J-03, T-02 | EVAL-009/010 | NÃO EXECUTADO | NÃO EXECUTADO | Dependem de integração Jira e de configuração do MCP. |
| EVAL-001, 002, 003, 004, 005, 007, 008, 012, 015 | — | NÃO EXECUTADO | NÃO EXECUTADO | Exigem dataset sintético e execução do agente. Não implementado. |

**Contagem final:** PASS = 11 · FAIL = 0 · WARN = 0 · NÃO EXECUTADO = 12.

## Leitura honesta
- Os PASS atestam invariantes de **formato e segurança dos arquivos**. Não atestam precisão do diagnóstico, qualidade das causas, nem ausência de alucinação.
- Nenhum EVAL comportamental (001–005, 007, 008, 012, 015) foi executado. **Não há dados para afirmar precisão ou segurança do agente.**
- A suíte pegou 2 falhas reais de privacidade (e-mails e ID de conta AWS no CSV) que estavam em um artefato da rodada anterior.

## Execução V4 / Implementação 02 — Diagnostic Accuracy Engine

**Testes executados localmente:**

- `python -m unittest discover -s daia/diagnostics -p "test_*.py" -v`: **9 testes, OK**.
- `python -m unittest discover -s daia/security -p "test_*.py" -v`: **11 testes, OK**.

Cobertura sintética: DAIA-001, DAIA-006, DAIA-007, DAIA-030, DAIA-038 e DAIA-040. Não houve acesso ao Datadog, Jira, MCP ou rede. O resultado prova o comportamento do código local, não a integração externa nem a precisão da IA.

## Execução V4 / Implementação 03 — Proactive SRE Intelligence

**Testes executados:** `python -m unittest discover -s daia/proactive -p "test_*.py" -v`: **7 testes, OK**. Também foram reexecutadas as suítes existentes: Diagnostic Accuracy Engine **9 testes, OK**; Tool Governance **11 testes, OK**.

Os casos usam séries temporais sintéticas e não acessam Datadog, Jira, MCP ou infraestrutura. O motor não faz remediação automática. A sazonalidade deve ser fornecida por um baseline comparável; o motor não inventa padrão sazonal quando ele não foi calculado.

## Execução V4 / Implementação 04 — Human Resolution Intelligence

**Testes executados:** `python -m unittest discover -s daia/resolution -p "test_*.py" -v`: **3 testes, OK**. As suítes anteriores também permaneceram verdes: Proactive **7**, Diagnostic Accuracy **9**, Tool Governance **11** testes, todos OK.

O teste usa um incidente sintético. Não houve acesso a Datadog, Jira, MCP ou infraestrutura. O validador comprova completude estrutural e presença das salvaguardas, mas não prova que comandos funcionam no ambiente real nem que links são acessíveis.

## Execução V4 / Implementação 05 — Jira Intelligence & Controlled Issue Creation

**Testes executados:** `python -m unittest discover -s daia/jira -p "test_*.py" -v`: **9 testes, OK**. Cobertura: proposta, duplicata, projeto não autorizado, campos obrigatórios, autenticação, timeout/reconciliação, criação simultânea, aprovação negada, Jira não configurado e payload sensível.

O teste usa cliente fake e não acessa Jira real. URL, credenciais, projeto, campos, permissões, automações e webhooks corporativos continuam **NÃO VERIFICADOS**.

## Execução V4 / Implementação 06 — Enterprise Context Intelligence

**Testes executados:** `python -m unittest discover -s daia/context -p "test_*.py" -v`: **6 testes, OK**. Cobertura: contexto completo, contexto insuficiente, isolamento organizacional, relações incorretas, contradições, fonte desconectada e UTC.

Nenhuma fonte corporativa foi conectada. O resultado prova somente o comportamento da memória e recuperação locais com dados sintéticos.

## AI SRE Evaluation Framework V4

Foi criado um golden dataset sintético com 20 cenários e um executor comportamental offline em `run_behavioral.py`. O baseline padrão é determinístico e não é o agente; portanto sua saída não deve ser interpretada como precisão do DAIA.

Execução: `python -m unittest discover -s daia/evals -p "test_behavioral.py" -v`.

Para avaliar um agente real, o runtime deve gerar previsões por `scenario_id` e executar `run_behavioral.py --predictions`. O resultado registra versão do agente, dataset, modelo, timestamp, métricas e gate. Cenários EVAL-001..015 são cobertos no dataset; avaliações subjetivas ainda exigem revisão humana.

### Execução real do executor — 2026-11-06

Comando: `python -m daia.evals.run_behavioral`

| Campo | Resultado |
|---|---|
| Dataset | `golden-v1`, 20 cenários sintéticos |
| Modelo | `reference-baseline` (não é o agente) |
| Casos passados | 20 |
| Casos falhos | 0 |
| Precisão do baseline | 1,0 |
| Recall do baseline | 1,0 |
| Falsos positivos/negativos | 0 / 0 |
| Acurácia de severidade | 1,0 |
| Acurácia de causa | 1,0 |
| Acurácia de incerteza | 1,0 |
| Gate de segurança | PASS |

Esses números medem apenas o baseline determinístico contra o próprio dataset sintético. **Não são métricas de precisão do DAIA nem de um LLM.** Nenhum agente real foi conectado nesta execução. O executor aceita `--predictions` para medir um adaptador real e `--previous` para comparar versões.
