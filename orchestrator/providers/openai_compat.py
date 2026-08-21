"""Open-model backend: any server speaking the OpenAI Chat Completions API.

Deliberately plain httpx rather than a vendor SDK, because "OpenAI-compatible"
is the lingua franca of open-weights serving and every runtime below exposes it:

    Ollama      http://localhost:11434/v1     (qwen3, llama3.3, mistral, ...)
    vLLM        http://localhost:8000/v1
    llama.cpp   http://localhost:8080/v1
    LM Studio   http://localhost:1234/v1
    OpenRouter  https://openrouter.ai/api/v1
    Together    https://api.together.xyz/v1
    Groq        https://api.groq.com/openai/v1

The dialect differences the engine would otherwise have to care about are all
absorbed here: tools are wrapped in a `function` envelope, arguments arrive as a
JSON *string* rather than an object, results go back as one `tool` message each
rather than a batch, and `finish_reason` uses a different vocabulary.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .base import (
    END_TURN,
    MAX_TOKENS,
    REFUSAL,
    TOOL_USE,
    ToolCall,
    ToolResult,
    Turn,
    json_schema_of,
)

log = logging.getLogger("devflow.provider.openai")

FINISH_REASONS = {
    "stop": END_TURN,
    "tool_calls": TOOL_USE,
    "function_call": TOOL_USE,
    "length": MAX_TOKENS,
    "content_filter": REFUSAL,
}


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(
        self,
        model: str,
        base_url: str,
        max_tokens: int,
        api_key: str = "",
        temperature: float = 0.0,
        timeout: float = 600.0,
    ) -> None:
        self.model = model
        # Many local servers are served at /v1 already; tolerate either form.
        self.base_url = base_url.rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        # Local runtimes ignore the key but some reject a missing header.
        self.api_key = api_key or "not-needed"
        self.timeout = timeout

    def prepare_tools(self, mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": json_schema_of(t),
                },
            }
            for t in mcp_tools
        ]

    def user_message(self, text: str) -> dict[str, Any]:
        return {"role": "user", "content": text}

    def tool_result_messages(self, results: list[ToolResult]) -> list[dict[str, Any]]:
        # One `tool` message per call, and every call in the assistant turn must
        # get one back or the next request 400s.
        return [
            {
                "role": "tool",
                "tool_call_id": r.call_id,
                "content": ("ERROR: " + r.content) if r.is_error else r.content,
            }
            for r in results
        ]

    async def complete(
        self, system: str, messages: list[dict[str, Any]], tools: Any
    ) -> Turn:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self.base_url + "/chat/completions",
                json=payload,
                headers={"Authorization": "Bearer " + self.api_key},
            )
            if resp.status_code >= 400:
                raise RuntimeError(
                    "{} returned {}: {}".format(
                        self.base_url, resp.status_code, resp.text[:500]
                    )
                )
            body = resp.json()

        choice = body["choices"][0]
        message = choice["message"]
        raw_calls = message.get("tool_calls") or []

        tool_calls = []
        for call in raw_calls:
            fn = call.get("function", {})
            arguments, parse_error = _parse_arguments(fn.get("arguments"))
            tool_calls.append(
                ToolCall(
                    id=call.get("id") or fn.get("name", "call"),
                    name=fn.get("name", ""),
                    arguments=arguments,
                    parse_error=parse_error,
                )
            )

        # Preserve the assistant message as the server produced it (including
        # any reasoning_content from R1-style models) so history stays valid.
        assistant: dict[str, Any] = {"role": "assistant", "content": message.get("content") or ""}
        for passthrough in ("tool_calls", "reasoning_content", "reasoning"):
            if message.get(passthrough):
                assistant[passthrough] = message[passthrough]

        finish = choice.get("finish_reason") or "stop"
        stop_reason = FINISH_REASONS.get(finish, END_TURN)
        # Some servers report "stop" even when they emitted tool calls.
        if tool_calls and stop_reason == END_TURN:
            stop_reason = TOOL_USE

        usage = body.get("usage") or {}
        return Turn(
            stop_reason=stop_reason,
            text=(message.get("content") or "").strip(),
            tool_calls=tool_calls,
            assistant_message=assistant,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            detail=finish,
        )


def _parse_arguments(raw: Any) -> tuple[dict[str, Any], str]:
    """Arguments arrive as a JSON string. Small models get this wrong often
    enough that a parse failure has to become a tool error the model can see,
    not an exception that kills the run."""
    if raw is None or raw == "":
        return {}, ""
    if isinstance(raw, dict):  # a few servers helpfully pre-parse it
        return raw, ""
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        return {}, "arguments were not valid JSON ({}): {}".format(exc, str(raw)[:300])
    if not isinstance(parsed, dict):
        return {}, "arguments must be a JSON object, got " + type(parsed).__name__
    return parsed, ""
