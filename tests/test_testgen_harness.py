"""The test-writing benchmark's grading, tested with a scripted model.

The point of grading by mutation is that tests which cannot fail should score nothing, so those cases are
scripted here and must come out at a kill rate of zero.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evals.testgen.run_one import run_attempt  # noqa: E402
from evals.testgen.suite import load_tasks, materialize  # noqa: E402
from scripted_model import ScriptedModel, calls, finish  # noqa: E402

ALL_TASK_IDS = [t.id for t in load_tasks()]


@pytest.fixture
def attempt(tmp_path, monkeypatch):
    async def run(task_id, model, variant="write_method"):
        task = load_tasks([task_id])[0]
        workspace = tmp_path / "workspace"
        materialize(task, workspace)
        monkeypatch.setenv("DEVFLOW_WORKSPACE", str(workspace))
        monkeypatch.setenv("DEVFLOW_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("DEVFLOW_MOCK", "1")
        return await run_attempt(task_id, variant, workspace, provider=model)

    return run


def write_tests(task_id, content):
    task = load_tasks([task_id])[0]
    return calls(("repo_write_file", {"path": f"tests/test_{task.module.stem}.py", "content": content}))


@pytest.mark.asyncio
@pytest.mark.parametrize("task_id", ALL_TASK_IDS)
async def test_the_reference_tests_score_a_perfect_kill_rate_through_the_harness(attempt, task_id):
    task = load_tasks([task_id])[0]
    model = ScriptedModel([write_tests(task_id, task.reference.read_text(encoding="utf-8")), finish("covered it")])

    result = await attempt(task_id, model)

    assert result["valid"] is True, result.get("pytest_output")
    assert result["kill_rate"] == 1.0
    assert result["survivors"] == []
    assert result["mutants"] == len(task.mutants)


@pytest.mark.asyncio
async def test_tests_that_cannot_fail_catch_nothing(attempt):
    model = ScriptedModel([write_tests("clamp", "from clamp import clamp\n\n\ndef test_it_runs():\n    clamp(1, 0, 2)\n    assert True\n"), finish("done")])

    result = await attempt("clamp", model)

    assert result["valid"] is True
    assert result["kill_rate"] == 0.0
    assert len(result["survivors"]) == result["mutants"]


@pytest.mark.asyncio
async def test_tests_that_fail_on_the_correct_module_are_invalid(attempt):
    model = ScriptedModel([write_tests("clamp", "from clamp import clamp\n\n\ndef test_wrong():\n    assert clamp(5, 0, 10) == 4\n"), finish("done")])

    result = await attempt("clamp", model)

    assert result["valid"] is False
    assert result["why_invalid"] == "tests fail on the original module"
    assert result["kill_rate"] == 0.0


@pytest.mark.asyncio
async def test_writing_no_tests_is_invalid(attempt):
    result = await attempt("clamp", ScriptedModel([finish("I tested it in my head.")]))

    assert result["valid"] is False
    assert result["why_invalid"] == "no test file"


@pytest.mark.asyncio
async def test_an_empty_test_file_is_invalid_not_a_pass(attempt):
    model = ScriptedModel([write_tests("clamp", "# nothing here\n"), finish("done")])

    result = await attempt("clamp", model)

    assert result["valid"] is False
    assert result["why_invalid"] == "no tests collected"


@pytest.mark.asyncio
async def test_editing_the_module_does_not_help_and_is_reported(attempt):
    """Tests that only pass because the module was changed are graded against the original module."""
    broken_module = "def clamp(value, low, high):\n    return 4\n"
    model = ScriptedModel([
        calls(("repo_write_file", {"path": "src/clamp.py", "content": broken_module})),
        write_tests("clamp", "from clamp import clamp\n\n\ndef test_wrong():\n    assert clamp(5, 0, 10) == 4\n"),
        finish("done"),
    ])

    result = await attempt("clamp", model)

    assert result["src_modified"] is True
    assert result["valid"] is False


@pytest.mark.asyncio
async def test_a_partial_suite_gets_a_partial_score(attempt):
    only_the_basics = (
        "from clamp import clamp\n\n\n"
        "def test_inside():\n    assert clamp(5, 0, 10) == 5\n\n\n"
        "def test_below():\n    assert clamp(-3, 0, 10) == 0\n"
    )
    model = ScriptedModel([write_tests("clamp", only_the_basics), finish("done")])

    result = await attempt("clamp", model)

    assert result["valid"] is True
    assert 0.0 < result["kill_rate"] < 1.0
    assert "equal_bounds_rejected" in result["survivors"]
    assert "no_validation" in result["survivors"]
