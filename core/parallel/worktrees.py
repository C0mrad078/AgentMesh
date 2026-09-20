from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path

from core.database.repositories.parallel_repo import ParallelRepository
from core.missions.models import Mission
from core.parallel.models import WorktreeLease
from core.utils.errors import ToolDeniedError, ValidationError
from core.utils.ids import new_id
from core.utils.shell_runner import get_runner
from core.utils.time import utc_now

_SAFE = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,180}$")


class WorktreeManager:
    """Creates task worktrees outside the project tree and never runs destructive Git commands."""

    def __init__(self, repo: ParallelRepository) -> None:
        self.repo = repo
        self.runner = get_runner()

    async def git(self, root: Path, args: list[str], timeout: float = 30.0):
        return await self.runner.run(["git", *args], cwd=root, timeout=timeout,
                                     env={"GIT_TERMINAL_PROMPT": "0"})

    async def base_sha(self, root: Path) -> str:
        result = await self.git(root, ["rev-parse", "HEAD"])
        if not result.success or not re.fullmatch(r"[0-9a-f]{40}", result.stdout.strip()):
            raise ValidationError("O projeto precisa de um commit-base Git válido.")
        return result.stdout.strip()

    def root_for(self, project_root: Path) -> Path:
        # Sibling directory, deterministic per project, never inside the project.
        digest = hashlib.sha256(str(project_root.resolve()).encode()).hexdigest()[:16]
        return project_root.resolve().parent / ".agentmash-worktrees" / digest

    async def create(self, *, mission: Mission, task_id: str, project_root: Path,
                     base_sha: str, branch_name: str) -> WorktreeLease:
        if not _SAFE.fullmatch(branch_name) or branch_name.startswith("-"):
            raise ValidationError("Nome de branch inseguro.")
        root, path, project_resolved = await asyncio.gather(
            asyncio.to_thread(self.root_for, project_root),
            asyncio.to_thread(lambda: (self.root_for(project_root) / task_id).resolve()),
            asyncio.to_thread(project_root.resolve),
        )
        if path == project_resolved or not path.is_relative_to(root.resolve()):
            raise ToolDeniedError("Worktree fora da raiz controlada.")
        await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
        if await asyncio.to_thread(path.exists):
            raise ValidationError("Diretório da worktree já existe; recuperação manual necessária.")
        worktree = WorktreeLease(
            id=new_id("wt"), mission_id=mission.id, task_id=task_id, project_id=mission.project_id,
            workspace_root=str(root), path=str(path), branch_name=branch_name, base_sha=base_sha,
            status="creating", created_at=utc_now(), updated_at=utc_now(),
        )
        await self.repo.create_worktree(worktree)
        result = await self.git(project_root, ["worktree", "add", "-b", branch_name, str(path), base_sha])
        if not result.success:
            await self.repo.update_worktree(worktree.id, status="orphaned", last_error=result.stderr[:1000])
            raise ValidationError(f"Falha ao criar worktree: {result.stderr[:1000]}")
        await self.repo.update_worktree(worktree.id, status="active")
        return worktree.model_copy(update={"status": "active"})

    async def commit(self, worktree: WorktreeLease, message: str) -> str:
        root = Path(worktree.path)
        if not root.is_relative_to(Path(worktree.workspace_root)):
            raise ToolDeniedError("Worktree escapou da raiz controlada.")
        status = await self.git(root, ["status", "--porcelain=v1"])
        if not status.success:
            raise ValidationError("Não foi possível inspecionar a worktree.")
        if not status.stdout.strip():
            head = await self.git(root, ["rev-parse", "HEAD"])
            return head.stdout.strip()
        add = await self.git(root, ["add", "--", "."])
        if not add.success:
            raise ValidationError(add.stderr[:1000])
        commit = await self.git(root, ["commit", "-m", message])
        if not commit.success:
            raise ValidationError(commit.stderr[:1000])
        head = await self.git(root, ["rev-parse", "HEAD"])
        if not head.success:
            raise ValidationError("Commit criado mas SHA não pôde ser lido.")
        await self.repo.update_worktree(worktree.id, head_sha=head.stdout.strip())
        return head.stdout.strip()

    async def integrate(self, *, worktree: WorktreeLease, integration_root: Path,
                        integration_branch: str) -> tuple[bool, str, str]:
        branch_result = await self.git(integration_root, ["show-ref", "--verify", f"refs/heads/{integration_branch}"])
        if not branch_result.success:
            created = await self.git(integration_root, ["branch", integration_branch, worktree.base_sha])
            if not created.success:
                return False, "", created.stderr[:1000]
        # The integration worktree owns this branch. Keep it attached so the
        # branch ref advances and restart/recovery can inspect the resulting SHA.
        checkout = await self.git(integration_root, ["checkout", integration_branch])
        if not checkout.success:
            return False, "", checkout.stderr[:1000]
        merge = await self.git(integration_root, ["merge", "--no-edit", worktree.branch_name])
        if not merge.success:
            # Abort only this temporary integration operation; no user branch is touched.
            await self.git(integration_root, ["merge", "--abort"])
            return False, "", merge.stderr[:1000]
        head = await self.git(integration_root, ["rev-parse", "HEAD"])
        return True, head.stdout.strip(), ""

    async def inspect(self, worktree: WorktreeLease) -> dict[str, str | bool]:
        path = Path(worktree.path)
        if not path.is_relative_to(Path(worktree.workspace_root)):
            raise ToolDeniedError("Worktree fora da raiz controlada.")
        exists = await asyncio.to_thread(path.is_dir)
        result = await self.git(path, ["status", "--porcelain=v1"]) if exists else None
        return {"exists": exists, "dirty": bool(result and result.stdout.strip()), "path": str(path),
                "branch": worktree.branch_name, "base_sha": worktree.base_sha,
                "head_sha": worktree.head_sha or ""}
