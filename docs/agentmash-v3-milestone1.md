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

## Implementação entregue

O corte vertical foi implementado em `core/missions/`, na migration
`0014_collaborative_missions.sql`, no bridge (`mission.create`, `mission.list`,
`mission.get`, `mission.command`) e na página `AgentWorkspacePage`.

O backend persiste missão, plano versionado, atribuição, sessão, mensagem,
artefato, revisão, instrução e eventos imutáveis. A interface é uma projeção
React Flow desses registros; o Pixel Office continua disponível em sua rota
secundária. O worker e o reviewer usam identidades diferentes, o reviewer não
pode aprovar trabalho do próprio agente, e o workspace é protegido por lease
serializado enquanto worktrees ainda não têm lifecycle operacional.

O fluxo real foi validado com Codex CLI autenticado: plano, três sessões,
handoff, artefatos, revisão, aprovação, testes e reabertura do banco. Claude
Code foi detectado e autenticado, mas uma execução foi bloqueada pela quota
semanal do provider; esse diagnóstico permaneceu bloqueado e nunca foi
convertido em sucesso.

## Verificação final

- Python: `613 passed, 9 skipped`.
- Frontend: `153 passed`; typecheck, lint e build aprovados.
- Rust/Tauri: fmt, clippy e `9` testes aprovados.
- A execução real com Codex registrou `102` eventos persistidos e sobreviveu
  ao fechamento/reabertura do banco.
