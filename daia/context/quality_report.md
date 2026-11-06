# Qualidade — Enterprise Context Intelligence

## Garantias locais

- entidades e relações têm proveniência obrigatória;
- timestamps de coleta e validação exigem UTC;
- contexto é isolado por organização;
- relações para entidades inexistentes ou outra organização são rejeitadas;
- contexto incompleto é reportado explicitamente;
- fontes desconectadas não são tratadas como disponíveis;
- evidências divergentes são listadas como contradições;
- não há aprendizado por fine-tuning nem alteração de fontes externas.

## Limitações

O store atual é memória local do processo, não uma base persistente distribuída. Não há adaptador real conectado para Datadog, Jira, Confluence, CMDB ou repositórios. Ownership, criticidade, processos e jornadas só podem ser considerados documentados quando uma fonte autorizada os fornecer.
