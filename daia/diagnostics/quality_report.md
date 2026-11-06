# DAIA V4 — Diagnostic Accuracy Engine: antes/depois

## Antes (baseline metodológico)

**OBSERVADO:** as auditorias anteriores tiveram seis regressões documentadas: spans amostrados tratados como tráfego total, `.weighted()` interpretado como tendência Kafka, contagens sem baseline, associação textual sem identificador causal, Jobs históricos confundidos com estado ativo e encerramentos com amostra parcial.

**NÃO VERIFICADO:** não existe uma métrica histórica confiável de precisão, recall ou taxa de falsos positivos. Portanto este documento não atribui percentuais de melhoria.

## Depois (implementação 02)

O engine agora bloqueia ou rebaixa conclusões quando faltar unidade, denominador, fonte ou janela temporal válidos; cobertura mínima e janela comparável para baseline; série bruta quando uma tendência é afirmada; identificadores reais para correlação causal; estado atual completo para encerramento; ou evidências contrárias e hipóteses alternativas.

Os resultados distinguem `INCOMPLETA`, `NÃO VERIFICADO`, `HIPÓTESE`, `INFERIDO` e `CAUSA_PROVÁVEL`. O engine não emite `CAUSA_CONFIRMADA`, `INDISPONIBILIDADE_GERAL` ou `ENCERRADO` como resultado automático.

## Regressões sintéticas

Os seis casos DAIA-001, DAIA-006, DAIA-007, DAIA-030, DAIA-038 e DAIA-040 têm regras sintéticas e testes. As entradas não contêm telemetria corporativa real.

## Limitação do depois

A implementação é um mecanismo determinístico local. Ela não prova que uma IA externa usará o engine, nem prova, sem um adaptador, que o coletor Datadog passou pela validação. A integração deve chamar o engine antes da análise e preservar a proveniência.
