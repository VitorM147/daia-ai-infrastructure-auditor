# DAIA V4 — Enterprise Context Intelligence

O pacote `daia/context/` representa a cadeia:

```text
EMPRESA → UNIDADE_DE_NEGÓCIO → PROCESSO → JORNADA → APLICAÇÃO → SERVIÇO → INFRAESTRUTURA → EQUIPE
```

Cada entidade e relacionamento exige fonte, evidência, coleta UTC, última validação, confiança, responsável, ambiente e status de verificação. O `ContextStore` é isolado por `organization_id` e rejeita relacionamentos entre organizações diferentes.

## Fontes

`adapters.py` define contratos somente leitura. `NotConnectedAdapter` falha explicitamente; ele não presume acesso a Datadog, Jira, Confluence, CMDB, runbooks ou repositórios. Um adaptador real deve ser implementado no runtime autorizado, passar pelo ToolGuard e transformar respostas em entidades com proveniência.

## Recuperação

`ContextRetriever.for_service()` recupera o serviço e seus relacionamentos, lista níveis ausentes e reporta evidências contraditórias. Se o serviço não existe ou não há fontes suficientes, retorna `NÃO VERIFICADO — CONTEXTO EMPRESARIAL INSUFICIENTE`.

Não há fine-tuning automático. Correções humanas devem atualizar a memória estruturada com nova proveniência e validação, sem sobrescrever silenciosamente o histórico.

## Testes

```powershell
python -m unittest discover -s daia/context -p "test_*.py" -v
```
