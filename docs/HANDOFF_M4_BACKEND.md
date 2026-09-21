# HANDOFF M4 — Backend / Delivery Engine

Agent: Codex 1 (Backend/Delivery Engineer)

Branch: `feat/m4-delivery-backend`

Worktree: `/Users/jhonatan/Downloads/AgentMash-m4-backend`

Commits de implementação:

- `dec0d74` — persistência imutável, migration, modelos, segurança e adapters remotos.
- `63a9c4a` — lifecycle, aprovações, CI/correção, recovery, bridge e testes de integração.

Escopo concluído:

- Candidate versionado e snapshot congelado: SHAs, SHA-256 do diff normalizado, commits, diff sanitizado, arquivos, tasks/critérios, agents/sessions, reviews, conflitos/resoluções, gates e riscos. Identidade do candidate, snapshots e aprovações protegidos por triggers SQLite.
- Bindings versionados com URL sanitizada; autenticação, permissões e proteções observadas no backend. Git/gh usam argv, ambiente limitado e supressão de observers para evidência bruta; nenhum token persistido. Remote divergente, URL rewriting, referências inseguras e push fora de branches de delivery são bloqueados.
- Preflight obrigatório: remote/auth, fetch/ancestralidade/base atual, HEAD/tree, hash do diff, perfil final de gates, segredos no diff/histórico/blobs, arquivos de credenciais, binários/grandes, migrations/lockfiles/generated e risco. Findings mascarados antes de persistência.
- Aprovação humana separada para push, PR create/update, merge e rollback, vinculada à versão/SHA. Novo preflight exige renovar aprovação; head remoto alterado bloqueia o fluxo.
- Idempotência por chave e por candidate/action, claim atômico de tentativa, resultado durável e reconciliação de push/PR/merge/revert. Tentativa terminada pode repetir após reconciliação; operação interrompida/incerta não é reaplicada cegamente.
- PR identificado por branch; atualização publica relatório de versão separado e preserva a descrição humana. CI/status checks, logs sanitizados, classificação de falha e intervalo mínimo de consulta de 15 segundos.
- Correção cria task e worktree novas a partir do head do PR, usa worker e reviewer distintos, verifica review persistida e gates, congela nova versão e exige novas aprovações. Máximo de três ciclos; interrupções preservam evidência e liberam leases.
- Merge valida novamente head, checks, reviews, mergeability, base e método permitido. Sem admin bypass ou force. Pós-merge confirma PR merged e presença do merge SHA na target, persistindo verificação e atualização da missão.
- Rollback por revert em worktree isolada, com gates/scan e PR de revert aprovado. Candidate permanece `rollback_proposed` até observar o revert merged na target; nenhum auto-merge do revert.
- PhaseTelemetry e InternalStep persistidos, incluindo agent/session/provider/task quando disponíveis, duração observada, retries, timeout, intervenção humana e recovery. Tokens/custo ausentes são `unknown`; esperas/identificadores/duração indisponíveis são `null`, conforme DTO, sem zero fabricado.
- Todos os 16 comandos delivery registrados, DTOs de entrada estritos, eventos e wiring de serviço no bridge. Timeout Python estendido somente para os sete comandos longos.

Arquivos alterados:

- `core/delivery/{__init__,models,security,git_remote,github_adapter,preflight,ci_monitor,state_machine,bridge,service}.py`
- `core/database/migrations/versions/0020_delivery_control_center.sql`
- `core/database/repositories/delivery_repo.py`
- `core/bridge/{context,handlers,server}.py`
- `core/security/allowlist.py`
- `core/orchestrator/{event_bus,event_sinks}.py`
- `tests/python/test_delivery_{adapters,engine}.py`
- Este handoff. Nenhum arquivo React/UI ou Rust foi alterado.

Contratos usados/alterados:

