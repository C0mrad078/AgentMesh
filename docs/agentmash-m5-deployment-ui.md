# AgentMash M5 — Deployment Center UI

The frontend deployment surface is implemented in the owned desktop files:

- `types/deployment.ts` mirrors the concrete wire DTOs from contract section 4.1 and `core/deployment/models.py`.
- `services/deploymentApi.ts` exposes all 16 `deployment.*` bridge commands with typed inputs and outputs.
- `stores/deploymentStore.ts` loads persisted environments/releases, refreshes selected release details, and coalesces all deployment event topics. Actions only refresh after a backend response; no operation claims success optimistically.
- `pages/DeploymentCenterPage.tsx` and `components/deployment/DeploymentCards.tsx` expose the development → staging → production pipeline, release/SHA, approval, workflow/run, health, sanitized log, telemetry, incident, recovery and rollback evidence.

The page intentionally does not modify application routing. The Lead owns the shared `App.tsx` integration and should route `/deployment` and `/deployment/:releaseId` to `DeploymentCenterPage` in Onda 3.

Security-sensitive values are represented only by backend-sanitized DTO fields. The UI does not accept or display raw credentials; health profiles expose only a secret reference.
