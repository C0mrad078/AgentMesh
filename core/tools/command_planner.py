"""Converts an abstract project action (`RunProjectTests`, `RunProjectBuild`,
`RunProjectLint`) into a concrete, safe command for the detected project
stack -- and refuses to guess when it cannot confirm the command actually
exists (e.g. no matching `package.json` script).

This is the layer that keeps `RunTest`/`RunBuild` tool calls (see
`core.tools.tool_schemas`) from ever inventing a command: `resolve()` always
checks for the stack's actual configuration before returning an argument
vector, and returns `None` -- never a guess -- when it can't confirm one.
"""

from __future__ import annotations

import json
import sys
from enum import Enum
from pathlib import Path

from core.tools.project_stack import ProjectStack, detect_stacks
from core.utils.errors import ToolExecutionError
from core.utils.shell_runner import RunResult, get_runner


class ProjectAction(str, Enum):
    RUN_TESTS = "run_tests"
    RUN_BUILD = "run_build"
    RUN_LINT = "run_lint"
    RUN_TYPECHECK = "run_typecheck"
    INSTALL_DEPENDENCIES = "install_dependencies"


_NODE_SCRIPT_NAMES: dict[ProjectAction, str] = {
    ProjectAction.RUN_TESTS: "test",
    ProjectAction.RUN_BUILD: "build",
    ProjectAction.RUN_LINT: "lint",
    ProjectAction.RUN_TYPECHECK: "typecheck",
}


class CommandPlanner:
    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root)
        self._runner = get_runner()

    def _node_scripts(self) -> dict[str, str]:
        package_json = self.workspace_root / "package.json"
        if not package_json.exists():
            return {}
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        scripts = data.get("scripts", {})
        return scripts if isinstance(scripts, dict) else {}

    def resolve(self, action: ProjectAction) -> list[str] | None:
        stacks = detect_stacks(self.workspace_root)

        if ProjectStack.NODE in stacks:
            if action == ProjectAction.INSTALL_DEPENDENCIES and (self.workspace_root / "package.json").exists():
                return ["npm", "install"]
            script_name = _NODE_SCRIPT_NAMES.get(action)
            if script_name and script_name in self._node_scripts():
                return ["npm", "run", script_name]

        if ProjectStack.PYTHON in stacks:
            if action == ProjectAction.RUN_TESTS and (self.workspace_root / "pyproject.toml").exists():
                return [sys.executable, "-m", "pytest"]
            if action == ProjectAction.RUN_LINT and _tool_configured(self.workspace_root, "ruff"):
                return [sys.executable, "-m", "ruff", "check", "."]
            if action == ProjectAction.RUN_TYPECHECK and _tool_configured(self.workspace_root, "mypy"):
                return [sys.executable, "-m", "mypy", "."]
            if action == ProjectAction.INSTALL_DEPENDENCIES and (self.workspace_root / "pyproject.toml").exists():
                return [sys.executable, "-m", "pip", "install", "-e", "."]

        if ProjectStack.RUST in stacks:
            if action == ProjectAction.RUN_TESTS:
                return ["cargo", "test"]
            if action == ProjectAction.RUN_BUILD:
                return ["cargo", "build"]
            if action == ProjectAction.INSTALL_DEPENDENCIES:
                return ["cargo", "fetch"]

        if ProjectStack.GO in stacks:
            if action == ProjectAction.RUN_TESTS:
                return ["go", "test", "./..."]
            if action == ProjectAction.RUN_BUILD:
                return ["go", "build", "./..."]
            if action == ProjectAction.INSTALL_DEPENDENCIES:
                return ["go", "mod", "download"]

        return None

    async def run(self, action: ProjectAction, *, timeout: float = 180.0) -> RunResult:
        argv = self.resolve(action)
        if argv is None:
            raise ToolExecutionError(
                f"Could not determine a safe '{action.value}' command for this project "
                "(no matching script/config found for its detected stack).",
            )
        return await self._runner.run(argv, cwd=self.workspace_root, timeout=timeout)


def _tool_configured(workspace_root: Path, tool_name: str) -> bool:
    pyproject = workspace_root / "pyproject.toml"
    if not pyproject.exists():
        return False
    try:
        content = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return f"[tool.{tool_name}" in content
