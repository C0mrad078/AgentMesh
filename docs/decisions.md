# Decisões arquiteturais — Estágio 1

Registro das decisões que afetam como os próximos estágios devem evoluir o
projeto. Cada entrada descreve o contexto, a decisão e as alternativas
descartadas.

## 1. Transporte do bridge: stdio + JSON Lines

**Contexto:** o Tauri precisa falar com o core Python de forma confiável,
segura e igualmente simples em macOS e Windows.

**Decisão:** o Python roda como processo filho do Tauri, com stdin/stdout
conectados por pipe. Cada mensagem é um objeto JSON por linha (`\n`
delimitado). `stdout` é reservado exclusivamente para o protocolo — todo log
do core vai para `stderr` e/ou arquivo (`core/utils/logging.py`), e
`guard_stdout()` substitui `sys.stdout` por um objeto que levanta exceção se
algo tentar escrever nele por engano.

**Alternativas descartadas:**
- *Named pipes/Unix sockets*: implementação duplicada por plataforma sem
  ganho real neste caso (relação 1:1 pai-filho).
- *HTTP/TCP local*: exige gerenciar porta e abre uma superfície de rede local
  que não existe com stdio.

**Consequência para estágios futuros:** o `ErrorPayload`/`RequestMessage`/
`ResponseMessage`/`EventMessage` (espelhados em `core/bridge/protocol.py` e
`desktop/src-tauri/src/bridge/protocol.rs`) são o contrato estável. Se um dia
for necessário trocar de transporte (ex.: multiplexar vários sidecars), o
payload não muda, só o transporte.

## 2. Allowlist única, em Python

**Contexto:** o bridge não pode virar um `execute_anything(cmd)`.

**Decisão:** `core/security/allowlist.py::BridgeCommand` é a única lista de
comandos válidos. `core/bridge/server.py` rejeita qualquer `command` fora
dessa lista antes de chegar a um handler. O lado Rust (`commands.rs`) expõe
apenas três comandos Tauri genéricos (`bridge_invoke`, `bridge_status`,
`bridge_reconnect`) — ele nunca precisa conhecer a lista de operações de
negócio, então as duas listas nunca podem divergir (só existe uma).

## 3. Sem shell genérico; ferramentas tipadas

**Contexto:** agentes (hoje mockados, no futuro reais) eventualmente vão
pedir para rodar comandos. Isso não pode virar RCE.

**Decisão:** `core/tools/git_tool.py` e `core/tools/terminal_tool.py`
expõem apenas métodos fixos (`GitTool.status()`, `GitTool.diff()`,
`TerminalCommand.PYTHON_VERSION`, etc.), cada um com um vetor de argumentos
hardcoded. A execução em si passa por `core/utils/shell_runner.py`, que usa
`asyncio.create_subprocess_exec` (nunca `shell=True` ou `create_subprocess_shell`).
`core/tools/path_guard.py` resolve todo caminho relativo contra a raiz do
workspace e rejeita qualquer resultado fora dela (`..`, caminho absoluto,
symlink escapando).

**Por que `PosixRunner` e `PowerShellRunner` existem sendo tecnicamente
iguais:** ambos executam o vetor de argumentos diretamente (sem interpretar
uma string de shell), porque todo argv que chega a essa camada já é fixo e
não vem de um agente ou usuário. Existirem como classes separadas (em vez de
uma função só) dá um lugar único e revisável por plataforma caso uma
capability futura realmente precise de um builtin do PowerShell — a decisão
de platform-branching já está centralizada em `get_runner()`.

## 4. Schemas de banco propositalmente largos

**Contexto:** o Estágio 1 não usa providers reais, aprendizado, nem
múltiplos agentes por execução — mas o Estágio 2+ vai.

