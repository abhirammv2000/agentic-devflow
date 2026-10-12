"""A model that replays a list of turns, for testing the benchmark harnesses without a real model."""

from __future__ import annotations

from orchestrator.providers import END_TURN, TOOL_USE, ToolCall, Turn


class ScriptedModel:
    """Replays a list of turns and remembers the first prompt it was given."""

    name = "scripted"
    model = "test"

    def __init__(self, turns):
        self.turns = list(turns)
        self.first_prompt = None

    def prepare_tools(self, mcp_tools):
        return mcp_tools

    def user_message(self, text):
        if self.first_prompt is None:
            self.first_prompt = text
        return {"role": "user", "content": text}

    def tool_result_messages(self, results):
        return [{"role": "user", "content": [{"type": "tool_result", "tool_use_id": r.call_id, "content": r.content} for r in results]}]

    async def complete(self, system, messages, tools):
        assert self.turns, "the engine asked for more turns than the script has"
        return self.turns.pop(0)


def calls(*items):
    return Turn(
        stop_reason=TOOL_USE,
        tool_calls=[ToolCall(id=f"c{i}", name=name, arguments=args) for i, (name, args) in enumerate(items)],
        assistant_message={"role": "assistant", "content": "(tools)"},
        input_tokens=100,
        output_tokens=20,
    )


def finish(text="done"):
    return Turn(stop_reason=END_TURN, text=text, assistant_message={"role": "assistant", "content": text}, input_tokens=100, output_tokens=10)
