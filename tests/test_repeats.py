"""A model that repeats a call that already worked. A small local model did this in the first eval:
it labelled the same issue five times and never got to the comment. No model and no network here."""

from __future__ import annotations

import dataclasses
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-placeholder-for-tests")

from orchestrator import engine as engine_module  # noqa: E402
from orchestrator.engine import REPEAT_MESSAGE, call_key  # noqa: E402
from orchestrator.store import STATUS_COMPLETED, STATUS_FAILED, RunStore  # noqa: E402
from test_engine import FakeRegistry, ScriptedEngine, text_turn, tool_turn  # noqa: E402

LABELS = ("gh_set_labels", {"repo": "a/b", "number": 1, "labels": ["bug"]})
ISSUE = ("gh_get_issue", {"repo": "a/b", "number": 1})
COMMENT = ("gh_comment_issue", {"repo": "a/b", "number": 1, "body": "triaged"})
INPUTS = {"repo": "a/b", "number": 1, "jira_project": "ENG"}


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "runs")


def test_the_call_key_ignores_key_order_and_tells_arguments_apart():
    assert call_key("t", {"a": 1, "b": 2}) == call_key("t", {"b": 2, "a": 1})
    assert call_key("t", {"a": 1}) != call_key("t", {"a": 2})
    assert call_key("t", {"a": 1}) != call_key("u", {"a": 1})


@pytest.mark.asyncio
async def test_a_repeated_call_is_not_run_again_and_the_model_is_told(store):
    registry = FakeRegistry()
    engine = ScriptedEngine(registry, store, [tool_turn(("t1", *LABELS)), tool_turn(("t2", *LABELS)), text_turn("done")])

    run = await engine.start("issue_triage", INPUTS, "semi")

    assert [n for n, _ in registry.executed] == ["gh_set_labels"]
    assert run.status == STATUS_COMPLETED and run.repeated_calls == 1
    refused = run.messages[-2]["content"][0]
    assert refused["content"] == REPEAT_MESSAGE and refused["is_error"] is True
    assert any(e["kind"] == "tool_repeated" and e["tool"] == "gh_set_labels" for e in run.events)


@pytest.mark.asyncio
async def test_a_repeat_with_other_arguments_runs_normally(store):
    registry = FakeRegistry()
    other = ("gh_set_labels", {"repo": "a/b", "number": 1, "labels": ["bug", "sev2"]})
    engine = ScriptedEngine(registry, store, [tool_turn(("t1", *LABELS)), tool_turn(("t2", *other)), text_turn("done")])

    run = await engine.start("issue_triage", INPUTS, "semi")

    assert len(registry.executed) == 2 and run.repeated_calls == 0


@pytest.mark.asyncio
async def test_a_repeated_comment_is_never_posted_twice_even_when_a_human_would_approve(store):
    registry = FakeRegistry()
    engine = ScriptedEngine(registry, store, [
        tool_turn(("t1", *COMMENT)), tool_turn(("t2", *COMMENT)), text_turn("done"),
    ])
    run = await engine.start("issue_triage", INPUTS, "semi")
    run = await engine.resume(run, {"t1": True})

    # the second comment is refused before it reaches the approval step, so the run does not pause again
    assert run.status == STATUS_COMPLETED
    assert [n for n, _ in registry.executed] == ["gh_comment_issue"]


@pytest.mark.asyncio
async def test_reading_the_same_thing_again_after_a_change_is_allowed(store):
    registry = FakeRegistry()
    engine = ScriptedEngine(registry, store, [
        tool_turn(("t1", *ISSUE)), tool_turn(("t2", *LABELS)), tool_turn(("t3", *ISSUE)), text_turn("done"),
    ])

    run = await engine.start("issue_triage", INPUTS, "semi")

    assert [n for n, _ in registry.executed] == ["gh_get_issue", "gh_set_labels", "gh_get_issue"]
    assert run.repeated_calls == 0


@pytest.mark.asyncio
async def test_reading_the_same_thing_twice_with_nothing_changed_is_a_repeat(store):
    registry = FakeRegistry()
    engine = ScriptedEngine(registry, store, [tool_turn(("t1", *ISSUE)), tool_turn(("t2", *ISSUE)), text_turn("done")])

    run = await engine.start("issue_triage", INPUTS, "semi")

    assert len(registry.executed) == 1 and run.repeated_calls == 1


@pytest.mark.asyncio
async def test_a_failed_call_may_be_retried(store):
    class FlakyRegistry(FakeRegistry):
        async def call(self, name, arguments):
            self.executed.append((name, arguments))
            return ("boom", True) if len(self.executed) == 1 else ('{"ok": true}', False)

    registry = FlakyRegistry()
    engine = ScriptedEngine(registry, store, [tool_turn(("t1", *LABELS)), tool_turn(("t2", *LABELS)), text_turn("done")])

    run = await engine.start("issue_triage", INPUTS, "semi")

    assert len(registry.executed) == 2 and run.repeated_calls == 0


@pytest.mark.asyncio
async def test_a_model_that_keeps_repeating_is_stopped(store, monkeypatch):
    monkeypatch.setattr(engine_module, "settings", dataclasses.replace(engine_module.settings, max_repeated_calls=3))
    registry = FakeRegistry()
    script = [tool_turn((f"t{i}", *LABELS)) for i in range(10)]
    engine = ScriptedEngine(registry, store, script)

    run = await engine.start("issue_triage", INPUTS, "semi")

    assert run.status == STATUS_FAILED and "kept repeating" in run.error
    assert len(registry.executed) == 1 and run.repeated_calls == 3
    assert run.iterations == 4  # one real call, then three refused


@pytest.mark.asyncio
async def test_what_the_run_has_done_survives_a_pause_for_approval(store):
    registry = FakeRegistry()
    engine = ScriptedEngine(registry, store, [
        tool_turn(("t1", *LABELS)), tool_turn(("t2", *COMMENT)), tool_turn(("t3", *LABELS)), text_turn("done"),
    ])
    run = await engine.start("issue_triage", INPUTS, "semi")  # labels run, the comment waits

    assert store.load(run.id).seen_calls  # saved to disk
    run = await engine.resume(store.load(run.id), {"t2": True})

    assert [n for n, _ in registry.executed] == ["gh_set_labels", "gh_comment_issue"]  # the repeat was refused
    assert run.repeated_calls == 1
