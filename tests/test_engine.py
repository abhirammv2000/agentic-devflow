"""Loop behaviour: suspension on a gated call, resumption, and rejection.

The model is replaced by a scripted sequence of responses and the MCP layer by
a recording stub, so these tests exercise the orchestration -- not the network.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.engine import AgentEngine  # noqa: E402
from orchestrator.store import (  # noqa: E402
    STATUS_AWAITING_APPROVAL,
    STATUS_COMPLETED,
    RunStore,
)


# --------------------------------------------------------------------------
# doubles
# --------------------------------------------------------------------------

@dataclass
class FakeBlock:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)

    def model_dump(self, **_kwargs):
        return {k: v for k, v in self.__dict__.items() if v not in ("", {})} | {
            "type": self.type
        }


@dataclass
class FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50


@dataclass
class FakeResponse:
    content: list[FakeBlock]
    stop_reason: str
    usage: FakeUsage = field(default_factory=FakeUsage)
    stop_details: Any = None


def text_turn(message: str) -> FakeResponse:
    return FakeResponse([FakeBlock("text", text=message)], "end_turn")


def tool_turn(*calls: tuple[str, str, dict]) -> FakeResponse:
    return FakeResponse(
        [FakeBlock("tool_use", id=i, name=n, input=a) for i, n, a in calls], "tool_use"
    )


class FakeRegistry:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict]] = []

    def tools_for(self, _allowed):
        return []

    async def call(self, name, arguments):
        self.executed.append((name, arguments))
        return '{"ok": true}', False


class ScriptedEngine(AgentEngine):
    def __init__(self, registry, store, script):
        super().__init__(registry, store, client=object())
        self.script = list(script)
        self.notifications: list[str] = []

    async def _call_model(self, run, book, tools):
        assert self.script, "the engine asked for more turns than the script provides"
        return self.script.pop(0)

    async def _notify(self, event, run):
        self.notifications.append(event)


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "runs")


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_read_only_run_completes_without_stopping(store):
    registry = FakeRegistry()
    engine = ScriptedEngine(
        registry,
        store,
        [
            tool_turn(("t1", "gh_get_pull_request", {"repo": "a/b", "number": 7})),
            text_turn("The diff is clean."),
        ],
    )

    run = await engine.start("review_pr", {"repo": "a/b", "number": 7}, "semi")

    assert run.status == STATUS_COMPLETED
    assert run.summary == "The diff is clean."
    assert registry.executed == [("gh_get_pull_request", {"repo": "a/b", "number": 7})]
    assert "run.completed" in engine.notifications


@pytest.mark.asyncio
async def test_publish_tier_suspends_the_run(store):
    registry = FakeRegistry()
    engine = ScriptedEngine(
        registry,
        store,
        [tool_turn(("t1", "gh_review_pull_request",
                    {"repo": "a/b", "number": 7, "event": "COMMENT", "body": "..."}))],
    )

    run = await engine.start("review_pr", {"repo": "a/b", "number": 7}, "semi")

    assert run.status == STATUS_AWAITING_APPROVAL
    assert registry.executed == [], "nothing may execute while approval is pending"
    assert [a["tool"] for a in run.pending["approvals"]] == ["gh_review_pull_request"]
    assert "run.approval_required" in engine.notifications


@pytest.mark.asyncio
async def test_approval_resumes_and_executes(store):
    registry = FakeRegistry()
    engine = ScriptedEngine(
        registry,
        store,
        [
            tool_turn(("t1", "gh_review_pull_request",
                       {"repo": "a/b", "number": 7, "event": "COMMENT", "body": "..."})),
            text_turn("Review posted."),
        ],
    )

    run = await engine.start("review_pr", {"repo": "a/b", "number": 7}, "semi")
    run = await engine.resume(run, {"t1": True}, reviewer="dana")

    assert run.status == STATUS_COMPLETED
    assert [name for name, _ in registry.executed] == ["gh_review_pull_request"]
    decisions = [e for e in run.events if e["kind"] == "approval_decision"]
    assert decisions[0]["approved"] is True
    assert decisions[0]["reviewer"] == "dana"


@pytest.mark.asyncio
async def test_rejection_is_reported_to_the_model_and_nothing_runs(store):
    registry = FakeRegistry()
    engine = ScriptedEngine(
        registry,
        store,
        [
            tool_turn(("t1", "gh_review_pull_request",
                       {"repo": "a/b", "number": 7, "event": "COMMENT", "body": "..."})),
            text_turn("Review was declined; stopping."),
        ],
    )

    run = await engine.start("review_pr", {"repo": "a/b", "number": 7}, "semi")
    run = await engine.resume(run, {"t1": False}, reviewer="dana", note="wrong PR")

    assert run.status == STATUS_COMPLETED
    assert registry.executed == []
    tool_results = run.messages[-2]["content"]
    assert tool_results[0]["is_error"] is True
    assert "declined" in tool_results[0]["content"]
    assert "wrong PR" in tool_results[0]["content"]


@pytest.mark.asyncio
async def test_unspecified_decision_counts_as_rejection(store):
    registry = FakeRegistry()
    engine = ScriptedEngine(
        registry,
        store,
        [
            tool_turn(("t1", "gh_review_pull_request",
                       {"repo": "a/b", "number": 7, "event": "COMMENT", "body": "..."})),
            text_turn("Stopped."),
        ],
    )

    run = await engine.start("review_pr", {"repo": "a/b", "number": 7}, "semi")
    run = await engine.resume(run, {})

    assert registry.executed == []


@pytest.mark.asyncio
async def test_mixed_turn_waits_for_the_whole_batch(store):
    """One gated call in a parallel batch parks the entire turn, so a partially
    applied turn can never reach the outside world."""
    registry = FakeRegistry()
    engine = ScriptedEngine(
        registry,
        store,
        [
            tool_turn(
                ("t1", "gh_get_issue", {"repo": "a/b", "number": 41}),
                ("t2", "jira_create_issue",
                 {"project": "ENG", "summary": "s", "description": "d"}),
            ),
            text_turn("Done."),
        ],
    )

    run = await engine.start(
        "issue_triage", {"repo": "a/b", "number": 41}, "semi"
    )
    assert run.status == STATUS_AWAITING_APPROVAL
    assert registry.executed == []

    run = await engine.resume(run, {"t2": True})
    assert [name for name, _ in registry.executed] == ["gh_get_issue", "jira_create_issue"]


@pytest.mark.asyncio
async def test_out_of_surface_tool_is_denied_without_asking_a_human(store):
    registry = FakeRegistry()
    engine = ScriptedEngine(
        registry,
        store,
        [
            tool_turn(("t1", "gh_merge_pull_request", {"repo": "a/b", "number": 7})),
            text_turn("I cannot merge from this playbook."),
        ],
    )

    run = await engine.start("review_pr", {"repo": "a/b", "number": 7}, "autonomous")

    assert run.status == STATUS_COMPLETED
    assert registry.executed == []
    assert any(e["kind"] == "tool_denied" for e in run.events)


@pytest.mark.asyncio
async def test_missing_required_input_is_rejected_early(store):
    engine = ScriptedEngine(FakeRegistry(), store, [])
    with pytest.raises(ValueError, match="jira_key"):
        await engine.start("implement_ticket", {"repo": "a/b"}, "semi")


@pytest.mark.asyncio
async def test_resume_on_a_run_that_is_not_paused_is_an_error(store):
    engine = ScriptedEngine(FakeRegistry(), store, [text_turn("done")])
    run = await engine.start("review_pr", {"repo": "a/b", "number": 7}, "semi")
    with pytest.raises(ValueError, match="not awaiting approval"):
        await engine.resume(run, {})


@pytest.mark.asyncio
async def test_runaway_loop_hits_the_iteration_cap(store, monkeypatch):
    """A model that never stops calling tools must be cut off, not run forever."""
    import dataclasses

    import orchestrator.engine as engine_module

    # Settings is frozen, so swap in a modified copy rather than mutating it.
    monkeypatch.setattr(
        engine_module,
        "settings",
        dataclasses.replace(engine_module.settings, max_iterations=4),
    )
    registry = FakeRegistry()
    engine = ScriptedEngine(
        registry,
        store,
        [tool_turn(("t%d" % i, "gh_get_issue", {"repo": "a/b", "number": 41}))
         for i in range(10)],
    )

    run = await engine.start("issue_triage", {"repo": "a/b", "number": 41}, "semi")

    assert run.status == "failed"
    assert "iteration limit" in run.error
    assert run.iterations == 4
    assert "run.failed" in engine.notifications
