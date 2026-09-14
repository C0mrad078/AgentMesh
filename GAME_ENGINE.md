# Game Engine (Estágio 1+2 — AgentMash 2D Game Foundation + Autonomous Office)

Documenta o motor 2D real por trás da tela Office: tilemap Tiled, grid de
navegação, colisão, A*, câmera, e (desde o Estágio 2) o sistema de
agentes autônomos que substituiu o Owner controlável pelo usuário. A
integração com dados reais do backend orquestrador está agora em
**[docs/agentmash-v2-phase4.md](docs/agentmash-v2-phase4.md)**
(`VIRTUAL_OFFICE.md` documenta a integração antiga, Estágio 3, já
superada).

> **Nota (AgentMash V2, Phase 4)**: o motor descrito abaixo continua real
> e em produção sem mudanças de arquitetura visual -- mas o roster de
> personagens deixou de ser os "quatro agentes nomeados" fixos citados
> logo abaixo. `AGENT_DEFINITIONS`/`agentDefinition()` (o array estático)
> foram removidos; `buildAgentDefinition()` (`appearancePresets.ts`)
> constrói uma definição por agente real, e o roster pode ter qualquer
> número de personagens (limitado a `WORKSTATION_CAPACITY` = 4 mesas
> simultâneas antes do overflow para o lounge). As 4 spritesheets em si
> não mudaram -- continuam sendo os únicos 4 visuais reais existentes,
> agora tratados como um pool de presets em vez de identidades fixas.

**Critério de aceitação**: abrir a tela Office deve parecer uma empresa
de IA rodando sozinha dentro de um jogo 2D 16-bit — o usuário observa e
comanda a câmera, nunca um personagem.

## Estágio 2 mudou a direção do produto

