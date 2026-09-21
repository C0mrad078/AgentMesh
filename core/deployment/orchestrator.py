from __future__ import annotations

from core.deployment.service import DeploymentService


class DeploymentOrchestrator:
    """Lifecycle facade used by bridges and startup code."""

    def __init__(self, service: DeploymentService) -> None:
        self.service = service

    async def reconcile(self, project_id: str | None = None):
        return await self.service.reconcile_after_restart(project_id)

    async def deploy(self, *args, **kwargs):
        return await self.service.deploy(*args, **kwargs)

    async def promote(self, *args, **kwargs):
        return await self.service.promote(*args, **kwargs)

    async def poll(self, run_id: str):
        return await self.service.poll(run_id)

    async def cancel(self, run_id: str):
        return await self.service.cancel(run_id)

    async def rollback(self, *args, **kwargs):
        return await self.service.rollback(*args, **kwargs)
