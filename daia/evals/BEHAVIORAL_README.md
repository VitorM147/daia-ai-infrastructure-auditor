# AI SRE Evaluation Framework V4

## Golden dataset

`golden_dataset.json` contém 20 cenários sintéticos: 15 avaliações EVAL-001..015 e cinco variações saudáveis/de capacidade/Kafka/rede. Não há telemetria corporativa real. Cada caso contém entrada, telemetria simulada, problemas esperados, causa quando conhecida, severidade, resposta permitida e objetivo.

## Executor

Execute:

```powershell
python -m daia.evals.run_behavioral
```

Esse comando usa o baseline determinístico de referência e grava `behavioral-last-run.json`, que é ignorado pelo Git. Isso valida o scorer e o pipeline, mas não representa precisão de uma IA.

Para avaliar um agente real, forneça um JSON com uma previsão por `scenario_id`:

```powershell
python -m daia.evals.run_behavioral --predictions predictions.json --output result.json
```

O adaptador do agente é externo e deve produzir os campos usados pelo scorer. O executor registra versão do dataset, versão do agente, modelo declarado, Python e timestamp UTC.

## Métricas e gates

O resultado inclui precisão, recall, falsos positivos, falsos negativos, acurácia de severidade, acurácia de causa, reconhecimento de incerteza e gate de segurança. O gate falha com regressão de segurança, falso positivo ou falso negativo. Avaliações subjetivas de utilidade de procedimentos continuam exigindo revisão humana.

`behavioral-last-run.json` não é uma declaração de precisão do DAIA. Não há resultado de agente real até um adaptador LLM ser conectado e suas previsões serem fornecidas.
