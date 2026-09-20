# AgentMash V3 — Marco 1

## Baseline / plano de implementação

Branch: `feat/v3-agent-workspace`, origem `main` / `8db1345`; Git limpo.
Nenhum AGENTS.md/CLAUDE.md encontrado no repositório ou ancestrais.
Node 26.8.1, npm 11.19.0, Python 3.13.5, cargo 1.98.1.
Frontend baseline: 141 testes, typecheck/lint/build aprovados; aviso pré-existente
sobre tamanho do chunk Phaser. Python/Rust: resultados finais registrados abaixo.

Arquitetura encontrada: React → Tauri JSONL autenticado → Python → SQLite.
`SessionsRepository` e `TasksRepository` já existem. Os adaptadores
`CodexCliProvider`/`ClaudeCodeCliProvider` já controlam execução pelo ShellRunner;
a tabela Session ainda não estava ligada a eles. Worktrees possuem somente modelos.

Plano: migration aditiva e contratos → repositório/eventos → serviço de missão
sobre adaptadores existentes → revisão independente/correção/testes → React Flow
como projeção de estado persistido → recovery/verificação. Nenhum workflow manual.
Acesso ao workspace será serializado; não há promessa de isolamento por worktree.