**Decisão:** a migration inicial já cria `provider_configs`, `prompt_versions`,
`learned_rules` e `project_memories` com as colunas que esses recursos vão
precisar (`secret_ref`, `version`, `confidence`, `importance`), mesmo sem
repository/uso ainda. Isso evita uma migration destrutiva (`DROP`/`ALTER`
complexo) quando esses recursos forem implementados — só será necessário
popular as tabelas, não redesenhá-las.

## 5. Motor de execução em 6 fases fixas

**Contexto:** a interface precisa mostrar um quadro de progresso estável
("Analisando intenção", "Criando plano", ...) independente de quantos passos
de trabalho reais existirem dentro da fase de execução.

**Decisão:** `core/orchestrator/models.py::ExecutionPhase` fixa as 6 fases.
Cada fase vira uma linha em `execution_steps` (`kind="phase"`) e um evento
`orchestrator://event`. Dentro da fase `execution`, cada `PlanStep` do
`ExecutionPlan` vira uma linha adicional (`kind="work"`), permitindo que um
plano multi-passo (Estágio 2+) apareça como sub-itens sem mudar as 6 fases
visíveis.

## 6. Cancelamento real, não só de UI

**Contexto:** "cancelar" não pode significar apenas "a interface para de
esperar enquanto o processo continua rodando".

**Decisão:** `core/orchestrator/executor.py::StepExecutor` corre a chamada ao
provider e um `asyncio.Event` de cancelamento em paralelo
(`asyncio.wait(..., return_when=FIRST_COMPLETED)`). Se o cancelamento vence,
a tarefa do provider é de fato cancelada (`Task.cancel()`) e
`provider.cancel(retry_key)` é chamado. O mesmo `asyncio.Event` é checado
entre fases no `ExecutionEngine`, então cancelar durante `planning` ou
`routing` (não só durante `execution`) também interrompe o pipeline antes do
próximo passo custoso.

## 7. Recuperação de crash no startup

**Contexto:** se o processo for encerrado à força enquanto uma task está
`running`, nenhum `ExecutionEngine` está mais vivo para terminá-la.

**Decisão:** `core/orchestrator/recovery.py::recover_interrupted_work` roda
antes do bridge aceitar requisições. Toda task em `running`/`waiting`/
`reviewing` sem execução ativa correspondente é marcada `failed` com um
resultado explicando o motivo (`"Interrupted by application restart."`).
Não há tentativa de "retomar de onde parou" — isso exigiria persistir estado
intermediário de execução que não existe hoje, e silenciosamente continuar
uma execução após um crash seria mais arriscado do que reportar a falha e
deixar o usuário tentar de novo.

## 8. Reconexão do bridge como um único loop supervisor

**Contexto:** a primeira implementação do gerenciador de bridge em Rust usava
funções `async` que se chamavam mutuamente (conectar → ler stream → tratar
desconexão → reconectar → conectar de novo). Isso **não compila**: o Rust
precisa inferir um tamanho finito para o tipo anônimo de cada `Future`, e
esse ciclo de chamadas mútuas cria um tipo de tamanho infinito (erro
`future cannot be sent between threads safely`, decorrente de uma
recursão real no grafo de tipos, não apenas um lint).

**Decisão:** `BridgeManager::run_supervisor` é um único `loop {}` de
longa duração (roda pela vida inteira do app) chamando funções auxiliares
simples e não-recursivas (`connect_once`, `stream_until_disconnected`).
Reconexão manual (`reconnect_now`) apenas acorda esse loop via
`tokio::sync::Notify`, sem criar uma segunda instância do loop.

## 9. Status de conexão sempre visível

**Contexto:** o app não pode deixar a interface "travada" sem explicação
quando o core não responde.

**Decisão:** `BridgeStatus` (`Initializing | Connected | Reconnecting{attempt} | Offline | Error{message}`)
é emitido como evento Tauri (`orchestrator://status`) a cada mudança, e
também pode ser consultado a qualquer momento via `bridge_status`. O
`ConnectionBadge` na interface reflete isso ao vivo, e desabilita o envio de
novas tarefas quando não há conexão (`WorkspacePage`).
