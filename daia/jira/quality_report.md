# Qualidade — Jira Intelligence & Controlled Issue Creation

## Garantias locais

- fingerprints são estáveis e não usam timestamp variável;
- proposta exige campos técnicos e de resolução;
- Nível 1 nunca cria;
- Nível 2 exige aprovação específica;
- Nível 3 é bloqueado;
- projeto sem autorização é bloqueado;
- duplicatas são pesquisadas antes da criação;
- lock por fingerprint impede concorrência local;
- timeout exige reconciliação antes de qualquer nova tentativa;
- erros de autenticação terminam o fluxo;
- Jira não configurado resulta em `NÃO_VERIFICADO`;
- nenhum dado sensível é adicionado pelo modelo de payload.

## Riscos residuais

O lock é apenas por processo e não substitui um lock distribuído. A busca por fingerprint só é confiável se o backend Jira indexar a chave. A URL real, os campos obrigatórios, as permissões e as automações do projeto continuam não verificados. O cliente fake não prova que o Jira corporativo cria exatamente uma issue; isso exige teste controlado no ambiente autorizado.
