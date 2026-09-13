# Virtual Office

Um escritório 2D que representa o estado **real** do Orquestrador — agentes,
tarefas, execuções e saúde de providers — nunca uma simulação decorativa.
Se algo aparece se movendo no escritório, é porque um evento real do
backend disse que aquilo está acontecendo.

## Princípio fundamental

```
Orchestrator Engine (Python)
        ↓ eventos reais via bridge (orchestrator://event)
executionStore (já existia, Estágio 2)
        ↓ mudanças de estado observadas
useOfficeSync (hook)
        ↓ dispara refresh()
officeStore (Zustand)
        ↓ busca agents/steps/providerHealth reais + deriva estado
deriveOfficeSnapshot (puro, testável sem React/Phaser)
        ↓
OfficeController
        ↓ comandos imperativos (nunca o inverso)
OfficeScene (Phaser)
```

Nunca existe um caminho `Virtual Office → simulação falsa`. Não há
`setTimeout` fingindo atividade em nenhum lugar deste módulo.

## Por que Phaser 3, e como ele se encaixa

`desktop/src/office/scenes/OfficeScene.ts` é a única classe que sabe que
Phaser existe. Ela expõe um contrato mínimo e imperativo
(`ensureAgentSprite`, `moveAgentAlongPath`, `setAgentVisual`,
`getAgentGridPosition`) consumido exclusivamente por `OfficeController`
(`desktop/src/office/OfficeController.ts`) — nenhum outro componente React
chama métodos do Phaser diretamente (spec original, seção 17).

`desktop/src/components/PhaserOffice.tsx` monta exatamente um
`Phaser.Game` na montagem do componente e o destrói no unmount. Ele nunca
re-renderiza em resposta a mudança de estado do office — em vez disso,
assina `officeStore` de forma imperativa (`useOfficeStore.subscribe`) e
repassa direto para o `OfficeController`. Isso é o que garante que o FPS
do canvas nunca dependa do ciclo de render do React (seção 31/32).

**Code splitting real**: Phaser sozinho adiciona ~1.2MB minificados ao
bundle. `OfficePage` é carregado via `React.lazy()` em `App.tsx` — todas
as outras páginas continuam com o bundle original (~390KB); o custo do
Phaser só é pago por quem realmente abre o Office.

## Mapa e grid

`desktop/src/office/map.ts` define um grid de 48×30 células (32px cada).
Sete salas são retângulos fixos com uma única porta cada
(`ROOMS`), e `isWalkable(x, y)` decide colisão: paredes de sala bloqueiam,
exceto na célula da porta; corredores fora de qualquer sala são sempre
andáveis. `desktop/src/office/pathfinding.ts` implementa A* 4-direcional
puro (sem dependência de Phaser/React) sobre esse grid — testado
diretamente (`__tests__/pathfinding.test.ts`), inclusive confirmando que
uma rota até uma sala sempre passa pela porta, nunca pela parede.

Destinos são sempre semânticos (`moveAgent(agentId, "meeting_room")`),
nunca coordenadas soltas — ver `destinationPoint()` em `map.ts`.

## Mapeamento de papéis (honesto sobre suas limitações)

`desktop/src/office/roleMapping.ts` mapeia a **categoria real** de uma
tarefa (`core/orchestrator/planner.py`'s lista fixa: `coding`, `testing`,
`architecture`, `research`, ...) para uma sala, e usa o `agent_id` real
para decidir Frontend Desk vs. Backend Desk quando duas famílias de
agentes de coding trabalham em paralelo (o DAG já roda camadas em
paralelo de verdade — isso não é decorativo).

**Limitação real, não escondida**: o backend não tem uma capability
"design" de primeira classe hoje. A "Design Desk" é alimentada pelas
categorias mais próximas que existem (`research`/`documentation`/
`multimodal`/`analysis`). Até o dia em que o Planner ganhar uma categoria
de design real, os agentes Gemini que aparecem ali estão fazendo pesquisa/
análise, rotulados como "Research & Design" no painel de detalhes.

## Estados dos agentes

`desktop/src/office/stateMachine.ts::deriveOfficeSnapshot` é uma função
pura: `(agents reais, steps reais da execução ativa, saúde real dos
providers, tarefa ativa) → estado visual de cada agente`. Nenhum timer,
nenhum delay artificial. Regras:

| Situação real | Estado visual |
|---|---|
| Agente desativado (`agent.active === false`) | `OFFLINE` |
| Nenhum step seu na execução ativa | `IDLE`, na mesa de casa |
| Step `pending` | `WAITING` |
| Step `running`, provider saudável, categoria coding/refactoring/debugging | `WORKING`, na mesa (Frontend ou Backend) |
| Step `running`, categoria testing/security | `TESTING`, Testing Lab |
| Step `running`, categoria architecture/planning | `PLANNING`, CEO Office |
| Step `running`, mas o provider dele está `degraded`/`rate_limited`/`unavailable` (via `provider.health` real) | `RATE_LIMITED`, Lounge |
| Step `failed` | `ERROR`, com a mensagem real do erro |
| Step `completed` | `COMPLETED` |
| `task.mode` é `debate`/`consensus` **e** 2+ agentes rodando ao mesmo tempo | `MEETING` para todos os envolvidos, Meeting Room |

## Fluxo de rate limit → Lounge → retomada

