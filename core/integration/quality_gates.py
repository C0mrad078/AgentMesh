"""Safe project quality-gate discovery and validation.

Commands are argv arrays, never shell strings. Detection only proposes files
that are present in the project and callers still persist/approve the profile
before execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

from core.integration.models import QualityGateDefinition
from core.utils.errors import ValidationError


def validate_gate(gate: QualityGateDefinition, project_root: Path) -> QualityGateDefinition:
    cwd = (project_root / gate.cwd).resolve()
    if not cwd.is_relative_to(project_root.resolve()):
        raise ValidationError("cwd do quality gate deve permanecer dentro do projeto")
    if any(not isinstance(part, str) or not part or "\x00" in part for part in gate.argv):
        raise ValidationError("argv inválido")
    if gate.argv[0] in {"sh", "bash", "zsh", "cmd", "powershell", "pwsh"}:
        raise ValidationError("shell arbitrário não é permitido em quality gates")
    return gate


def detect_gates(project_root: Path) -> list[QualityGateDefinition]:
    root = project_root.resolve()
    gates: list[QualityGateDefinition] = []
    package = root / "package.json"
    if package.exists():
        try:
            scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
        except (OSError, json.JSONDecodeError):
            scripts = {}
        for name, kind in (
            ("test", "test"),
            ("lint", "lint"),
            ("typecheck", "typecheck"),
            ("build", "build"),
        ):
            if name in scripts:
                gates.append(
                    QualityGateDefinition(
                        id=f"npm-{name}",
                        name=f"npm {name}",
                        argv=["npm", "run", name],
                        kind=cast(Literal["test", "lint", "typecheck", "build"], kind),
                        source="detected",
                        order=len(gates),
                    )
                )
    if (root / "pyproject.toml").exists() or (root / "tests").is_dir():
        gates.append(
            QualityGateDefinition(
                id="python-tests",
                name="Python tests",
                argv=["python", "-m", "pytest", "-q"],
                kind="test",
                source="detected",
                order=len(gates),
            )
        )
    if (root / "Cargo.toml").exists():
        gates.append(
            QualityGateDefinition(
                id="rust-tests",
                name="Rust tests",
                argv=["cargo", "test"],
                kind="test",
                source="detected",
                order=len(gates),
            )
        )
    return gates
