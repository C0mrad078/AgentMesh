# Marco 5 — Backend Delivery handoff

Implementação entregue nos arquivos owned do Backend Delivery:

- adaptador GitHub Actions com dispatch, runs, status, jobs, cancelamento, polling e sanitização;
- `DeploymentService` com idempotência, SHA imutável, leases, reconciliação fail-closed e promoção;
- health checks HTTP/local command com timeout, retries e persistência sanitizada;
- `DeploymentOrchestrator` como facade para bridge/startup.

O serviço usa exclusivamente as entidades, repository, leases, recovery e policies existentes da migration 0021. Estados remotos ausentes, inconsistentes ou com SHA divergente tornam-se `blocked`, nunca `succeeded`.