Não existe um evento de "rate limit" dedicado hoje no backend
(`core.orchestrator.event_bus.EventType`), mas o sinal real já existe:
`ProviderHealthMonitor`/`CircuitBreaker` (Estágio 2) já classificam um
provider como `degraded`/`rate_limited`/`unavailable`, exposto via o
comando de bridge `provider.health` que a UI de Configurações já usa.
`officeStore` consulta esse mesmo endpoint. Quando o step em andamento de
um agente usa um provider nesse estado, `deriveOfficeSnapshot` o coloca em
`RATE_LIMITED` rumo à Lounge — no próximo refresh (evento real ou o poll
leve descrito abaixo), se o provider já não estiver mais degradado, o
agente volta a `WORKING` e o `OfficeController` o move de volta à mesa
automaticamente, porque o `destination` derivado mudou.

**Sem polling agressivo (seção 12)**: `useOfficeSync`
(`desktop/src/hooks/useOfficeSync.ts`) nunca usa um timer para
steps/tarefas — ele reage a mudanças reais em `executionStore` (que só
muda em resposta a eventos reais do bridge). A saúde de provider é a única
coisa sem evento de push próprio hoje, então é a única coisa com um poll —
a cada 15s, e **somente enquanto uma execução está de fato ativa**; sem
tarefa rodando, não há poll nenhum.

## Reuniões (meetings)

Não existe um objeto de "meeting" persistido no backend — deliberadamente,
para não inventar um domínio novo sem necessidade. Uma reunião visual é
derivada diretamente da estrutura real do DAG: `task.mode` sendo
`debate`/`consensus` **e** 2 ou mais agentes com steps `running`
simultaneamente. Isso é honesto porque só acontece quando o DAG
genuinamente executa múltiplos agentes em paralelo sob esses modos — nunca
fabricado para parecer mais dinâmico.

## Task Board

`desktop/src/components/OfficeTaskBoard.tsx` reflete os `ExecutionStep`s
reais (`kind === "work"`) da execução ativa, agrupados pelos status reais
(`pending`/`running`/`completed`/`failed`+`cancelled`+`skipped`).
**Diferença deliberada da especificação original**: não existe uma coluna
"Review" no board porque não existe um status `ExecutionStep` distinto
para isso no backend hoje — inventar um quebraria o princípio de nunca
mostrar o que não é real.

## Bug real encontrado e corrigido durante a implementação

O primeiro `OfficeTaskBoard` usava `useOfficeStore((s) =>
s.steps.filter(...))` como seletor do Zustand — `.filter()` sempre retorna
um array novo, então o `useSyncExternalStore` do React entrava em loop
infinito de re-render assim que a página montava com qualquer step
presente. Corrigido selecionando o array bruto e filtrando com `useMemo`
no componente. Coberto por um teste de regressão
(`OfficeTaskBoard.test.tsx`) que falha imediatamente se o padrão voltar.

## Persistência

**Não implementado nesta primeira versão** (ver "Pendências" no relatório
final): `office_layout`/`agent_position`/`desk_assignment` não são
persistidos em SQLite ainda. O layout do mapa e o mapeamento de salas são
hoje configuração estática no frontend (`map.ts`/`roleMapping.ts`), o que
já é suficiente para o MVP porque nenhuma posição precisa sobreviver a um
restart — ao reabrir o app, `officeStore.refresh()` já reconstrói o
snapshot inteiro a partir do estado real do backend (agentes, execução
ativa se houver uma, saúde de providers).

## Modo Classic Dashboard

O Office nunca é obrigatório (seção 34). Ele é a página padrão
(`useUiStore`'s `activePage: "office"`), mas "Tarefas" (Workspace) continua
inteiramente funcional e a um clique de distância na barra lateral — nada
no motor de orquestração depende do Office estar aberto.

## Fallback / Error Boundary

`OfficePage` é envolvido pelo mesmo `ErrorBoundary` por página já usado em
todas as telas (Estágio 4) — um erro de renderização no Office nunca
derruba o resto do app; o usuário vê uma mensagem e pode trocar de tela
pela barra lateral, e o orquestrador continua rodando (ele nunca dependeu
do frontend para nada além de exibir progresso).

## Como criar um novo agente/desk/sala

1. **Novo agente**: já é possível — qualquer agente real de
   `core/agents/registry.py` aparece automaticamente no escritório assim
   que `agentsApi.list()` o retorna. O `homeRoom` dele é derivado de
   `capabilities[0].name` via `roomForCapability` em `roleMapping.ts`.
2. **Nova sala**: adicione uma entrada em `ROOMS` (`map.ts`) com um
   retângulo do grid que não sobreponha outra sala, e uma entrada
   correspondente em `DESTINATION_POINTS`. Adicione o novo `RoomId` ao
   union em `types.ts`.
3. **Nova regra de mapeamento categoria → sala**: edite
   `CAPABILITY_TO_ROOM` em `roleMapping.ts`.

## Pendências reais (não escondidas)

- Botão "Conectar" disparando o fluxo OAuth interativo de um provider CLI
  (`codex login`/`claude auth login` abrindo o navegador) — hoje a
  detecção é automática para o que já está autenticado via terminal.
- Persistência em SQLite de layout/posição/preferências (seção 35).
- Pathfinding evita paredes de sala, mas não evita colisão entre dois
  agentes ocupando a mesma célula simultaneamente (não crítico
  visualmente com poucos agentes).
- Minimap, áudio, avatares customizáveis pelo usuário, Low Power Mode
  explícito, múltiplos andares/mapas -- tudo isso é "Fase 2" (seção 55),
  deliberadamente fora desta primeira versão.
- Sprites são placeholders geométricos (círculo colorido + ícone + label),
  não arte pixel final -- trocar por sprite sheets reais é uma mudança
  isolada em `OfficeScene.ts`, nada acima dela precisa mudar.
