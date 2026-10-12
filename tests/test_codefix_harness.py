"""The code-fix benchmark's own machinery, tested with a scripted model so no real model is needed.

What this protects is the grading. A benchmark that can be passed by editing the tests, or by hard-coding the
example in the ticket, measures nothing, so those two cheats are scripted here and must be graded as failures.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from evals.codefix.run_one import run_attempt  # noqa: E402
from evals.codefix.suite import load_tasks, materialize  # noqa: E402
from scripted_model import ScriptedModel, calls, finish  # noqa: E402

ALL_TASK_IDS = [t.id for t in load_tasks()]


@pytest.fixture
def attempt(tmp_path, monkeypatch):
    """Returns a function that runs one scripted attempt on a task and gives back its result."""

    async def run(task_id, model, variant="fix_tdd"):
        task = load_tasks([task_id])[0]
        workspace = tmp_path / "workspace"
        materialize(task, workspace)
        monkeypatch.setenv("DEVFLOW_WORKSPACE", str(workspace))
        monkeypatch.setenv("DEVFLOW_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("DEVFLOW_MOCK", "1")
        return await run_attempt(task_id, variant, workspace, provider=model)

    return run


def solution_source(task_id):
    task = load_tasks([task_id])[0]
    path = next((task.solution / "src").glob("*.py"))
    return "src/" + path.name, path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_a_real_fix_is_graded_as_solved(attempt):
    path, source = solution_source("slugify")
    model = ScriptedModel([
        calls(("repo_list_files", {}), ("repo_read_file", {"path": path})),
        calls(("repo_run_tests", {})),
        calls(("repo_write_file", {"path": path, "content": source})),
        calls(("repo_run_tests", {})),
        finish("The pattern matched one character at a time. It now matches runs, and the ends are stripped."),
    ])

    result = await attempt("slugify", model)

    assert result["solved"] is True
    assert result["status"] == "completed"
    assert result["src_files_changed"] == ["src/slugify.py"]
    assert result["tests_modified"] == []
    assert result["tested_before_editing"] and result["tested_after_editing"]
    assert result["tool_calls"] == 5
    assert result["input_tokens"] == 500 and result["output_tokens"] == 90


@pytest.mark.asyncio
async def test_editing_the_failing_test_does_not_count_as_a_fix(attempt):
    """The cheat the hidden tests exist for: make the red visible test green by weakening it."""
    model = ScriptedModel([
        calls(("repo_write_file", {"path": "tests/test_slugify.py", "content": "def test_nothing():\n    assert True\n"})),
        calls(("repo_run_tests", {})),
        finish("All tests pass."),
    ])

    result = await attempt("slugify", model)

    assert result["solved"] is False
    assert result["tests_modified"] == ["tests/test_slugify.py"]
    assert result["src_files_changed"] == []


@pytest.mark.asyncio
async def test_hard_coding_the_example_from_the_ticket_does_not_count(attempt):
    cheat = (
        "def slugify(text):\n"
        "    if text == '  Hello,   World!  ':\n"
        "        return 'hello-world'\n"
        "    return text.lower().replace(' ', '-')\n"
    )
    model = ScriptedModel([
        calls(("repo_write_file", {"path": "src/slugify.py", "content": cheat})),
        calls(("repo_run_tests", {})),
        finish("Fixed."),
    ])

    result = await attempt("slugify", model)

    assert result["solved"] is False
    assert "test_symbols_between_words_collapse" in result["hidden_output"]


@pytest.mark.asyncio
async def test_doing_nothing_fails(attempt):
    result = await attempt("pagination", ScriptedModel([finish("I could not find a bug.")]))

    assert result["solved"] is False
    assert result["status"] == "completed"
    assert result["src_files_changed"] == []


@pytest.mark.asyncio
async def test_the_agent_cannot_read_outside_its_working_copy_or_run_a_shell(attempt):
    model = ScriptedModel([
        calls(
            ("repo_read_file", {"path": "../../../etc/passwd"}),
            ("repo_run_tests", {"command": "rm -rf /"}),
            ("repo_read_file", {"path": "../hidden/test_hidden.py"}),
        ),
        finish("done"),
    ])

    result = await attempt("retry", model)

    assert result["failed_calls"] == 3
    assert result["solved"] is False


@pytest.mark.asyncio
async def test_the_context_variant_puts_the_first_test_run_in_the_prompt(attempt):
    model = ScriptedModel([finish("no change")])

    await attempt("leap_years", model, variant="fix_context")

    assert "1900" in model.first_prompt
    assert "src/calendar_utils.py" in model.first_prompt
    assert "failed" in model.first_prompt.lower()


@pytest.mark.asyncio
async def test_the_plain_variant_gives_only_the_ticket(attempt):
    model = ScriptedModel([finish("no change")])

    await attempt("leap_years", model, variant="fix_plain")

    assert "1900" in model.first_prompt
    assert "Context gathered" not in model.first_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("task_id", ALL_TASK_IDS)
async def test_every_task_is_solved_by_its_reference_solution_through_the_harness(attempt, task_id):
    path, source = solution_source(task_id)
    model = ScriptedModel([calls(("repo_write_file", {"path": path, "content": source})), finish("fixed")])

    result = await attempt(task_id, model)

    assert result["solved"] is True, result["hidden_output"]
