"""The boundary between the agent loop and whatever model is behind it.

The engine never imports a vendor SDK. It gives a provider a system prompt, a message
history it treats as opaque, and the MCP tool list, and gets back a normalised Turn.
Anything specific to a provider lives behind this interface: the tool schema format, how an
assistant turn is stored, how a tool result is sent back, and what the stop reasons are
called.

Histories stay in each provider's own format. The engine treats them as plain JSON, which
is what lets a run be saved to disk mid-turn and resumed later (see store.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# Normalised stop reasons. Every provider maps its own vocabulary onto these.
END_TURN = "end_turn"
TOOL_USE = "tool_use"
MAX_TOKENS = "max_tokens"
REFUSAL = "refusal"


@dataclass
class ToolCall:
    """One tool invocation the model asked for."""

    id: str
    name: str
    arguments: dict[str, Any]
    # Set when the model emitted arguments that would not parse; the engine
    # turns this into an error result instead of calling the tool.
    parse_error: str = ""


@dataclass
class ToolResult:
    call_id: str
    content: str
    is_error: bool = False


@dataclass
class Turn:
    stop_reason: str
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # The assistant message to append to history, in the provider's own format.
    assistant_message: dict[str, Any] = field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    detail: str = ""


@runtime_checkable
class Provider(Protocol):
    """What the engine needs from a model backend."""

    name: str
    model: str

    def prepare_tools(self, mcp_tools: list[dict[str, Any]]) -> Any:
        """Translate MCP tool definitions into this provider's tool dialect."""

    def user_message(self, text: str) -> dict[str, Any]:
        """The opening message of a run."""

    def tool_result_messages(self, results: list[ToolResult]) -> list[dict[str, Any]]:
        """Feed tool results back. Anthropic wants one user message carrying all
        of them; OpenAI-compatible APIs want one `tool` message each."""

    async def complete(
        self, system: str, messages: list[dict[str, Any]], tools: Any
    ) -> Turn:
        """One model call."""


def json_schema_of(mcp_tool: dict[str, Any]) -> dict[str, Any]:
    """MCP advertises plain JSON Schema, which both dialects accept as-is."""
    schema = mcp_tool.get("input_schema") or {"type": "object", "properties": {}}
    # Some local runtimes reject a schema without an explicit `type`.
    schema.setdefault("type", "object")
    return schema
