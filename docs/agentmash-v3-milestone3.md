# AgentMash V3 Marco 3

This milestone adds the first operations surface for the persisted V3
parallel engine. Runtime bindings now expose enabled state, diagnostics and
reconciliation timestamps; the desktop has a RuntimeBindings control page and
the Agent form selects a binding from the live catalog instead of asking for
an opaque id.

Quality gates are represented as project profiles containing validated argv,
relative working directory, timeout/retry/log policy, source and approval
metadata. `core.integration.quality_gates` only proposes commands discovered
from project files and rejects shell interpreters or paths outside the
project. Execution remains a backend responsibility.

Mission plans now carry an `ExecutionEnvelope`. The leader receives it before
planning; the backend classifies implementation and control stages, executes
ready workers in deterministic waves, and releases a completed worker lease
before the next wave or a reviewer/integrator stage. Queued work therefore
does not occupy slots or deadlock control Agents.

Migration `0017_integration_control_center.sql` adds profiles and the
auditable conflict, conflict-file, resolution-attempt, review and human
decision records. `IntegrationRepository` exposes these records to the
bridge and mission snapshots. A failed integration is persisted as a
classified conflict and shown in Agent Workspace; the integration branch and
the user's main branch remain separate.

The assisted flow now creates a real Vega session and resolution worktree,
captures Git stages, persists structured questions and worker answers, writes
an audited proposal commit, runs an independent Sentinel review and quality
profile, and waits for an explicit human decision before fast-forwarding the
integration branch. Binary, lockfile, migration/schema, generated and API
contract conflicts are classified conservatively and can be escalated to a
human.

The opt-in conflict smoke is intentionally still reporting a real external
limitation: the Codex planner generated more than two worker tasks, exhausted
the configured per-mission/provider capacity, and therefore did not reach a
Git conflict. The test fails with that diagnosis rather than fabricating a
successful resolution. The earlier Marco 2.1 parallel smoke remains green.

## Planning bounded e liveness

`PlanningPolicy` é persistida na Mission e no MissionPlan. No modo `bounded`,
`desired_workstreams` e `max_implementation_tasks` limitam Tasks de
implementação; passos sequenciais permanecem em `internal_steps`, enquanto
review, integração e QA são etapas sistêmicas do scheduler. No modo
autonomous, o líder conserva liberdade dentro do `ExecutionEnvelope`.

A migration `0019_planning_liveness.sql` persiste `tasks.waiting_reason`.
O scheduler executa workers em ondas determinísticas, libera leases ao
concluir cada worker e registra a razão quando uma tarefa aguarda correção.
Uma sessão Codex usa `--ignore-user-config` para impedir que um MCP inválido
e não relacionado ao projeto interrompa a execução; a autenticação continua
sendo a do próprio Codex CLI.

O smoke opt-in `tests/integration/test_integration_conflict_live.py` foi
executado com quatro Agents Codex. A política bounded produziu exatamente dois
workstreams: Atlas e Nova rodaram em worktrees distintas com sobreposição;
a integração gerou conflito textual real em `shared_contract.py`; Vega criou a
sessão e worktree de resolução, perguntou aos dois trabalhadores e persistiu
as respostas; Sentinel revisou independentemente. Após o gate e aprovação
humana, a branch de integração avançou e a `main` do fixture permaneceu no
SHA inicial. A execução passou em 360,69 s.
