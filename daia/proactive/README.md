# DAIA V4 — Proactive SRE Intelligence

Este pacote analisa sinais preventivos sem alterar Datadog, infraestrutura ou Jira.

## Estados

- `PROBLEMA_ATUAL`: o valor atual atingiu o limiar informado. Não é previsão.
- `RISCO_FUTURO`: há tendência positiva validada, mas o valor atual ainda está abaixo do limiar.
- `SEM_EVIDENCIA`: não há sinal suficiente de degradação futura.
- `NÃO_VERIFICADO`: a qualidade ou cobertura da telemetria é insuficiente.

## Regras

A análise exige uma série temporal ordenada, uma identidade única de recurso, unidade consistente, timestamps UTC e cobertura mínima. Tendências não são calculadas com pontos insuficientes ou amostra parcial. `.weighted()` não é aceito como prova de crescimento persistente: a série bruta deve ser fornecida.

Estimativas de esgotamento só são retornadas com tendência positiva e intervalo inferior/superior de incerteza. O intervalo é uma aproximação baseada na dispersão dos resíduos, não uma garantia estatística para qualquer sistema. Sem dados suficientes, o status é `NOT_CALCULABLE`.

O catálogo em `catalog.json` lista as verificações preventivas e os requisitos mínimos de evidência. O método `classify_risk()` recebe fatores aceleradores, mitigadores, ações preventivas e indicadores de acompanhamento para manter a recomendação auditável.

## Testes

```powershell
python -m unittest discover -s daia/proactive -p "test_*.py" -v
```

Os testes usam somente séries sintéticas.
