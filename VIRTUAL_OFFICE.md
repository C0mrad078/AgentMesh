# Virtual Office

> **SUPERSEDIDO (AgentMash V2, Phase 4)** — a integração descrita abaixo
> (`RealOfficeAdapter`, `realAgentMapping.ts`, `useRealOfficeSync`, o
> mapeamento fixo de N agentes de roteamento para 4 personagens visuais
> nomeados) foi **retirada** nesta fase e substituída por uma integração
> orientada a domínio real (`Agent`/`Team`/`Project`/`Session`
> persistidos), sem mapeamento fixo — ver **[docs/agentmash-v2-phase4.md](docs/agentmash-v2-phase4.md)**
> para a arquitetura atual. Este documento permanece como registro
> histórico do Estágio 3 (útil para entender decisões passadas), mas não
> descreve mais o código em produção.

Um escritório 2D que representa o estado **real** do Orquestrador — agentes,
tarefas, execuções e saúde de providers — nunca uma simulação decorativa.
Se algo aparece se movendo no escritório, é porque um evento real do
backend disse que aquilo está acontecendo.

**Este documento cobre a integração com o backend** (eventos reais, estados
de agente, fallback, reuniões, task board), como existia até o Estágio 3.
Para a fundação de jogo 2D em si (Phaser, Tiled, grid, colisão,
pathfinding, câmera, personagens, sprites), ainda válida, ver
**[GAME_ENGINE.md](GAME_ENGINE.md)**.

## Estágio 3: o Simulation Mode deixou de ser a fonte padrão

A partir deste estágio, `OfficeSimulationService` (Estágio 2) só roda a
partir do painel **Developer Mode** (ícone de chave inglesa na tela
Office) — nunca por padrão. A fonte real e padrão é:

```
Codex CLI / Claude Code CLI / Gemini (adapters reais)
        ↓
ProviderPool + ProviderHealthMonitor (core/providers/)
        ↓
Router + ExecutionEngine (core/orchestrator/)
        ↓ publica em
EventBus (core/orchestrator/event_bus.py) -- tipado, único, real
        ↓
Bridge sinks (core/bridge/server.py) -- já existiam desde o Estágio 1
        ↓ stdio JSON-line "event"
Rust bridge manager (desktop/src-tauri/src/bridge/manager.rs)
        ↓ Tauri emit
canal "orchestrator://event" (frontend)
        ↓
executionStore (já existia -- Estágios 1/2)
        ↓ dispara re-sync (não polling)
useRealOfficeSync -> RealOfficeAdapter (game/agents/)
        ↓ traduz para AgentEvent
AgentStateMachine (Estágio 2, inalterada)
        ↓
Agent (Phaser) -- game/entities/
```

Achado real da auditoria inicial deste estágio: o caminho Python → Rust →
Tauri → frontend **já existia por completo** desde o Estágio 1 (usado pelo
board de progresso da execução) — nada novo foi necessário nessa ponte. O
que realmente faltava, e foi construído agora:

1. **`provider.rate_limited` / `provider.recovered` nunca chegavam ao
   frontend** -- `ProviderHealthMonitor.on_change` só alimentava a tabela
   `provider_health`. Novo sink real:
   `core.bridge.server.make_provider_health_bridge_sink`, testado em
   `tests/python/test_provider_health_bridge_sink.py`.
2. **`retry_after_seconds` de um `ProviderRateLimitError` real era
   descartado** -- agora persiste em `ProviderHealthSnapshot` e viaja até
   o `provider.rate_limited` (chave `retryAfter`) e até `provider.health`
   (chave `retry_after_seconds`), nunca inventado quando o adapter não
   informa (`tests/python/test_provider_health.py`).
3. **Fallback entre agentes nunca acontecia de verdade** --
   `EventType.FALLBACK_USED` existia no enum mas nunca era publicado.
   Agora `ExecutionEngine._run_correction_round` reexecuta com um agente
   diferente (`Router.route(..., exclude_agent_ids=...)`) *apenas* quando
   o provider do agente anterior está genuinely indisponível -- nunca só
   porque o código estava errado (isso continua sendo o mesmo agente
   corrigindo o próprio trabalho, spec seção 52). Ver
   `tests/integration/test_provider_fallback.py` (inclui o teste de
   controle negativo: correção comum não troca de agente).
4. **Reunião nunca era um evento nomeado** -- `MeetingManager`
   (`core/orchestrator/meeting_manager.py`) publica
   `meeting.created`/`meeting.started`/`meeting.completed` com
   participantes reais e dinâmicos sempre que uma camada do DAG roda 2+
   agentes ao mesmo tempo sob modo Debate/Consensus -- o mesmo sinal real
   que a heurística do frontend (abaixo) já usava, agora também nomeado e
   auditável no backend. Ver `tests/integration/test_meeting_manager.py`.
