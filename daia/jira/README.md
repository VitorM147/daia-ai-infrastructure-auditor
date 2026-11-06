# DAIA V4 — Jira Intelligence & Controlled Issue Creation

## Estado atual

O adaptador está implementado como uma fronteira segura e testável, mas o Jira real permanece **NÃO VERIFICADO**. Não há credenciais, URL corporativa, projeto autorizado ou chamada de rede versionados neste repositório.

## Fluxo

1. `build_fingerprint()` cria uma chave estável com ambiente, aplicação, serviço, recurso, classe e identificador normalizado da falha. Timestamps não entram na chave principal.
2. `JiraController.propose()` valida e gera payload estruturado.
3. `preflight()` consulta projetos/metadados e pesquisa duplicatas por fingerprint.
4. `create()` exige Nível 2, aprovação específica, projeto autorizado e nova pesquisa de duplicatas.
5. Um lock por fingerprint impede criações simultâneas no mesmo processo.
6. Timeout após criação dispara reconciliação por fingerprint; nunca há retry cego.

## Modos

- `NIVEL_1`: somente proposta.
- `NIVEL_2`: criação após aprovação humana específica. É o padrão.
- `NIVEL_3`: bloqueado neste adaptador até autorização corporativa separada.

## Configuração segura

A implementação não lê credenciais automaticamente. O cliente real deve receber credenciais por secret manager ou variáveis de ambiente do runtime, nunca por arquivo versionado. Use identidades separadas para leitura e criação, limite o projeto explicitamente e valide automações/webhooks antes de habilitar criação.

A classe `NotConfiguredJiraClient` falha explicitamente. Ela não simula conexão.

## Testes

```powershell
python -m unittest discover -s daia/jira -p "test_*.py" -v
```

Os testes usam um cliente fake e cobrem proposta, duplicata, projeto não autorizado, aprovação negada, autenticação, timeout após criação, Jira não configurado e payload sem dados sensíveis.

## Não implementado

- transporte Jira corporativo real;
- descoberta ao vivo de projetos, campos, componentes e automações;
- persistência distribuída de idempotência;
- lock distribuído entre múltiplas instâncias;
- registro automático em `audit-log.md` por uma integração externa.

Esses pontos precisam ser implementados no gateway/runtime autorizado antes de declarar a integração real concluída.
