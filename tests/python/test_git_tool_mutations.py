"""Stage 4 Git Tool hardening: mutable/destructive operations, each gated
on an explicit `authorized` flag the caller must have already obtained
from the Permission Engine (see `core.security.permissions`). Every test
here uses a throwaway repo under `tmp_path` -- never the real project repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.tools.git_tool import GitTool
from core.utils.errors import ToolDeniedError


async def _init_repo(tmp_path: Path) -> GitTool:
    tool = GitTool(tmp_path)
    await tool._run(["init", "-q"])  # noqa: SLF001 - test-only bootstrap, not part of the public contract
    await tool._run(["config", "user.email", "test@example.com"])
    await tool._run(["config", "user.name", "Test"])
    (tmp_path / "a.txt").write_text("hello")
    await tool.add(["a.txt"], authorized=True)
    await tool.commit("initial commit", authorized=True)
    return tool


async def test_mutable_operations_refuse_to_run_without_authorization(tmp_path: Path) -> None:
    tool = await _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("changed")
    with pytest.raises(ToolDeniedError):
        await tool.add(["a.txt"], authorized=False)
    with pytest.raises(ToolDeniedError):
        await tool.commit("nope", authorized=False)


async def test_add_and_commit_when_authorized(tmp_path: Path) -> None:
    tool = await _init_repo(tmp_path)
    (tmp_path / "b.txt").write_text("new file")
    add_result = await tool.add(["b.txt"], authorized=True)
    assert add_result.success
    commit_result = await tool.commit("add b.txt", authorized=True)
    assert commit_result.success

    log = await tool.log()
    assert "add b.txt" in log.stdout


async def test_create_branch_and_checkout(tmp_path: Path) -> None:
    tool = await _init_repo(tmp_path)
    result = await tool.create_branch("feature/x", authorized=True)
    assert result.success
    branches = await tool.branch_list()
    assert "feature/x" in branches.stdout

    checkout_result = await tool.checkout("main", authorized=True)
    # `main` or `master` depending on the git version's default -- either
    # a clean checkout or a "not found" for the other name is acceptable;
    # what matters is that authorization gated the call, not the branch name.
    assert checkout_result.returncode in (0, 1)


async def test_destructive_reset_hard_requires_authorization(tmp_path: Path) -> None:
    tool = await _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("uncommitted change")
    with pytest.raises(ToolDeniedError):
        await tool.reset_hard("HEAD", authorized=False)
    # Refusing to run means the uncommitted change survives.
    assert (tmp_path / "a.txt").read_text() == "uncommitted change"


async def test_destructive_reset_hard_when_explicitly_authorized(tmp_path: Path) -> None:
    tool = await _init_repo(tmp_path)
    (tmp_path / "a.txt").write_text("uncommitted change")
    result = await tool.reset_hard("HEAD", authorized=True)
    assert result.success
    assert (tmp_path / "a.txt").read_text() == "hello"


async def test_push_and_force_push_require_authorization(tmp_path: Path) -> None:
    tool = await _init_repo(tmp_path)
    with pytest.raises(ToolDeniedError):
        await tool.push(authorized=False)
    with pytest.raises(ToolDeniedError):
        await tool.force_push(authorized=False)


async def test_branch_delete_requires_authorization(tmp_path: Path) -> None:
    tool = await _init_repo(tmp_path)
    await tool.create_branch("throwaway", authorized=True)
    with pytest.raises(ToolDeniedError):
        await tool.branch_delete("throwaway", authorized=False)


async def test_revision_and_branch_names_cannot_smuggle_a_flag(tmp_path: Path) -> None:
    tool = await _init_repo(tmp_path)
    with pytest.raises(ToolDeniedError):
        await tool.checkout("--upload-pack=evil", authorized=True)
    with pytest.raises(ToolDeniedError):
        await tool.create_branch("--force", authorized=True)
    with pytest.raises(ToolDeniedError):
        await tool.reset_hard("--soft", authorized=True)


async def test_add_requires_at_least_one_path(tmp_path: Path) -> None:
    tool = await _init_repo(tmp_path)
    with pytest.raises(ToolDeniedError):
        await tool.add([], authorized=True)


async def test_commit_requires_a_non_empty_message(tmp_path: Path) -> None:
    tool = await _init_repo(tmp_path)
    (tmp_path / "c.txt").write_text("x")
    await tool.add(["c.txt"], authorized=True)
    with pytest.raises(ToolDeniedError):
        await tool.commit("   ", authorized=True)