5. **`Agent` não distinguia papel de provider** -- `preferred_provider` +
   `fallback_providers` (spec seção 8/9), persistidos (migração
   `0005_agent_fallback_providers.sql`), declarados de verdade para os
   dois agentes reais autenticados nesta máquina
   (`agent_codex_cli_developer` → fallback `claude_code_cli`;
   `agent_claude_code_architect` → fallback `codex_cli`). O `Router`
   também dá um bônus de pontuação (`fallback_preference_bonus`) a um
   candidato cujo provider está na lista `fallback_providers` do agente
   anterior durante um reroute -- não é só "qualquer outro candidato da
   mesma capability", é o fallback *declarado* preferido sobre os demais
   (`ExecutionEngine._run_correction_round` passa
   `preferred_fallback_providers` ao `Router.route`). Ver
   `tests/python/test_router.py::test_fallback_preference_bonus_*`.

## Como o frontend traduz eventos reais em posição física

`RealOfficeAdapter` (`desktop/src/game/agents/RealOfficeAdapter.ts`) é o
`VirtualOfficeController` do diagrama do Estágio 3. Ele **não** reimplementa
a derivação de estado -- reutiliza `deriveOfficeSnapshot`
(`office/stateMachine.ts`, real desde o Estágio 1, inalterada) para decidir
o que cada *agente real* está fazendo a partir de `agents`/`steps`/
`providerHealth`/`activeTask` reais, e só então traduz esse estado real
para o `AgentEvent` que uma das 4 personagens visuais entende.

**Mapeamento agente real → personagem visual**
(`game/agents/realAgentMapping.ts`, tabela fixa e auditável): os 2 agentes
CLI reais e autenticados nesta máquina (`agent_codex_cli_developer`,
`agent_claude_code_architect`) mapeiam para Codex/Claude Code
respectivamente -- a identidade que essas duas personagens já tinham em
todo o projeto. Os demais 9 agentes (mock + HTTP-API) mapeiam pelas mesmas
convenções de papel já estabelecidas em `roleMapping.ts`. Quando dois
agentes reais mapeiam para a mesma personagem e ambos estão ativos ao
mesmo tempo (raro na prática -- o DAG normalmente atribui um agente por
etapa), o estado mais "urgente" vence (ERROR > MEETING > RATE_LIMITED >
trabalho > espera > ocioso), nunca uma condição de corrida silenciosa.

`RealOfficeAdapter` é **stateful de propósito**: guarda o último estado
real traduzido por personagem para escolher o `AgentEvent` certo na
transição (`WORKING` vindo de `MEETING` → `meeting_ended`, vindo de
`RATE_LIMITED` → `provider_recovered`, do zero → `task_assigned`) --
nunca reemite o mesmo evento sem uma mudança real (testado em
`RealOfficeAdapter.test.ts`, 9 casos, incluindo o bug real encontrado e
corrigido durante a escrita dos testes: um agente que ficava `IDLE` não
disparava `reset` nenhum e a personagem ficava presa na pose de trabalho
para sempre).

**Curto vs. longo cooldown com dado real**: `cooldownMs` vem de
`retry_after_seconds` (convertido para ms) quando o provider informou um;
quando não informou, a política do próprio enunciado (seção 36) é seguida
literalmente -- tratado como curto (sofá), nunca inventado como longo.

**Reconstrução ao reabrir o app (spec seção 72/73)**: `useRealOfficeSync`
faz uma sincronização real assim que monta, antes de qualquer evento ao
vivo -- se um provider já estava com problema de saúde quando o app foi
fechado (`provider_health` sobrevive no SQLite), o agente correspondente
aparece direto no Lounge/Recovery Room, nunca de volta na mesa por engano.
`core.orchestrator.recovery.recover_interrupted_work` (já existia) cuida
da metade "backend": nenhuma execução trava em `running` para sempre após
um crash -- é marcada `failed_interrupted` antes do bridge aceitar
qualquer request, então o frontend nunca vê uma execução fantasma ainda
"ativa" para tentar reconstruir.

**Escopo deliberadamente não coberto nesta rodada** (ver relatório de
entrega para a lista completa): o tooltip ainda não mostra "Fallback
from: Codex" quando `FALLBACK_USED` troca o provider ativo de um agente
(o provider *atual* já aparece corretamente via `virtual.provider`, só a
anotação explícita do fallback não foi fiada até a UI); o frontend deriva
`MEETING` pela mesma heurística de sempre (modo debate/consensus + 2+
agentes rodando) em vez de consumir diretamente os novos eventos
`meeting.*` (equivalentes na prática, já que os dois lados leem o mesmo
sinal real); e não há uma segunda dimensão de "quem cada agente real
está revisando" além do papel fixo.

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

