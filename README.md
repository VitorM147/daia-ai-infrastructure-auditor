# DAIA — Datadog AI Infrastructure Auditor

O DAIA é um framework para investigar infraestrutura, aplicações e observabilidade usando evidências do Datadog e análise assistida por IA.

O projeto foi desenhado para reduzir diagnósticos baseados em suposições. A coleta, a análise, a recomendação e a execução de mudanças são etapas separadas.

## O que o DAIA faz

- coleta métricas, logs, traces, eventos, monitores e inventário;
- identifica anomalias e falhas silenciosas;
- compara sinais atuais com baselines históricos;
- separa sintoma, correlação e causa provável;
- classifica evidências como `OBSERVADO`, `INFERIDO`, `HIPÓTESE` ou `NÃO VERIFICADO`;
- gera guias humanos de diagnóstico e resolução;
- prepara propostas de atividades Jira;
- registra limitações, erros de consulta e lacunas de cobertura;
- gera relatórios somente quando o usuário solicita.

O DAIA não deve ser entendido como um agente que corrige automaticamente a infraestrutura.

## Princípios de segurança

| Sistema | Regra |
|---|---|
| Datadog | Somente leitura |
| Infraestrutura, Kubernetes, cloud, bancos e redes | Nenhuma escrita pelo agente |
| Jira | Leitura e criação somente após aprovação humana explícita |
| Base local `daia/` | Escrita controlada, com proveniência e histórico |
| Relatórios | Gerados sob demanda e ignorados pelo Git por padrão |

A allowlist local documenta a intenção. O bloqueio real deve acontecer fora do modelo, por meio de credenciais, permissões da API e configuração do MCP ou coletor.

## Arquitetura

```text
Datadog / MCP / API / exportação manual
              |
              v
    coletor determinístico somente leitura
              |
              v
   pacote de evidências JSON/CSV sanitizado
              |
              v
 IA + regras DAIA + templates + baselines
              |
              v
   achados, recomendações e relatório sob demanda
              |
              v
       aprovação humana para executar
```

A IA deve analisar evidências, não executar alterações diretamente. Toda hipótese precisa indicar as evidências favoráveis, as evidências contrárias, as alternativas e como uma pessoa pode confirmar ou refutar a hipótese.

## Quando não existe MCP

O DAIA pode operar em quatro modos:

### 1. MCP do Datadog

O agente consulta ferramentas de leitura disponibilizadas pelo MCP. A configuração deve permitir apenas operações autorizadas pela allowlist.

### 2. Coletor por API ou SDK

Um serviço autorizado consulta o Datadog usando uma service account com permissões de leitura. O coletor salva um pacote de evidências para a IA analisar.

### 3. Exportação agendada

Um job autorizado exporta periodicamente métricas, eventos, monitores e inventário para JSON ou CSV. Esse modo é adequado para ambientes isolados.

### 4. Upload manual

Uma pessoa exporta os dados e fornece o arquivo sanitizado ao agente. A janela da coleta, a origem, os filtros e as lacunas precisam acompanhar o arquivo.

Se não houver rede, credencial, MCP ou ferramenta disponível, o DAIA deve marcar o dado como `NÃO VERIFICADO` ou `NÃO DISPONÍVEL`. Ele não deve contornar o bloqueio nem inventar resultados.

## Fluxo de uso

### Mapear o ambiente

Use o comando conceitual:

```text
MAPEAR SERVIÇOS E EQUIPES
```

O objetivo é identificar serviços, ambientes, dependências, equipes indicadas por tags e lacunas de ownership.

### Auditar a infraestrutura

Use:

```text
AUDITAR TUDO
```

A auditoria orquestrada (`python -m daia.orchestration.cli start ...`, ver `daia/orchestration/README.md`) executa 15 etapas com checkpoint e retomada. Em resumo, as fases são:

1. Discovery;
2. Health Check;
3. Deep Investigation;
4. Correlation;
5. Risk Assessment;
6. Reporting.

### Gerar relatório

Relatórios não são criados automaticamente. Solicite explicitamente:

```text
GERAR RELATÓRIO EXECUTIVO
GERAR RELATÓRIO TÉCNICO
PREPARAR ATIVIDADES JIRA
```

