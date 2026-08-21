"""Both model backends, checked against the same MCP tool definitions.

The point of these tests is that the engine's contract holds identically for
Claude and for an open model behind an OpenAI-compatible server: same tool
surface in, same normalised Turn out.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.providers import (  # noqa: E402
    END_TURN,
    MAX_TOKENS,
    TOOL_USE,
    ToolResult,
    build_provider,
)
from orchestrator.providers.openai_compat import OpenAICompatProvider  # noqa: E402

MCP_TOOLS = [
    {
        "name": "gh_get_issue",
        "description": "Fetch a single issue.",
        "input_schema": {
            "type": "object",
            "properties": {"repo": {"type": "string"}, "number": {"type": "integer"}},
            "required": ["repo", "number"],
        },
    }
]


class FakeSettings:
    provider = "openai_compat"
    model = "qwen3:32b"
    base_url = "http://localhost:11434/v1"
    api_key = ""
    temperature = 0.0
    effort = "high"
    max_tokens = 4096


# --------------------------------------------------------------------------
# construction
# --------------------------------------------------------------------------

def test_build_provider_rejects_an_unknown_backend():
    class S(FakeSettings):
        provider = "llamafile-but-typoed"

    with pytest.raises(ValueError, match="unknown DEVFLOW_PROVIDER"):
        build_provider(S())


def test_shorthand_backends_get_a_default_base_url():
    class S(FakeSettings):
        provider = "ollama"
        base_url = ""

    assert build_provider(S()).base_url == "http://localhost:11434/v1"


def test_openai_compat_without_a_base_url_is_an_error():
    class S(FakeSettings):
        provider = "openai_compat"
        base_url = ""

    with pytest.raises(ValueError, match="DEVFLOW_BASE_URL"):
        build_provider(S())


# --------------------------------------------------------------------------
# tool dialect
# --------------------------------------------------------------------------

def test_openai_wraps_tools_in_a_function_envelope():
    provider = build_provider(FakeSettings())
    tool = provider.prepare_tools(MCP_TOOLS)[0]

    assert tool["type"] == "function"
    assert tool["function"]["name"] == "gh_get_issue"
    # JSON Schema passes through untouched -- that is why MCP schemas work on
    # both backends without a translation table.
    assert tool["function"]["parameters"] == MCP_TOOLS[0]["input_schema"]


def test_anthropic_uses_the_flat_input_schema_form():
    pytest.importorskip("anthropic")
    from orchestrator.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider("claude-opus-5", 4096, "high", api_key="test-key")
    tool = provider.prepare_tools(MCP_TOOLS)[0]

    assert tool["name"] == "gh_get_issue"
    assert tool["input_schema"] == MCP_TOOLS[0]["input_schema"]
    assert "function" not in tool


# --------------------------------------------------------------------------
# tool results
# --------------------------------------------------------------------------

def test_openai_returns_one_tool_message_per_result():
    provider = build_provider(FakeSettings())
    messages = provider.tool_result_messages(
        [ToolResult("call_1", "fine"), ToolResult("call_2", "nope", is_error=True)]
    )

    assert [m["role"] for m in messages] == ["tool", "tool"]
    assert messages[0]["tool_call_id"] == "call_1"
    # There is no is_error flag in this dialect, so it has to be in the text.
    assert messages[1]["content"].startswith("ERROR: ")


def test_anthropic_batches_results_into_one_user_message():
    pytest.importorskip("anthropic")
    from orchestrator.providers.anthropic_provider import AnthropicProvider

    provider = AnthropicProvider("claude-opus-5", 4096, "high", api_key="test-key")
    messages = provider.tool_result_messages(
        [ToolResult("t1", "fine"), ToolResult("t2", "nope", is_error=True)]
    )

    assert len(messages) == 1
    blocks = messages[0]["content"]
    assert [b["tool_use_id"] for b in blocks] == ["t1", "t2"]
    assert "is_error" not in blocks[0]
    assert blocks[1]["is_error"] is True


# --------------------------------------------------------------------------
# response normalisation (mock transport, no server needed)
# --------------------------------------------------------------------------

def _completion(message: dict, finish_reason: str = "stop") -> dict:
    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 22},
    }


@pytest.mark.asyncio
async def test_openai_parses_tool_calls_and_string_arguments(monkeypatch):
    body = _completion(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_abc",
                    "type": "function",
                    "function": {
                        "name": "gh_get_issue",
                        "arguments": json.dumps({"repo": "a/b", "number": 41}),
                    },
                }
            ],
        },
        finish_reason="tool_calls",
    )
    turn = await _run_against(monkeypatch, body)

    assert turn.stop_reason == TOOL_USE
    assert turn.tool_calls[0].name == "gh_get_issue"
    assert turn.tool_calls[0].arguments == {"repo": "a/b", "number": 41}
    assert turn.tool_calls[0].parse_error == ""
    assert turn.input_tokens == 11 and turn.output_tokens == 22
    # The assistant message must carry tool_calls verbatim or the next
    # request is rejected for having unanswered calls.
    assert turn.assistant_message["tool_calls"] == body["choices"][0]["message"]["tool_calls"]


@pytest.mark.asyncio
async def test_unparseable_arguments_become_a_parse_error_not_an_exception(monkeypatch):
    body = _completion(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_bad",
                    "function": {"name": "gh_get_issue", "arguments": "{repo: a/b,,}"},
                }
            ],
        },
        finish_reason="tool_calls",
    )
    turn = await _run_against(monkeypatch, body)

    assert turn.tool_calls[0].parse_error
    assert "not valid JSON" in turn.tool_calls[0].parse_error


@pytest.mark.asyncio
async def test_tool_calls_with_a_stop_finish_reason_are_still_tool_use(monkeypatch):
    """Several local runtimes report finish_reason 'stop' alongside tool calls."""
    body = _completion(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "c1", "function": {"name": "gh_get_issue", "arguments": "{}"}}
            ],
        },
        finish_reason="stop",
    )
    turn = await _run_against(monkeypatch, body)
    assert turn.stop_reason == TOOL_USE


@pytest.mark.asyncio
async def test_plain_text_answer_ends_the_turn(monkeypatch):
    body = _completion({"role": "assistant", "content": "The diff is clean."})
    turn = await _run_against(monkeypatch, body)

    assert turn.stop_reason == END_TURN
    assert turn.text == "The diff is clean."
    assert turn.tool_calls == []


@pytest.mark.asyncio
async def test_length_finish_reason_maps_to_max_tokens(monkeypatch):
    body = _completion({"role": "assistant", "content": "truncated..."}, "length")
    assert (await _run_against(monkeypatch, body)).stop_reason == MAX_TOKENS


@pytest.mark.asyncio
async def test_reasoning_content_is_preserved_in_history(monkeypatch):
    body = _completion(
        {"role": "assistant", "content": "done", "reasoning_content": "<think>..."}
    )
    turn = await _run_against(monkeypatch, body)
    assert turn.assistant_message["reasoning_content"] == "<think>..."


@pytest.mark.asyncio
async def test_http_error_surfaces_the_server_message(monkeypatch):
    with pytest.raises(RuntimeError, match="model not found"):
        await _run_against(
            monkeypatch, {"error": "model not found"}, status_code=404
        )


async def _run_against(monkeypatch, body: dict, status_code: int = 200):
    """Point the provider's httpx client at an in-memory transport."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=body)

    real_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(
        "orchestrator.providers.openai_compat.httpx.AsyncClient", factory
    )
    provider = OpenAICompatProvider("qwen3:32b", "http://fake/v1", 4096)
    return await provider.complete("system", [{"role": "user", "content": "hi"}], [])
