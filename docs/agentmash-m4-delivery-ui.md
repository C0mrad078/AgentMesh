# Delivery Center — uso e handoff de UI

Abra **Delivery Center** no Agent Workspace. As URLs `/delivery` e
`/delivery/:candidateId` também abrem a lista ou um candidate específico e
suportam voltar/avançar do navegador. A missão e o projeto selecionados no
workspace preenchem o formulário de criação; o backend valida a integração.

1. Consulte ou configure o remote binding (URL sem credenciais, provider,
   remote name, target branch e método de merge).
2. Congele o candidate e revise versão, SHAs, hash/estatísticas do diff,
   arquivos, commits, tasks, agents, reviews, conflitos e quality gates.
3. Execute preflight. Bloqueios e sugestões de recovery são fornecidos pelo
   backend. Amostras de segredos são sempre suprimidas na tela e no relatório.
4. Em **Aprovações humanas**, abra a ação pendente, confira versão/destino/SHA,
   informe o ator humano e registre aprovação ou rejeição. A decisão não
   dispara uma operação remota automaticamente.
5. Em **Executar operação aprovada**, solicite push, criação/atualização do PR,
   merge ou revert. O backend exige aprovação e valida gates, SHA e proteção
   da branch. A UI apresenta qualquer rejeição sem alterar o estado local.
6. Consulte a CI e atribua correções por finding (agent opcional). A nova versão
   gerada pelo backend aparece na lista, sem substituir silenciosamente a
   versão selecionada.
7. Confira evidências pós-merge e proponha rollback com motivo. O plano usa
   revert e passa pela aprovação separada antes de executar.
8. Consulte telemetria por fase e etapas persistidas. Métricas ausentes são
   `unknown`; valores medidos iguais a zero permanecem zero.

A store assina `orchestrator://event`, agrupa rajadas de eventos delivery e
recarrega DTOs persistidos, sem polling automático ou transições de domínio
locais. **Atualizar estado** / **Recuperar estado persistido** recuperam dados
após falha de conexão. Retry remoto reutiliza chave por candidate, versão,
ação e head SHA. A idempotência e autorização são garantidas pelo backend.

A interface usa os 16 comandos e DTOs da seção 4.1 do contrato compartilhado.
O contrato oferece diff hash/stat e lista de arquivos, não conteúdo de patch;
a UI exibe exatamente essas evidências. Links externos aceitam HTTPS sem
credenciais, query ou fragmento. Campos livres sanitizados recebem máscara
adicional de apresentação; isso não substitui a sanitização do backend.

## Validação

- `npm --prefix desktop test -- --run`
- `npm --prefix desktop run typecheck`
- `npm --prefix desktop run lint`
- `npm --prefix desktop run build`

Os testes cobrem página, cards, payloads dos 16 comandos, decisões humanas,
retries, eventos, seleção concorrente, cleanup de subscriptions, URLs,
mascaramento/cópia e métricas desconhecidas. O smoke remoto real e a integração
Tauri/backend são responsabilidade do Lead e não são substituídos por mocks.