Os arquivos aparecem em `daia/reports/`, mas essa pasta é ignorada pelo Git para evitar publicar dados operacionais.

### Preparar Jira

Use:

```text
PREPARAR ATIVIDADES JIRA
```

O resultado é uma proposta. O agente deve consultar duplicatas quando houver acesso ao Jira, usar fingerprints e aguardar aprovação humana antes de criar qualquer issue.

## Estrutura do projeto

```text
.kiro/steering/daia-core.md   regras permanentes do agente

daia/
├── README.md                 documentação operacional detalhada
├── config/
│   ├── policy.md             política de autonomia e escopo
│   └── tool-allowlist.md     ferramentas permitidas por efeito
├── evals/
│   ├── evals.md              casos e gates de avaliação
│   ├── BEHAVIORAL.md         suíte comportamental (Golden Dataset + executor)
│   ├── results.md            resultados registrados
│   ├── run-evals.ps1         suíte de verificações estáticas
│   ├── run-behavioral.ps1    suíte comportamental (executa o agente)
│   ├── golden/               Golden Dataset sintético (golden-v2)
│   ├── framework/            sandbox, scorers, métricas, gates, agentes
│   └── history/              execuções registradas e histórico de regressões
├── orchestration/            orquestrador de auditorias (15 etapas, checkpoints, retomada, limites)
├── findings/                 registry local, ignorado no Git
├── knowledge/                conhecimento operacional, ignorado no Git
├── reports/                  relatórios sob demanda, ignorados no Git
└── templates/
    ├── finding.md            ficha de achado e guia humano
    ├── jira-ticket.md        modelo de proposta Jira
    └── report.md             modelo de relatório
```

## Evidências e privacidade

Antes de enviar evidências para uma IA ou para um repositório remoto:

- remova tokens, senhas e chaves;
- remova PII desnecessária;
- remova IDs de contas e endpoints internos quando não forem necessários;
- sanitize corpos de logs, traces e payloads;
- preserve a janela temporal e a origem da evidência;
- registre o que foi removido e o que ficou indisponível.

O repositório não deve conter inventário real de produção, nomes de hosts, ownership interno ou histórico de incidentes sem aprovação explícita.

## Evals

