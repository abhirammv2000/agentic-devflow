"""Launches the MCP servers over stdio and presents their tools as one flat
tool surface for the Claude Messages API.

MCP is what makes the tool layer swappable: the orchestrator never imports the
GitHub or Jira code, it only knows "there are servers, they advertise tools".
Point `settings.mcp_servers` at a vendor's MCP server instead and nothing in the
engine changes.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import settings

log = logging.getLogger("devflow.mcp")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class MCPRegistry:
    """Owns one long-lived stdio session per MCP server."""

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._sessions: dict[str, ClientSession] = {}
        self._tools: list[dict[str, Any]] = []
        self._owner: dict[str, str] = {}   # tool name -> server name

    async def start(self) -> None:
        if self._stack is not None:
            return
        self._stack = AsyncExitStack()
        env = dict(os.environ)
        env.setdefault("PYTHONPATH", str(PROJECT_ROOT))
        env.setdefault("PYTHONUNBUFFERED", "1")

        for name, args in settings.mcp_servers.items():
            params = StdioServerParameters(
                command=sys.executable, args=list(args), env=env, cwd=str(PROJECT_ROOT)
            )
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._sessions[name] = session

            listing = await session.list_tools()
            for tool in listing.tools:
                if tool.name in self._owner:
                    raise RuntimeError(
                        "tool name collision: '{}' served by both {} and {}".format(
                            tool.name, self._owner[tool.name], name
                        )
                    )
                self._owner[tool.name] = name
                self._tools.append(
                    {
                        "name": tool.name,
                        "description": (tool.description or "").strip(),
                        "input_schema": _schema_of(tool),
                    }
                )
            log.info("mcp server '%s' ready with %d tools", name, len(listing.tools))

    async def stop(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._sessions.clear()
        self._tools.clear()
        self._owner.clear()

    @property
    def tools(self) -> list[dict[str, Any]]:
        """Anthropic tool definitions, in a stable order so the prompt cache holds."""
        return sorted(self._tools, key=lambda t: t["name"])

    def tools_for(self, allowed: list[str] | None) -> list[dict[str, Any]]:
        if allowed is None:
            return self.tools
        allowed_set = set(allowed)
        return [t for t in self.tools if t["name"] in allowed_set]

    def knows(self, tool_name: str) -> bool:
        return tool_name in self._owner

    async def call(self, tool_name: str, arguments: dict[str, Any]) -> tuple[str, bool]:
        """Invoke an MCP tool. Returns (text_result, is_error)."""
        server = self._owner.get(tool_name)
        if server is None:
            return "No MCP server provides a tool named '{}'.".format(tool_name), True
        try:
            result = await self._sessions[server].call_tool(tool_name, arguments)
        except Exception as exc:  # transport / server crash
            log.exception("mcp call failed: %s", tool_name)
            return "Tool transport error: {}: {}".format(type(exc).__name__, exc), True

        parts = []
        for block in result.content:
            text = getattr(block, "text", None)
            parts.append(text if text is not None else str(block))
        return "\n".join(parts) or "(no output)", _is_error(result)


registry = MCPRegistry()


def _schema_of(tool) -> dict[str, Any]:
    """`input_schema` in the MCP 2.x SDK, `inputSchema` in 1.x."""
    return getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {
        "type": "object", "properties": {}
    }


def _is_error(result) -> bool:
    flag = getattr(result, "is_error", None)
    return bool(getattr(result, "isError", False) if flag is None else flag)