- Contrato compartilhado e seção 4.1 aprovados pelo Lead, incluindo commit `452f812`.
- Detail retorna `remote_operations`, `rollback_plan`, `internal_steps`, recovery, diff_files, remote_sha e pending_approvals; aliases `operations` e `rollback` também presentes.
- Extensões opcionais do snapshot, contexto do serviço e versionamento por `assign_fix` aprovados via Maestri.
- Lead aprovou `task_id`, `queue_wait_ms` e `human_wait_ms` opcionais na telemetria; `null` quando desconhecidos.
- Lead aprovou bloquear rebase merge neste marco e usar squash/merge para rollback previsível.
- A atualização do contrato compartilhado permanece sob propriedade do Lead.

Migrations:

- `0020_delivery_control_center.sql`: bindings, candidates, snapshots, records tipados e operations; índices, FKs, unicidade e triggers de imutabilidade.
- Cobertura de banco vazio, upgrade de 0019, reabertura, integridade, FKs e rejeição de alterações em snapshots/aprovações/bindings.

Testes executados e resultados finais:

- `.venv/bin/pytest`: **702 passed, 11 skipped**, 47,09s.
- Novos testes delivery: **77 passed**. Incluem SQLite e Git/worktrees/revert reais locais, ciclo worker/reviewer/gates com provider/remoto determinísticos, crash/retry/concurrency, contratos, masking, CI, merge e timeout.
- `.venv/bin/ruff check core tests`: **All checks passed**.
- `.venv/bin/mypy`: **Success: no issues found in 190 source files**.
- `git diff --check`: sem erros.
- `.venv/bin/ruff check .`: dois erros preexistentes e fora do escopo: `scripts/generate_office_assets.py:20` (I001) e `scripts/generate_office_map.py:311` (E702). Arquivos idênticos ao contrato-base `452f812`; preservados por acordo com o Lead.
- Primeiro smoke dentro do sandbox encontrou erro de Keychain macOS (-50); a suíte completa foi repetida com acesso autorizado fora do sandbox e passou. Dependências existentes reutilizadas, sem instalação.

Riscos e limites operacionais:

- Nenhum push remoto, PR real ou merge remoto foi executado no desenvolvimento. Testes determinísticos não substituem o smoke remoto privado/descartável de aceite.
- Adapter de PR/CI suporta GitHub.com. Git genérico por SSH pode fazer fetch/push; HTTPS genérico sem autenticação verificável permanece bloqueado no preflight. Proteções não observáveis bloqueiam a entrega.
- Perfil final precisa ter ao menos um gate obrigatório habilitado. Binários/arquivos maiores que 1 MiB e evidência acima do limite de captura bloqueiam preflight, preservando diagnóstico para revisão humana.
- Correção interrompida ou operação remota incerta sem evidência suficiente exige intervenção humana; nenhuma worktree/branch é removida automaticamente.
- Rollback entregue como PR de revert requer merge protegido separado; abrir o PR não é declarado como rollback concluído.

Pendências acordadas com o Lead:

1. **Glue Rust pelo Antigravity**, em `desktop/src-tauri/src/bridge/manager.rs`: Python usa **10800s** para `delivery.preflight.run`, `delivery.ci.assign_fix`, `delivery.remote.push`, `delivery.pr.create`, `delivery.pr.update`, `delivery.merge.execute`, `delivery.rollback.execute`. Recomenda-se Rust **10830s** nesses mesmos comandos, permitindo que o erro Python retorne antes do deadline do cliente. Demais comandos permanecem em 30s. Nome correto é `delivery.merge.execute`, não `delivery.pr.merge`.
2. Review independente dos commits, integração com UI e review do glue Rust pelo Codex 1, conforme combinado.
3. Smoke remoto real de CI/falha/correção/merge/revert em repositório privado descartável pelo Lead, sem usar o AgentMash real.

Higiene:

- `main` preservada em `8db13456c61fdbe91dfdbe55819b8fec3e6989ab`.
- Nenhuma alteração React/UI; nenhum reset destrutivo, force push ou admin bypass.
- Fontes técnicas consultadas para os argumentos do adapter: [gh pr merge](https://cli.github.com/manual/gh_pr_merge), [gh pr create](https://cli.github.com/manual/gh_pr_create), [gh pr checks](https://cli.github.com/manual/gh_pr_checks).