Execute a suíte estática no PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File daia/evals/run-evals.ps1
```

A suíte verifica invariantes dos arquivos, como:

- ausência de e-mails, tokens e IDs sensíveis;
- domínios de links permitidos;
- ausência de tickets marcados como criados sem confirmação;
- uso de ferramentas proibidas no log;
- rotulagem de comandos mutáveis;
- campos mínimos das fichas técnicas.

Essas verificações não medem a precisão geral da IA. Evals comportamentais precisam de datasets sintéticos e revisão humana.

## Estado e limitações

O projeto é um framework de auditoria, não uma integração pronta com todos os ambientes. Cada instalação precisa definir:

- como o Datadog será acessado;
- quais ferramentas estão autorizadas;
- quais ambientes estão no escopo;
- quais dados podem sair do ambiente;
- qual modelo de IA será usado;
- quais projetos Jira podem receber issues;
- quais pessoas aprovam correções e tickets.

## Licença

Defina a licença antes de distribuir o projeto publicamente. Nenhuma licença foi presumida neste repositório.

## Segurança V4 e governança de ferramentas

A Implementação 01 adiciona uma política estruturada em `daia/config/tool-allowlist.json` e um guardião offline em `daia/security/tool_guard.py`.

O guardião usa **default-deny**: ferramentas ausentes, bloqueadas, com identidade divergente, efeito diferente, transporte não autorizado, limites excedidos ou verificação incompleta são negadas. Ele separa as identidades de Datadog somente leitura, Jira, criação Jira aprovada e escrita local do DAIA.

Os testes simulados estão em `daia/security/test_tool_guard.py` e não acessam rede, MCP, Datadog ou Jira:

```powershell
python -m unittest discover -s daia/security -p "test_*.py" -v
```

A proteção no servidor MCP, no backend/gateway e nas credenciais ainda precisa ser configurada no ambiente de execução. O projeto não declara essa proteção como concluída apenas por ter uma política local. Veja `daia/security/risk-residual.md`.

## Diagnostic Accuracy Engine V4

A implementação 02 adiciona `daia/diagnostics/`, um engine determinístico e somente local para reduzir conclusões sem evidência.

Ele valida:

- unidades, denominadores, timestamps UTC e fonte de uma métrica;
- mistura indevida de spans amostrados com métricas de tráfego;
- baseline comparável por janela, cobertura e mediana;
- séries brutas antes de aceitar tendências;
- correlação por identificadores reais;
- evidências contrárias e hipóteses alternativas;
- amostras parciais, que resultam em `INCOMPLETA` e nunca em encerramento global.

Os seis cenários sintéticos de regressão estão em `daia/diagnostics/synthetic_regressions.json`. Eles representam os padrões DAIA-001, DAIA-006, DAIA-007, DAIA-030, DAIA-038 e DAIA-040 sem telemetria corporativa real.

Execute os testes:

```powershell
python -m unittest discover -s daia/diagnostics -p "test_*.py" -v
python -m unittest discover -s daia/security -p "test_*.py" -v
```

O relatório metodológico antes/depois está em `daia/diagnostics/quality_report.md`. O engine não acessa Datadog nem substitui o bloqueio externo do MCP/backend.

## Proactive SRE Intelligence V4

A implementação 03 adiciona `daia/proactive/` para procurar riscos antes de incidentes. O catálogo cobre crescimento de recursos, armazenamento, redundância, filas, latência, degradação silenciosa, pós-deploy, Kubernetes, Jobs, certificados, cobertura de monitores, ingestão, consumo contratual, bancos e dependências externas.

O motor separa `PROBLEMA_ATUAL`, `RISCO_FUTURO`, `SEM_EVIDENCIA` e `NÃO_VERIFICADO`. Não fornece prazo de esgotamento sem tendência suficiente e intervalo de incerteza. Não executa remediações nem acessa Datadog, Jira ou infraestrutura.

```powershell
python -m unittest discover -s daia/proactive -p "test_*.py" -v
```

Veja `daia/proactive/README.md` e `daia/proactive/quality_report.md`.

## Human Resolution Intelligence V4

A implementação 04 adiciona `daia/resolution/` para transformar achados em guias executáveis por engenheiros humanos.

O gerador inclui identificação, evidências, consultas, sintomas, comportamento esperado, hipóteses, evidências contra, alternativas, confiança, passos somente leitura, opções condicionais de correção, riscos, aprovação, rollback, validação, aceite e prevenção.

O validador rejeita guias incompletos, causa confirmada sem evidências contrárias/alternativas e instruções de alteração sem o marcador:

```text
EXECUÇÃO HUMANA — NÃO EXECUTAR PELO AGENTE
```

Execute os testes:

```powershell
python -m unittest discover -s daia/resolution -p "test_*.py" -v
```

O gerador não executa comandos nem abre links. Links não validados devem aparecer como caminho manual e filtros exatos.

## Jira Intelligence & Controlled Issue Creation V4

A implementação 05 adiciona `daia/jira/` com proposta estruturada, fingerprints estáveis, deduplicação, aprovação humana, controle de concorrência e reconciliação após timeout.

O padrão é Nível 2. Nível 1 apenas propõe. Nível 2 cria somente com aprovação específica e projeto autorizado. Nível 3 permanece bloqueado até autorização corporativa separada.

O Jira real continua `NÃO VERIFICADO`: não há URL corporativa, credenciais, projeto autorizado ou chamada de rede versionados. O cliente padrão falha explicitamente quando não configurado.

```powershell
python -m unittest discover -s daia/jira -p "test_*.py" -v
```

## Enterprise Context Intelligence V4

A implementação 06 adiciona `daia/context/` para representar:

```text
EMPRESA → UNIDADE_DE_NEGÓCIO → PROCESSO → JORNADA → APLICAÇÃO → SERVIÇO → INFRAESTRUTURA → EQUIPE
```

Entidades e relacionamentos exigem proveniência, evidência, coleta UTC, última validação, confiança, responsável, ambiente e status. O contexto é isolado por organização, relacionamentos incorretos são rejeitados e contradições são reportadas.

Os adaptadores são somente leitura e fontes desconectadas falham explicitamente. Quando faltam fontes, o resultado é `NÃO VERIFICADO — CONTEXTO EMPRESARIAL INSUFICIENTE`.

```powershell
python -m unittest discover -s daia/context -p "test_*.py" -v
```
