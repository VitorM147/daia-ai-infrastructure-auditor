# DAIA V4 — Human Resolution Intelligence

## Critérios de qualidade

Um guia é completo quando identifica o serviço e recurso, fixa timestamp e janela, separa evidências de diagnóstico, oferece consultas somente leitura com resultado esperado e interpretação, e descreve correções condicionais com riscos, aprovação, rollback, validação e critério de aceite.

O validador rejeita guias sem seções essenciais, sem o marcador `EXECUÇÃO HUMANA — NÃO EXECUTAR PELO AGENTE`, sem passos explicitamente somente leitura ou com causa confirmada sem evidências contra e hipóteses alternativas.

## Limitações

O validador verifica estrutura e salvaguardas textuais; ele não abre links, executa consultas nem prova que um comando é válido no ambiente. Links devem ser provenientes de ferramentas ou apresentados como caminho manual quando não validados. A causa continua dependendo da evidência do pacote e da decisão humana.

Nenhuma remediação é executada pelo gerador.
