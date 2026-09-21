# HANDOFF M5 — Backend Core

Agent: Backend Core (Codex 1)
Branch: `feat/v3-deployment-control`

## Escopo entregue

- Modelos Pydantic para ambientes, releases, snapshots, runs, tentativas, leases, aprovações, operações, incidentes, health checks, rollback, telemetria e recovery.
- Máquina de estados com os 27 estados normativos e transições explícitas.
- Políticas de origem de release, SHA idêntico na promoção e segregação produtor/aprovador.
- Lease de ambiente com aquisição atômica SQLite, renovação, liberação e expiração.
- Telemetria que mantém métricas não medidas como `null`.
- Reconciliação conservadora: runs em estado remoto desconhecido são bloqueados e recebem ação sugerida.
- Migration `0021_deployment_control_center.sql` e repository transacional para releases/runs/registros.

## Testes

```text
.venv/bin/pytest tests/python/test_deployment_core.py
.venv/bin/ruff check core/deployment core/database/repositories/deployment_repo.py tests/python/test_deployment_core.py
.venv/bin/mypy core/deployment core/database/repositories/deployment_repo.py
```

O commit deve ser feito somente após autorização explícita da janela exclusiva pelo Lead.

## Pendências de integração

Backend Delivery deve consumir estes modelos/repositórios em `service.py`, adapters, health checks, orchestrator e handlers. O wiring de bridge e os contratos de frontend permanecem fora deste escopo.
