# <ID: DAIA-NNN> — <Título>

## Camada executiva
Problema · Prioridade · O que é afetado · Impacto no negócio (observado | potencial | indeterminado) · Equipe · Jira relacionado.

## Camada técnica

### IDENTIFICAÇÃO
- ID / Título / Prioridade / Status:
- Ambiente / Serviço / Recurso / Região-cluster:
- Equipe responsável (fonte e status de validação):
- Data e horário / Janela de análise:
- Fingerprint (composição usada):

### DESCRIÇÃO
- O que aconteceu:
- Esperado x observado:
- Frequência / Duração / Primeira e última ocorrência:
- Alerta configurado? Disparou?
- Incidentes anteriores / recorrência / risco de propagação:
- Impacto operacional (observado | potencial):
- Impacto no negócio (observado | potencial):
- Nível de confiança (critério):

### EVIDÊNCIAS (rotular OBSERVADO | INFERIDO | HIPÓTESE | NÃO VERIFICADO)
- Métricas (consulta, janela, valores):
- Logs sanitizados (padrão, contagem):
- Traces:
- Eventos / mudanças correlacionadas:
- Histórico / período equivalente:
- **Links diretos** (URL real ou caminho manual + filtros; marcar “não validado” quando aplicável):

### DIAGNÓSTICO
- Causa: confirmada | provável | hipótese | indeterminada
- Hipóteses alternativas:
- Evidências a favor / contra:
- Informações não verificadas e como obtê-las:

### GUIA DE INVESTIGAÇÃO E RESOLUÇÃO HUMANA
**A. Resumo (linguagem simples):**
**B. Pré-requisitos:** permissões, ferramentas, sistemas, restrições de segurança, aprovação de mudança.

**C. Diagnóstico passo a passo (SOMENTE LEITURA)**
| # | Objetivo | Ferramenta/interface e onde | Comando ou consulta | Resultado esperado | Interpretação | Se diferente |
|---|---|---|---|---|---|---|
| 1 | | | | | | |

**D. Resolução sugerida (condicional à causa confirmada)**
Para cada correção:
- Ação / por que pode resolver:
- Pré-requisitos / riscos / efeitos colaterais / aprovação necessária:
- Como executar manualmente:
  > **EXECUÇÃO HUMANA — NÃO EXECUTAR PELO AGENTE**
  > `<comando>`
- Validação / condição de parada / rollback:

**E. Validação pós-correção:** métricas que normalizam, erros que cessam, testes, comportamento esperado, janela de observação, critérios de aceite.
**F. Acompanhamento/prevenção:** alertas, observabilidade, capacidade, runbooks, testes preventivos.

### ENCAMINHAMENTO
- Ticket Jira / status:
- Duplicata verificada em (data, consulta, resultado):

## Requisitos V4 — qualidade do guia humano

Toda ficha gerada deve conter: identificação completa com timestamp e janela; evidências separadas por tipo e rótulo; links reais ou caminho manual com filtros; sintomas e comportamento esperado; causas, evidências a favor e contra, alternativas e confiança; passos de diagnóstico com objetivo, interface, local, consulta, esperado, interpretação e desvio; opções condicionais de correção; riscos, aprovação, rollback, condição de parada, validação e aceite. Comandos mutáveis devem conter exatamente: **EXECUÇÃO HUMANA — NÃO EXECUTAR PELO AGENTE**.