Este mapa de estados agora alimenta `RealOfficeAdapter` (acima) em vez de
`OfficeController`/círculos coloridos (Estágio 1, removido no Estágio 3
por estar definitivamente órfão -- nada mais implementava a interface
`SceneLike` que ele exigia desde a reescrita da `OfficeScene` no Estágio
2). `officeStore.ts`/`useOfficeSync.ts` (Estágio 1) também foram removidos
pelo mesmo motivo: zero consumidores restantes depois que
`useRealOfficeSync` assumiu o papel de sincronizar com dados reais.

## Fluxo de rate limit → Lounge → retomada

`ProviderHealthMonitor` (`core/providers/health.py`) classifica um
provider como `degraded`/`rate_limited`/`unavailable` a partir de um erro
real (`ProviderRateLimitError`/`ProviderAuthenticationError`/etc.) e agora
**empurra** essa mudança para o frontend em tempo real (não mais só um
poll de 15s) via `make_provider_health_bridge_sink`. Quando o step em
andamento de um agente usa um provider nesse estado,
`deriveOfficeSnapshot` o coloca em `RATE_LIMITED`; `RealOfficeAdapter`
decide sofá vs. cama pelo `retryAfter` real e, quando o provider volta,
o mesmo agente resume exatamente a tarefa salva (`AgentStateMachine`,
Estágio 2, inalterada).

## Reuniões (meetings)

Duplamente real agora: o backend (`MeetingManager`) publica os eventos
nomeados e auditáveis; o frontend deriva o mesmo resultado visual da
mesma condição real (`task.mode` `debate`/`consensus` **e** 2+ agentes
com steps `running` simultaneamente) via `deriveOfficeSnapshot`. Nunca
fabricado para parecer mais dinâmico -- só acontece quando o DAG
genuinamente executa múltiplos agentes em paralelo sob esses modos.

## Task Board

O Task Board físico no mundo 2D (Estágio 1/2) continua navegando para a
página real de Tarefas ao ser clicado -- ver GAME_ENGINE.md. Um overlay
com colunas reais (Backlog/Ready/In Progress/.../Done/Failed) dentro do
próprio canvas, conforme sugerido na spec do Estágio 3 seção 63, não foi
construído nesta rodada (a página real de Tarefas já cobre a mesma
necessidade); listado como pendência.

## Bug real encontrado e corrigido durante a implementação

Além do bug do Estágio 1 (loop infinito do `OfficeTaskBoard`, já
documentado antes), o Estágio 3 encontrou e corrigiu, todos com teste de
regressão:

- `Router.status_of(...)` vs. `is_available(...)`: o teste de fallback
  inicialmente usava `is_available` (só fica falso quando o circuit
  breaker abre após várias falhas) em vez de `status_of` (reflete o
  status explícito real imediatamente) -- um único `ProviderRateLimitError`
  não bastava para o `ExecutionEngine` perceber o provider como
  indisponível. Corrigido para checar `status_of`.
- `RealOfficeAdapter`: um agente real que fica `IDLE` não emitia nenhum
  evento -- a personagem ficava presa na última pose de trabalho para
  sempre. Corrigido emitindo `reset` na transição para `IDLE`/`OFFLINE`.

## Persistência

Tabelas reais já existentes (`tasks`, `executions`, `execution_steps`,
`provider_health`, `routing_decisions`, `execution_events`, ...) cobrem a
maior parte da spec do Estágio 3 seção 7/71 sem nenhuma tabela nova, exceto
as 2 colunas novas de `agents` (`preferred_provider`/`fallback_providers`,
migração `0005`). Posições/layout do escritório continuam não persistidos
-- não é necessário, já que `useRealOfficeSync` reconstrói o snapshot
inteiro a partir do estado real do backend a cada boot.

## Modo Classic Dashboard

Inalterado desde o Estágio 1: o Office é a página padrão, mas "Tarefas"
continua inteiramente funcional e a um clique de distância.

## Pendências reais (não escondidas)

- Frontend deriva `MEETING` pela heurística de sempre, não consumindo
  diretamente os novos eventos `meeting.*` (resultado equivalente hoje).
- Nenhum overlay de Task Board com colunas dentro do canvas (a página
  real de Tarefas já cobre isso).
- Sessão do Codex/Claude Code CLI (spec seção 84-86) não é explicitamente
  preservada/reexibida entre chamadas -- o adapter CLI já mantém seu
  próprio contexto interno real, mas o AgentMash não expõe esse id de
  sessão na UI.
- Gemini CLI não está instalado nesta máquina -- qualquer cenário
  envolvendo Gemini real é `UNVERIFIED EXTERNAL DEPENDENCY`; os testes ao
  vivo desta rodada usaram Codex CLI e Claude Code CLI, os dois
  genuinamente autenticados aqui.
