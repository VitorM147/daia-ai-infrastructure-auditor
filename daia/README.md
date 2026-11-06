# DAIA V3 — estrutura de trabalho

O DAIA investiga infraestrutura e negócio com evidências do Datadog, separando coleta, análise e decisão humana. O Datadog é somente leitura. Infraestrutura não recebe alterações pelo agente. Tickets Jira só podem ser criados após aprovação humana explícita.

## Estrutura

```text
.kiro/steering/daia-core.md     regras permanentes (carregadas em toda sessão)
daia/config/policy.md           autonomia, janelas, escopo, Jira, pesos, supressões, permissões
daia/config/tool-allowlist.md   classificação de ferramentas por operação/efeito
daia/knowledge/                 memória estruturada com proveniência
daia/findings/registry.md       fingerprints, recorrência, vínculo com Jira
daia/audit-log.md               execuções, ferramentas usadas, criações Jira
daia/templates/                 report, finding (com guia de resolução humana), jira-ticket
daia/evals/                     EVAL-001..015, gates e resultados
daia/reports/                   saída temporária de relatórios gerados sob demanda
```

## Relatórios

Relatórios **não são gerados automaticamente**. O agente responde no chat por padrão e só grava um arquivo em `daia/reports/` quando o usuário solicitar, por exemplo:

- `GERAR RELATÓRIO EXECUTIVO`
- `GERAR RELATÓRIO TÉCNICO`
- `AUDITAR TUDO E GERAR RELATÓRIO`
- `PREPARAR ATIVIDADES JIRA`

Os relatórios são artefatos de uma execução específica. Eles não devem ser tratados como memória permanente nem versionados por padrão. O conteúdo de `daia/reports/` é ignorado pelo `.gitignore`, exceto o `.gitkeep`. A memória permanente fica em `knowledge/`, `findings/registry.md` e `audit-log.md`, sempre com proveniência, data e classificação da evidência.

Se um relatório não for solicitado, o agente pode registrar apenas o evento essencial no `audit-log.md` quando isso fizer parte do escopo da execução. Não deve criar relatório silenciosamente.

## Ambientes sem MCP do Datadog

O DAIA pode funcionar sem MCP. O mecanismo de coleta deve ser escolhido conforme o ambiente:

| Método | Funcionamento | Requisito |
|---|---|---|
| MCP Datadog | O agente consulta ferramentas de leitura do Datadog | MCP configurado e allowlist aplicada fora do LLM |
| Coletor por API | Um serviço ou script executa consultas REST/SDK com credencial de leitura | Rede para o Datadog e credencial de service account somente leitura |
| Exportação | Um job autorizado exporta métricas, eventos, monitores e inventário para JSON/CSV | Processo autorizado de exportação; a IA não precisa de acesso ao Datadog |
| Upload manual | Uma pessoa fornece um snapshot ou arquivo de evidências | Arquivo sanitizado e janela de coleta informada |

A falta de MCP, rede, credencial ou ferramenta não pode ser contornada. O DAIA deve registrar `NÃO VERIFICADO` ou `NÃO DISPONÍVEL`, explicar a limitação e não inventar dados. Os arquivos de evidência devem remover tokens, senhas, PII e IDs de conta quando não forem necessários.

A coleta deve ser separada da análise. O coletor deve produzir um pacote de evidências com:

- janela UTC da coleta;
- origem e versão do coletor;
- consultas executadas e paginação;
- métricas brutas e agregadas;
- monitores, eventos, logs e traces sanitizados;
- erros de consulta, lacunas e contagens de páginas;
- checksum ou identificador do pacote.

## Arquitetura da análise por IA

A IA analisa o pacote de evidências, não acessa infraestrutura diretamente. O fluxo recomendado é:

```text
Datadog/MCP/API/exportação
        ↓
coletor determinístico somente leitura
        ↓
pacote JSON/CSV sanitizado + metadados
        ↓
IA com daia-core.md + templates + evidências
        ↓
achados OBS/INF/HIP/NV e relatório sob demanda
        ↓
aprovação humana para correção ou Jira
```

A IA deve:

1. validar se a evidência está completa e dentro da janela;
2. separar sintoma, correlação e causa;
3. calcular taxas a partir de métricas apropriadas e comparar baseline;
4. marcar incertezas como `OBSERVADO`, `INFERIDO`, `HIPÓTESE` ou `NÃO VERIFICADO`;
5. propor diagnóstico, correção manual, rollback e validação;
6. gerar relatório somente quando solicitado;
7. nunca executar alterações em Datadog ou infraestrutura;
8. nunca criar Jira sem aprovação humana e sem reconciliação de duplicatas.

Quando não houver MCP, a IA pode rodar sobre o pacote exportado localmente ou em um serviço de modelo aprovado pela organização. Antes de enviar evidências a uma API externa, aplicar redaction e validar política de dados. Uma opção de operação é um modelo hospedado na conta corporativa, como Bedrock, mas a escolha do provedor depende da política de segurança e ainda precisa ser validada.

## Primeiros passos

1. Preencher `config/policy.md` (ambientes, projetos Jira, pesos).
2. Classificar as ferramentas reais do Datadog em `config/tool-allowlist.md`.
3. Garantir o bloqueio fora do LLM (chaves de API somente leitura, ferramentas permitidas no MCP).
4. Definir o adaptador de coleta para cada ambiente: MCP, API, exportação ou upload.
5. `MAPEAR SERVIÇOS E EQUIPES`, depois `AUDITAR TUDO`.
6. Pedir explicitamente `GERAR RELATÓRIO EXECUTIVO/TÉCNICO` quando quiser um arquivo.
7. Montar datasets e executar `EXECUTAR EVALS` antes de ampliar a autonomia.