O Estágio 1 tinha um personagem `Owner` controlado por WASD/clique. O
Estágio 2 **removeu esse personagem inteiramente** (spec: "o usuário NÃO
deverá controlar um personagem") e o substituiu por quatro agentes
nomeados e autônomos -- Gemini CEO, Gemini Designer, Codex, Claude Code
-- cujo único "controlador" é `AgentStateMachine`. `Player.ts`,
`NPC.ts` e `InteractionManager.ts` (todos dependiam de um personagem do
usuário) foram deletados, não deprecados.

## Por que isto não é uma simulação decorativa

Nada aqui é `setTimeout` fingindo atividade. Todo movimento autônomo
passa pelo mesmo `NavigationService.findPath` (A* real sobre o grid
real) e pela mesma `Character.update()` (avança tile a tile, nunca
`sprite.x = target.x`). O único `setTimeout` real do código
(`AgentStateMachine.scheduleSettle`) só resolve a transição cosmética
`COMPLETED -> IDLE` depois da animação de celebração -- documentado e
testado com fake timers.

## Estrutura de arquivos

```
desktop/src/game/
  Game.ts                      -- factory único do Phaser.Game
  scenes/
    BootScene.ts                -- carrega tileset/spritesheets/ícones, registra o tilemap
    OfficeScene.ts               -- desenha o mundo, dono dos 4 Agents/câmera/debug
  entities/
    Character.ts                -- núcleo de movimento/animação compartilhado
    Agent.ts                     -- um agente nomeado e autônomo (spec seção 4/8/30)
  agents/
    types.ts                     -- AgentState/DestinationId/AvatarAppearance/AgentDefinition
    appearancePresets.ts          -- os 4 presets reais (Gemini CEO/Designer, Codex, Claude)
    AgentStateMachine.ts          -- SimulationService -> AgentEvent -> aqui -> destino/animação
  simulation/
    OfficeSimulationService.ts   -- Developer Mode: os 6 cenários + 10 controles de debug
  systems/
    NavigationService.ts         -- A* real sobre o grid de colisão real
    RoomRegistry.ts               -- qual sala é qual, detecção "estou em qual sala"
    ObjectRegistry.ts             -- objetos interativos (computador, task board)
    CameraController.ts           -- follow/zoom/pan/bounds/reset
    OccupancySystem.ts             -- reserva genérica de "um agente por vaga" (spec seção 40)
    WorkstationSystem.ts           -- desk/chair/computer + approach/seat point
    BedSystem.ts                   -- 2 camas reais, sleep/approach point
    SofaSystem.ts                  -- 2 assentos reais de sofá
    MeetingRoomSystem.ts           -- 4 cadeiras reais de reunião
  maps/
    agentmashHq.json              -- o mapa Tiled real (8 salas -- ver "Tilemap")
    agentmashHq.ts                 -- leitor puro do JSON (sem Phaser), usado por testes
    roomTypes.ts                   -- RoomId canônico (fato do mapa, não do backend)
    tileIds.ts                     -- ids de tile referenciados fora do JSON
  assets/
    tileset.png                    -- atlas 8x8 de tiles 32x32
    status_icons.png                -- 6 glifos pixel art (zzz/erro/pensando/espera/café/estrela)
    gemini_ceo.png, gemini_designer.png, codex.png, claude_code.png
                                     -- spritesheets: 4 direções x (walk + seat) + lying + celebrate
```

`desktop/src/components/PhaserOffice.tsx` monta exatamente um
`Phaser.Game` (via `createOfficeGame`) e nunca re-renderiza em resposta a
estado do jogo. React só emite comandos de câmera via `ref` e recebe
eventos de hover/click/task-board/summary via props (spec seção 37/38).

## Tilemap

Mapa **AgentMash HQ**, Tiled JSON real (`orthogonal`, 32px, 40x30),
gerado por `scripts/generate_office_map.py` (sem Tiled Editor GUI neste
ambiente -- o script escreve exatamente o schema que o editor real
produziria). Tileset e os 4 spritesheets nomeados são pixel art simples
e original (`scripts/generate_office_assets.py`, via Pillow) --
parametrizada por um dict `PRESETS` que espelha
`game/agents/appearancePresets.ts` (spec seção 45/46: arquitetura de
customização real, ainda sem editor em-app).

8 salas reais, cada uma com identidade visual própria (spec seção 3):
CEO Office (quadro estratégico, estante, monitor de operação), Meeting
Room (quadro, mesa, 4 cadeiras), Design Desk (tablet de desenho,
paleta de cores), Frontend Desk (monitor extra), Backend Desk (2
racks de servidor), Testing Lab (equipamento de teste + servidor),
Lounge (sofá, cafeteira real, planta), e a nova **Recovery Room** (2
camas + puff).

Layers (ordem real do arquivo): `Ground`, `Floor`, `FloorDetails`,
`WallsBottom`, `FurnitureBottom`, `Collision` (invisível, única fonte de
colisão), `Objects` (computadores + task board), `Zones` (uma por sala),
`SpawnPoints` (`agents_entry` + um ponto por destino nomeado --
desks, camas, sofás, cadeiras de reunião), `FurnitureTop`, `WallsTop`.

## Colisão e Pathfinding

Sem mudanças de arquitetura desde o Estágio 1: `Collision` é a única
fonte de verdade (`agentmashHq.ts::isWalkable`), e
`NavigationService.findPath` (A* 4-direcional puro) é usado
identicamente por todo mundo -- os mesmos 4 personagens visuais, agora
movidos por eventos reais (`RealOfficeAdapter`, ver VIRTUAL_OFFICE.md) em
vez da simulação. Camas e assentos de sofá **não** colidem (mesmo padrão
de cadeira/mesa do Estágio 1): o ponto de dormir/sentar é o próprio tile
do móvel, walkable, e a profundidade do personagem o desenha por cima.

## Agentes autônomos (spec seção 4-30)

`AGENT_DEFINITIONS` (`appearancePresets.ts`) descreve os 4 agentes
fixos -- id, nome, `roleLabel`, textura, mesa/sala de origem,
aparência. `Agent extends Character`: some o controle de teclado do
Estágio 1; o único método de entrada é `applyRuntimeState(runtime)`,
chamado sempre que `AgentStateMachine` notifica uma mudança. Ele decide
se precisa andar (compara a tile atual com `destinationPoint(destino)`
e chama `NavigationService.findPath` + `moveAlongPath`, exatamente como
o antigo Owner) e qual pose tocar ao chegar.

### AgentStateMachine -- a regra central (spec seção 8/55-60)

Um único módulo puro (sem Phaser) resolve cada `AgentEvent` em
`{state, destination}` e reserva/libera mesas, camas, sofás e cadeiras
de reunião via `OccupancySystem`. Tabela `STATE_ANIMATION` (seção 58)
mapeia cada `AgentState` para `{pose, icon}` -- nunca um
`if (state === ...)` espalhado. Fluxos verificados (unit tests +
ao vivo, ver relatório):

- `task_assigned` -> estado de trabalho certo (CODING/DESIGNING/
  RESEARCHING/PLANNING) + vai para a própria mesa.
- `meeting_called` -> todos para uma cadeira real e distinta da Meeting
  Room; `meeting_ended` -> volta e **resume a mesma tarefa** salva antes
  da reunião (seção 16/24).
- `rate_limited(cooldownMs)` -> `cooldownMs >= sleepThresholdMs`
  (configurável, seção 23) decide sofá (RESTING) vs. cama (SLEEPING);
  `provider_recovered` -> acorda, volta, resume a tarefa salva.
- `error_occurred` -> para de trabalhar sem sair da mesa (seção 26).
- `waiting_on_dependency` / `dependency_resolved` -> pausa e resume sem
  perder a tarefa.
- `task_completed` -> `COMPLETED` (pose celebrate) e, sozinho depois de
  ~2.2s reais, assenta em `IDLE` (seção 28) -- o único timer do código,
  testado com `vi.useFakeTimers()`.

**"MOVING" é derivado, não armazenado**: `AgentRuntimeState.state`
guarda sempre o estado de negócio real (CODING, MEETING, ...);
enquanto o agente ainda está andando até lá, a UI (debug HUD, painel de
inspeção) mostra "MOVING" lendo `Character.isMoving`, não um valor
gravado pela state machine -- decisão deliberada para não exigir que o
módulo puro (que não conhece posição/tile) soubesse decidir sozinho
"já cheguei ou ainda não".

### Occupancy (spec seção 40/43)

`OccupancySystem` é uma única tabela de reserva (`spotId -> agentId`)
usada por `WorkstationSystem`, `BedSystem`, `SofaSystem` e
`MeetingRoomSystem`. Testado diretamente: nunca duas ocupações no mesmo
spot; liberar um spot o deixa livre para outro agente; pedir uma vaga
com todas ocupadas retorna `null` sem quebrar (o terceiro agente que
precisar de cama com as 2 já ocupadas ainda recebe um estado SLEEPING
coerente, só que sem uma cama própria reservada -- ver
"Pendências" no relatório).

**Avoidance de colisão entre agentes em trânsito não foi implementada**
(spec seção 43 permite "reservation" apenas, que é o que existe --
cada destino final é reservado; dois agentes cujos *caminhos* se cruzam
podem se sobrepor visualmente por um instante, resolvido pela
profundidade por Y, não por desvio de rota). Documentado como pendência
deliberada, não como bug escondido.

## Simulação (Developer Mode) -- spec seção 25/51-55

`OfficeSimulationService` é a única fonte de eventos neste estágio --
chamado exclusivamente pelo painel "Developer Mode" (ícone de chave
inglesa) em `OfficePage.tsx`, nunca por código de produção. Os 10
controles pedidos pela spec mais um "End Meeting" (necessário para
demonstrar o retorno às mesas): `Start Workday`, `Start Planning
Meeting`, `End Meeting`, `Rate Limit Codex`, `Long Cooldown Claude`,
`Recover Codex`, `Recover Claude`, `Send to Testing`, `Trigger Error`,
`Complete Task`, `Reset Office`. Trocar `OfficeSimulationService` por
eventos reais do Orchestrator no Estágio 3 não muda uma linha de
`AgentStateMachine` para baixo.

## Sprites e animação (spec seção 6/7/44/46-48)

Cada spritesheet (`32x48`, 10 linhas x 4 colunas): linhas 0-3 andar
(down/left/right/up, idle = coluna 0), linhas 4-7 sentado (mesmas 4
direções, colunas 1/3 erguem levemente os braços -- um loop sutil de
"digitando"), linha 8 deitado (sofá/cama, uma única pose compartilhada),
linha 9 celebrar. **Decisão de escopo documentada**: em vez de animar à
mão as 12 poses contextuais pedidas (typing/thinking/talking/meeting/
reading/testing/resting/sleeping/coffee/error/celebrate), a maioria
reaproveita {pose sentada ou deitada} + {um ícone de status pequeno}
(`status_icons.png`: zzz/erro/pensando/espera/café/estrela) -- real,
não emoji, pixel art de 16x16 -- em vez de uma pose desenhada única para
cada uma. `celebrate` e `error` (tint vermelho) têm pose própria por
serem visualmente centrais.

Os 4 agentes são reconhecíveis sem label (spec seção 47) por paleta +
acessório: CEO (terno azul-marinho + gravata), Designer (rosa + boina),
Codex (azul + headset), Claude (verde + óculos) -- nunca um logo oficial
como rosto.

## Câmera e interação com o usuário (spec seção 31-35)

`CameraController` inalterado desde o Estágio 1 (follow/zoom/pan/fit/
reset). O que mudou: `follow(target)` agora sempre aponta para um dos 4
agentes (nunca mais para um Owner). Clicar ou passar o mouse sobre um
agente nunca o controla -- abre `AgentDetailPanel` (nome, papel, estado,
tarefa, provider, sala, progresso) via `OfficeScene.inspect(agentId)`,
um método somente-leitura. O Task Board continua clicável (sem mais
checagem de raio/proximidade, já que não há personagem do usuário) e
navega para a página real de Tarefas.

## Debug mode

Tecla `` ` `` (ou o ícone de inseto): overlay de colisão, zonas,
caminho atual de cada agente em trânsito, e um HUD de texto com FPS e,
por agente, estado real/MOVING + sala + posição em tile.

## Testes automatizados (Estágio 2, novos)

- `game/agents/__tests__/AgentStateMachine.test.ts` (14 testes) --
  todo fluxo de evento/estado/destino/ocupação descrito acima.
- `game/systems/__tests__/OccupancySystem.test.ts` (6 testes) -- reserva,
  liberação, `claimAny` com vagas esgotadas.
- `game/maps/__tests__/agentmashHq.test.ts` -- agora 8 salas.
- `components/__tests__/AgentDetailPanel.test.tsx`,
  `pages/__tests__/OfficePage.test.tsx` -- reescritos para o painel de
  inspeção somente-leitura e o painel Developer Mode.

## Checklist de aceitação

Ver o relatório de entrega para os resultados reais de cada item e como
foram verificados (unit tests determinísticos + verificação ao vivo
dentro do Tauri/Chrome via stepping manual do game loop -- necessário
porque a automação de navegador roda a aba como "não focada", o que o
Chrome (não o Phaser) throttla agressivamente; documentado no relatório
como uma característica do ambiente de teste, não do jogo).
