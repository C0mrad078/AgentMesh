# AgentMash V3 — Marco 2

O Marco 2 adiciona execução paralela segura ao Agent Workspace. O líder continua produzindo um plano em linguagem natural, mas o backend valida o grafo e cria uma `Task` e uma `Session` independente para cada trabalho de escrita. Cada tarefa recebe uma branch e uma worktree em `.agentmash-worktrees/<project-hash>/`, sempre derivada do SHA base da missão.

## Fluxo

`MissionService.run_parallel` admite as tarefas prontas em ondas determinísticas. O `ParallelConcurrency` protege os slots do processo e `ParallelRepository` persiste leases com limites global, por provider, projeto e missão. O `ConflictForecast` compara áreas declaradas e registra sobreposições como `possible`, `likely` ou `confirmed`.

O trabalhador executa na própria worktree. O revisor usa uma sessão distinta e recebe o diff e os critérios; `changes_requested` devolve o ciclo ao trabalhador até o limite configurado. Entregas aprovadas são mescladas, em ordem determinística, em `agentmash/mission-<id>/integration`. Conflitos bloqueiam a missão e permanecem disponíveis para resolução controlada. O quality gate é executado sobre a worktree integrada e a missão chega a `awaiting_human_approval`; aprovar registra a decisão, mas não modifica a branch principal.

## Persistência e recovery

A migration `0015_parallel_worktrees.sql` estende worktrees e cria leases, forecasts, tentativas de integração, quality gates e decisões humanas. O snapshot da missão projeta esses registros para o Agent Workspace. Após reinício, sessões em execução são interrompidas, worktrees ausentes são marcadas `orphaned` e leases expirados são removidos; nenhuma worktree com mudanças é apagada automaticamente.

## Limitações do corte

Os limites de concorrência são valores seguros padrão (`4` global, `2` por provider, `3` por projeto e missão) e ainda não têm editor dedicado no painel. O quality gate usa o comando de testes reconhecido pelo `CommandPlanner`; typecheck, lint e build adicionais continuam sendo gates configuráveis do projeto. A resolução de conflito é bloqueada para intervenção explícita e não usa resolução automática cega.
