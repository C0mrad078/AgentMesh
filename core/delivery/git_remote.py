from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from typing import Any

from core.delivery.models import RemoteRepositoryBinding
from core.delivery.security import private_run, ref, sanitize_url, sha
from core.utils.errors import ValidationError
from core.utils.shell_runner import ShellRunner, get_runner


class GitRemote:
    def __init__(self, runner: ShellRunner | None = None) -> None:
        self.runner = runner or get_runner()

    async def run(self, root: Path, args: list[str], *, allowed: tuple[int, ...] = (0,)) -> str:
        result = await private_run(
            self.runner,
            [
                "git",
                "-c",
                f"core.hooksPath={os.devnull}",
                "-c",
                "protocol.file.allow=never",
                "-c",
                "protocol.ext.allow=never",
                "-c",
                "diff.external=",
                *args,
            ],
            cwd=root,
            timeout=120,
            env={"GIT_TERMINAL_PROMPT": "0", "GIT_SSH_COMMAND": "ssh -oBatchMode=yes"},
            max_stdout_bytes=8 * 1024 * 1024,
        )
        if result.returncode not in allowed:
            # Git may echo a credentialed configured URL even for a benign failure.
            raise ValidationError(
                f"Git {args[0]} failed (exit {result.returncode}); inspect local configuration"
            )
        if "[output truncated" in result.stdout:
            raise ValidationError(
                "Git evidence exceeds safe capture limit; human intervention required"
            )
        return result.stdout

    async def head(self, root: Path) -> str:
        return sha((await self.run(root, ["rev-parse", "HEAD"])).strip())

    async def clean_tree(self, root: Path) -> bool:
        return not (
            await self.run(root, ["status", "--porcelain=v1", "--untracked-files=all"])
        ).strip()

    async def ancestor(self, root: Path, base: str, head: str) -> bool:
        result = await private_run(
            self.runner,
            ["git", "merge-base", "--is-ancestor", sha(base), sha(head)],
            cwd=root,
            timeout=30,
        )
        if result.returncode not in (0, 1):
            raise ValidationError("Cannot verify commit ancestry")
        return result.returncode == 0

    async def verify_remote(self, root: Path, binding: RemoteRepositoryBinding) -> None:
        name = ref(binding.remote_name)
        # Multiple push destinations, URL rewriting, and credentialed URLs are blocked.
        for flag in ([], ["--push"]):
            values = (
                await self.run(root, ["remote", "get-url", *flag, "--all", name])
            ).splitlines()
            if len(values) != 1 or sanitize_url(values[0]) != binding.remote_url_sanitized:
                raise ValidationError("Configured remote differs from approved binding")
            original = values[0]
            canonical = sanitize_url(original)
            if original.startswith("https://") and original != canonical:
                raise ValidationError(
                    "Remove credentials/query parameters from configured remote URL"
                )
        rewrites = await self.run(
            root,
            ["config", "--get-regexp", r"^url\..*\.(insteadof|pushinsteadof)$"],
            allowed=(0, 1),
        )
        if rewrites.strip():
            raise ValidationError("URL rewrite rules require human review")

    async def remote_sha(
        self, root: Path, binding: RemoteRepositoryBinding, branch: str
    ) -> str | None:
        await self.verify_remote(root, binding)
        output = await self.run(
            root,
            ["ls-remote", "--heads", binding.remote_url_sanitized, f"refs/heads/{ref(branch)}"],
        )
        lines = output.splitlines()
        if not lines:
            return None
        if len(lines) != 1:
            raise ValidationError("Ambiguous remote branch")
        return sha(lines[0].split()[0])

    async def fetch(self, root: Path, binding: RemoteRepositoryBinding, branch: str) -> str:
        await self.verify_remote(root, binding)
        await self.run(
            root,
            [
                "fetch",
                "--no-tags",
                "--no-recurse-submodules",
                binding.remote_url_sanitized,
                f"refs/heads/{ref(branch)}",
            ],
        )
        return sha((await self.run(root, ["rev-parse", "FETCH_HEAD"])).strip())

    async def push(
        self, root: Path, binding: RemoteRepositoryBinding, branch: str, head: str
    ) -> dict[str, Any]:
        if not branch.startswith("agentmash/delivery-") or branch == binding.target_branch:
            raise ValidationError("Only controlled delivery branches can be pushed")
        existing = await self.remote_sha(root, binding, branch)
        if existing == head:
            return {"head_sha": head, "branch": branch, "reconciled": True}
        if existing:
            await self.fetch(root, binding, branch)
            if not await self.ancestor(root, existing, head):
                raise ValidationError("Non-fast-forward push blocked")
        await self.run(
            root,
            [
                "push",
                "--porcelain",
                binding.remote_url_sanitized,
                f"{sha(head)}:refs/heads/{ref(branch)}",
            ],
        )
        observed = await self.remote_sha(root, binding, branch)
        if observed != head:
            raise ValidationError("Remote branch changed during push; human intervention required")
        return {"head_sha": observed, "branch": branch}

    async def evidence(self, root: Path, base: str, head: str) -> dict[str, Any]:
        span = f"{sha(base)}..{sha(head)}"
        diff = await self.run(
            root, ["diff", "--no-ext-diff", "--no-textconv", "--binary", base, head, "--"]
        )
        normalized = diff.replace("\r\n", "\n")
        log = await self.run(root, ["log", "--format=%H%x00%s%x00%an%x00%aI", span, "--"])
        commits = []
        for line in log.splitlines():
            parts = line.split("\x00")
            if len(parts) != 4:
                raise ValidationError("Invalid commit metadata")
            commits.append(dict(zip(("sha", "message", "author", "timestamp"), parts, strict=True)))
        stats = await self.run(root, ["diff", "--no-renames", "--numstat", "-z", base, head, "--"])
        names = await self.run(
            root, ["diff", "--no-renames", "--name-status", "-z", base, head, "--"]
        )
        tokens = names.rstrip("\x00").split("\x00") if names else []
        statuses = {
            tokens[i + 1]: {"A": "added", "D": "deleted"}.get(tokens[i], "modified")
            for i in range(0, len(tokens), 2)
        }
        files = []
        binary = []
        for entry in stats.rstrip("\x00").split("\x00") if stats else []:
            added, deleted, path = entry.split("\t", 2)
            files.append(
                {
                    "path": path,
                    "status": statuses[path],
                    "additions": int(added) if added != "-" else 0,
                    "deletions": int(deleted) if deleted != "-" else 0,
                }
            )
            if added == "-":
                binary.append(path)
        # Includes deleted/intermediate secrets that remain reachable in pushed commits.
        history = await self.run(
            root, ["log", "--format=%H", "-p", "--no-ext-diff", "--no-textconv", span, "--"]
        )
        return {
            "diff": normalized,
            "diff_hash": hashlib.sha256(normalized.encode()).hexdigest(),
            "commits": commits,
            "files": files,
            "binary": binary,
            "history": history,
        }

    async def blob(self, root: Path, head: str, path: str) -> tuple[int, str]:
        spec = f"{sha(head)}:{path}"
        size = int((await self.run(root, ["cat-file", "-s", spec])).strip())
        if size > 1024 * 1024:
            return size, ""
        return size, await self.run(root, ["cat-file", "blob", spec])

    async def revert(
        self,
        root: Path,
        binding: RemoteRepositoryBinding,
        merge_sha: str,
        branch: str,
        worktree: Path,
    ) -> str:
        target = await self.fetch(root, binding, binding.target_branch)
        if not await self.ancestor(root, merge_sha, target):
            raise ValidationError("Merge commit is no longer in target history")
        # A surviving worktree is evidence: never reset/overwrite it after an interrupted revert.
        if await asyncio.to_thread(worktree.exists):
            if not await self.clean_tree(worktree):
                raise ValidationError("Interrupted revert requires human recovery")
            head = await self.head(worktree)
            message = await self.run(worktree, ["log", "-1", "--format=%B"])
            if merge_sha not in message or head == target:
                raise ValidationError("Existing revert worktree cannot be safely reconciled")
            return head
        worktree.parent.mkdir(parents=True, exist_ok=True)
        await self.run(root, ["worktree", "add", "-b", ref(branch), str(worktree), target])
        parents = (
            await self.run(worktree, ["rev-list", "--parents", "-n", "1", sha(merge_sha)])
        ).split()
        args = ["revert", "--no-edit"]
        if len(parents) > 2:
            args += ["-m", "1"]
        await self.run(worktree, [*args, sha(merge_sha)])
        return await self.head(worktree)
