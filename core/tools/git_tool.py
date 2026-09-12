"""Git operations, layered by mutability and risk.

Read-only operations (`status`/`diff`/`log`/`show`/`branch_list`) have
always been safe to run freely. Stage 4 adds the mutable operations the
brief asks for (`add`/`commit`/`checkout`/`create_branch`/`revert`/
`merge`) and the destructive ones (`push`/`force_push`/`reset_hard`/
`clean_fd`/`branch_delete`) -- but this tool itself never decides whether
an operation is *allowed*. Every mutable/destructive method takes an
explicit `authorized: bool` the caller must have already obtained from
`core.security.permissions.PermissionEngine` (see
`core.tools.tool_schemas.ToolExecutor`, the only real caller); the method
still enforces it as a second, independent gate (`ToolDeniedError` if not
`authorized`) rather than trusting the caller never to skip the check.

There is no method that accepts caller-supplied raw git arguments --
every operation is a fixed, reviewed argument vector.
"""

from __future__ import annotations

from pathlib import Path

from core.tools.base import Tool
from core.utils.errors import ToolDeniedError
from core.utils.shell_runner import RunResult, get_runner

_GIT_TIMEOUT_SECONDS = 15.0
_PUSH_TIMEOUT_SECONDS = 60.0


class GitTool(Tool):
    name = "git"

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root)
        self._runner = get_runner()

    async def _run(self, args: list[str], *, timeout: float = _GIT_TIMEOUT_SECONDS) -> RunResult:
        if not self.workspace_root.exists():
            raise ToolDeniedError(f"Workspace root '{self.workspace_root}' does not exist.")
        return await self._runner.run(
            ["git", *args], cwd=self.workspace_root, timeout=timeout, env=_GIT_ENV,
        )

    def _require_authorization(self, operation: str, authorized: bool) -> None:
        if not authorized:
            raise ToolDeniedError(
                f"Git operation '{operation}' was not pre-authorized by the Permission Engine.",
            )

    # -- read-only (always safe) ------------------------------------------

    async def status(self) -> RunResult:
        return await self._run(["status", "--porcelain=v1", "--branch"])

    async def diff(self, *, staged: bool = False) -> RunResult:
        args = ["diff", "--no-color"]
        if staged:
            args.append("--staged")
        return await self._run(args)

    async def log(self, *, max_count: int = 20) -> RunResult:
        return await self._run(["log", f"--max-count={max_count}", "--oneline", "--no-color"])

    async def show(self, revision: str) -> RunResult:
        return await self._run(["show", "--no-color", _safe_revision(revision)])

    async def branch_list(self) -> RunResult:
        return await self._run(["branch", "--list", "--no-color"])

    async def is_repository(self) -> bool:
        result = await self._run(["rev-parse", "--is-inside-work-tree"])
        return result.success and result.stdout.strip() == "true"

    # -- mutable (require pre-authorization) ------------------------------

    async def add(self, paths: list[str], *, authorized: bool) -> RunResult:
        self._require_authorization("GitAdd", authorized)
        if not paths:
            raise ToolDeniedError("GitAdd requires at least one path.")
        return await self._run(["add", "--", *paths])

    async def commit(self, message: str, *, authorized: bool) -> RunResult:
        self._require_authorization("GitCommit", authorized)
        if not message.strip():
            raise ToolDeniedError("GitCommit requires a non-empty message.")
        return await self._run(["commit", "-m", message])

    async def checkout(self, revision: str, *, authorized: bool) -> RunResult:
        self._require_authorization("GitCheckout", authorized)
        return await self._run(["checkout", _safe_revision(revision)])

    async def create_branch(self, name: str, *, authorized: bool) -> RunResult:
        self._require_authorization("GitCreateBranch", authorized)
        return await self._run(["checkout", "-b", _safe_branch_name(name)])

    async def revert(self, revision: str, *, authorized: bool) -> RunResult:
        self._require_authorization("GitRevert", authorized)
        return await self._run(["revert", "--no-edit", _safe_revision(revision)])

    async def merge(self, revision: str, *, authorized: bool) -> RunResult:
        self._require_authorization("GitMerge", authorized)
        return await self._run(["merge", "--no-edit", _safe_revision(revision)])

    # -- destructive (require pre-authorization; never run unattended) ----

    async def push(self, *, authorized: bool, remote: str = "origin", branch: str | None = None) -> RunResult:
        self._require_authorization("GitPush", authorized)
        args = ["push", _safe_branch_name(remote)]
        if branch:
            args.append(_safe_branch_name(branch))
        return await self._run(args, timeout=_PUSH_TIMEOUT_SECONDS)

    async def force_push(self, *, authorized: bool, remote: str = "origin", branch: str | None = None) -> RunResult:
        self._require_authorization("GitForcePush", authorized)
        args = ["push", "--force-with-lease", _safe_branch_name(remote)]
        if branch:
            args.append(_safe_branch_name(branch))
        return await self._run(args, timeout=_PUSH_TIMEOUT_SECONDS)

    async def reset_hard(self, revision: str, *, authorized: bool) -> RunResult:
        self._require_authorization("GitResetHard", authorized)
        return await self._run(["reset", "--hard", _safe_revision(revision)])

    async def clean_fd(self, *, authorized: bool) -> RunResult:
        self._require_authorization("GitCleanFd", authorized)
        return await self._run(["clean", "-fd"])

    async def branch_delete(self, name: str, *, authorized: bool) -> RunResult:
        self._require_authorization("GitBranchDelete", authorized)
        return await self._run(["branch", "-D", _safe_branch_name(name)])


#: Git commits/tags/branches are legitimately created by anyone with commit
#: access, including strings that could otherwise be read as a flag
#: (`--upload-pack=...`) by a naive `git <cmd> <ref>` call. Reject anything
#: starting with `-` so a malicious or accidental branch/revision name can
#: never be interpreted as an option -- this is defense in depth on top of
#: argv-array execution (already immune to shell injection).
def _safe_revision(revision: str) -> str:
    if not revision or revision.startswith("-"):
        raise ToolDeniedError(f"Refusing to use '{revision}' as a git revision.")
    return revision


def _safe_branch_name(name: str) -> str:
    if not name or name.startswith("-"):
        raise ToolDeniedError(f"Refusing to use '{name}' as a git branch/remote name.")
    return name


#: Git subprocesses never need the app's own secrets (API keys live in the
#: OS keychain, never in env vars anyway) but should still see enough of
#: the environment to find `git` itself and behave normally.
_GIT_ENV = {"GIT_TERMINAL_PROMPT": "0"}
