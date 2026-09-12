from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from core.tools.command_planner import CommandPlanner, ProjectAction
from core.utils.errors import ToolExecutionError


def test_resolves_npm_script_when_present(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "vitest run"}}), encoding="utf-8"
    )
    planner = CommandPlanner(tmp_path)
    assert planner.resolve(ProjectAction.RUN_TESTS) == ["npm", "run", "test"]


def test_does_not_invent_npm_script_that_does_not_exist(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(json.dumps({"scripts": {}}), encoding="utf-8")
    planner = CommandPlanner(tmp_path)
    assert planner.resolve(ProjectAction.RUN_BUILD) is None


def test_resolves_pytest_for_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    planner = CommandPlanner(tmp_path)
    assert planner.resolve(ProjectAction.RUN_TESTS) == [sys.executable, "-m", "pytest"]


def test_resolves_ruff_lint_only_when_configured(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
    planner = CommandPlanner(tmp_path)
    assert planner.resolve(ProjectAction.RUN_LINT) == [sys.executable, "-m", "ruff", "check", "."]


def test_no_ruff_config_means_no_lint_command(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    planner = CommandPlanner(tmp_path)
    assert planner.resolve(ProjectAction.RUN_LINT) is None


def test_resolves_cargo_for_rust_project(tmp_path: Path) -> None:
    (tmp_path / "Cargo.toml").write_text("[package]\nname='x'\n", encoding="utf-8")
    planner = CommandPlanner(tmp_path)
    assert planner.resolve(ProjectAction.RUN_TESTS) == ["cargo", "test"]
    assert planner.resolve(ProjectAction.RUN_BUILD) == ["cargo", "build"]


def test_unknown_stack_resolves_to_none(tmp_path: Path) -> None:
    planner = CommandPlanner(tmp_path)
    assert planner.resolve(ProjectAction.RUN_TESTS) is None


async def test_run_raises_tool_execution_error_when_unresolvable(tmp_path: Path) -> None:
    planner = CommandPlanner(tmp_path)
    with pytest.raises(ToolExecutionError):
        await planner.run(ProjectAction.RUN_TESTS)


async def test_run_executes_resolved_command(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    planner = CommandPlanner(tmp_path)
    result = await planner.run(ProjectAction.RUN_TESTS, timeout=5.0)
    # pytest isn't necessarily installed as `python -m pytest` output we can
    # assert on here, but the command must at least execute without our
    # planner itself raising -- the RunResult always comes back, success or not.
    assert result.returncode in (0, 1, 2, 4, 5)
