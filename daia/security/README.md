# Guardião de ferramentas DAIA V4

## O que está implementado

`tool_guard.py` implementa um ponto de decisão local, determinístico e offline. Ele não chama MCP, Datadog, Jira, rede, shell ou modelo.

O guardião:

- carrega `daia/config/tool-allowlist.json`;
- exige `default_decision: deny`;
- nega ferramentas ausentes;
- nega ferramentas explicitamente bloqueadas;
- compara sistema, operação, identidade, efeito e transporte;
- aplica limites de páginas, itens e timeout;
- exige aprovação humana e projeto explicitamente autorizado para Jira;
- restringe escrita local aos diretórios aprovados;
- gera um registro de auditoria sem payload.

## Integração obrigatória

O adaptador que chama MCP/API deve fazer isto antes de despachar uma operação:

```python
from daia.security.tool_guard import ToolGuard

guard = ToolGuard("daia/config/tool-allowlist.json")
decision = guard.authorize(request)
if not decision.allowed:
    raise PermissionError(decision.reason)
# Somente aqui o adaptador pode despachar a chamada autorizada.
```

O guardião não intercepta automaticamente chamadas já feitas por outro cliente. Se o cliente MCP não chamar esse ponto de decisão, a proteção local não está aplicada.

## Testes

Na raiz do repositório:

```powershell
python -m unittest discover -s daia/security -p "test_*.py" -v
```

Os testes incluem escrita simulada no Datadog, `execute_code`, ferramenta desconhecida, divergência de efeito, identidade, limites, Jira sem aprovação/projeto e escrita local fora do escopo.

## Status de segurança

- **Implementado e testável localmente:** política estruturada e decisão default-deny.
- **Não comprovado:** bloqueio técnico no servidor MCP, escopos reais das credenciais e interceptação de todos os adaptadores.
- **Obrigatório antes de produção:** executar o guardião no backend/gateway antes do despacho e usar credenciais separadas sem permissões de escrita no Datadog ou infraestrutura.
