"""Claude backend, via the Anthropic Messages API."""

from __future__ import annotations

from typing import Any

import anthropic

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

# Route around safety-classifier refusals instead of failing the run.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

STOP_REASONS = {
    "end_turn": END_TURN,
    "tool_use": TOOL_USE,
    "max_tokens": MAX_TOKENS,
    "refusal": REFUSAL,
    "stop_sequence": END_TURN,
    "pause_turn": "pause_turn",
}


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        model: str,
        max_tokens: int,
        effort: str,
        api_key: str | None = None,
        base_url: str | None = None,
        client: Any = None,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        kwargs: dict[str, Any] = {}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self.client = client or anthropic.AsyncAnthropic(**kwargs)

    def prepare_tools(self, mcp_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": json_schema_of(t),
            }
            for t in mcp_tools
        ]

    def user_message(self, text: str) -> dict[str, Any]:
        return {"role": "user", "content": text}

    def tool_result_messages(self, results: list[ToolResult]) -> list[dict[str, Any]]:
        blocks = []
        for r in results:
            block: dict[str, Any] = {
                "type": "tool_result",
                "tool_use_id": r.call_id,
                "content": r.content,
            }
            if r.is_error:
                block["is_error"] = True
            blocks.append(block)
        return [{"role": "user", "content": blocks}]

    async def complete(
        self, system: str, messages: list[dict[str, Any]], tools: Any
    ) -> Turn:
        # Streaming keeps long tool-heavy turns under the HTTP timeout; the
        # cache breakpoint on the system block covers the (stable) tool list too.
        async with self.client.beta.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            response = await stream.get_final_message()

        # Thinking blocks carry signatures the API validates, so the assistant
        # message must round-trip through JSON byte-for-byte.
        content = [
            block.model_dump(mode="json", exclude_none=True) for block in response.content
        ]

        return Turn(
            stop_reason=STOP_REASONS.get(response.stop_reason, END_TURN),
            text="\n".join(b.text for b in response.content if b.type == "text").strip(),
            tool_calls=[
                ToolCall(id=b.id, name=b.name, arguments=b.input)
                for b in response.content
                if b.type == "tool_use"
            ],
            assistant_message={"role": "assistant", "content": content},
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            detail=str(getattr(getattr(response, "stop_details", None), "category", "")),
        )
