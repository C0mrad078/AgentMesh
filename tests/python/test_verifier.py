from __future__ import annotations

from pathlib import Path

from core.orchestrator.models import StepResult, StepStatus
from core.orchestrator.verifier import Verifier


def _result(step_id: str = "s1", *, status: StepStatus = StepStatus.COMPLETED, output: str | None = "done") -> StepResult:
    return StepResult(step_id=step_id, status=status, output=output, agent_id="agent_1")


async def test_no_results_fails() -> None:
    verifier = Verifier()
    outcome = await verifier.verify([])
    assert outcome.passed is False
    assert outcome.reasons


async def test_all_completed_with_output_passes() -> None:
    verifier = Verifier()
    outcome = await verifier.verify([_result("s1"), _result("s2")])
    assert outcome.passed is True
    assert outcome.reasons == []
    assert len(outcome.checks) == 2


async def test_failed_step_fails_verification() -> None:
    verifier = Verifier()
    outcome = await verifier.verify([_result("s1", status=StepStatus.FAILED, output=None)])
    assert outcome.passed is False
    assert "failed" in outcome.reasons[0]


async def test_empty_output_fails_verification() -> None:
    verifier = Verifier()
    outcome = await verifier.verify([_result("s1", output="   ")])
    assert outcome.passed is False
    assert "empty" in outcome.reasons[0]


async def test_cancelled_step_fails_verification() -> None:
    verifier = Verifier()
    outcome = await verifier.verify([_result("s1", status=StepStatus.CANCELLED, output=None)])
    assert outcome.passed is False


async def test_no_workspace_skips_quality_gates(tmp_path: Path) -> None:
    verifier = Verifier()
    outcome = await verifier.verify([_result("s1")], categories=("coding",), workspace_path=None)
    assert outcome.passed is True
    assert len(outcome.checks) == 1  # only the step check, no project-level gates


async def test_quality_gates_run_and_pass_for_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    verifier = Verifier()
    outcome = await verifier.verify(
        [_result("s1")], categories=("coding",), workspace_path=str(tmp_path)
    )
    assert outcome.passed is True
    assert any(c.name == "run_tests" for c in outcome.checks)


async def test_quality_gates_run_and_fail_when_tests_fail(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "test_fail.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
    verifier = Verifier()
    outcome = await verifier.verify(
        [_result("s1")], categories=("coding",), workspace_path=str(tmp_path)
    )
    assert outcome.passed is False
    assert any(c.name == "run_tests" and not c.passed for c in outcome.checks)


async def test_quality_gates_skipped_when_command_cannot_be_confirmed(tmp_path: Path) -> None:
    verifier = Verifier()
    outcome = await verifier.verify(
        [_result("s1")], categories=("coding",), workspace_path=str(tmp_path)
    )
    assert outcome.passed is True
    assert len(outcome.checks) == 1


async def test_quality_gates_skipped_entirely_when_flag_disabled(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    (tmp_path / "test_fail.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
    verifier = Verifier()
    outcome = await verifier.verify(
        [_result("s1")], categories=("coding",), workspace_path=str(tmp_path), run_quality_gates=False,
    )
    assert outcome.passed is True
    assert len(outcome.checks) == 1


async def test_deterministic_step_failure_skips_quality_gates(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    verifier = Verifier()
    outcome = await verifier.verify(
        [_result("s1", status=StepStatus.FAILED, output=None)],
        categories=("coding",), workspace_path=str(tmp_path),
    )
    assert outcome.passed is False
    assert len(outcome.checks) == 1  # never got to the project-level gates
