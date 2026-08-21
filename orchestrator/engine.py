"""The agent loop.

Manual rather than SDK tool-runner on purpose: a run must be able to stop in
the middle of a turn, persist itself, and be resumed by a *different* HTTP
request once a human has approved the pending action. See store.py.

Turn structure:

    model proposes tool calls
        -> policy.evaluate() each one
        -> all auto?      execute them, feed results back, keep going
        -> any needs approval?  persist, notify n8n, return; resume later
        -> any denied?    feed back an error result and let the model adapt
"""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
import httpx

from . import playbooks, policy
from .config import settings
from .mcp_registry import MCPRegistry
from .store import (
    STATUS_AWAITING_APPROVAL,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    Run,
    RunStore,
)

log = logging.getLogger("devflow.engine")

# Route around safety-classifier refusals instead of failing the run.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AgentEngine:
    def __init__(
        self,
        registry: MCPRegistry,
        store: RunStore,
        client: anthropic.AsyncAnthropic | None = None,
    ) -> None:
        self.registry = registry
        self.store = store
        # Injectable so tests can drive the loop without hitting the API.
        self.client = client or anthropic.AsyncAnthropic()

    # ------------------------------------------------------------------
    # public entry points
    # ------------------------------------------------------------------

    async def start(
        self, playbook_name: str, inputs: dict[str, Any], autonomy: str | None = None
    ) -> Run:
        book = playbooks.get(playbook_name)
        missing = playbooks.validate_inputs(book, inputs)
        if missing:
            raise ValueError("missing required inputs: " + ", ".join(missing))

        run = self.store.create(playbook_name, inputs, autonomy or settings.autonomy)
        run.messages = [{"role": "user", "content": book.render(inputs)}]
        run.log("started", playbook=playbook_name, inputs=inputs, autonomy=run.autonomy)
        self.store.save(run)
        return await self._loop(run)

    async def resume(
        self, run: Run, decisions: dict[str, bool], reviewer: str = "human", note: str = ""
    ) -> Run:
        """Apply a human's approve/reject decisions and continue the run.

        `decisions` maps tool_use_id -> approved. Anything left unspecified is
        treated as rejected: silence is not consent.
        """
        if run.status != STATUS_AWAITING_APPROVAL or not run.pending:
            raise ValueError("run {} is not awaiting approval".format(run.id))

        calls = run.pending["calls"]
        results: list[dict[str, Any]] = []

        for call in calls:
            if call["decision"] == policy.DECISION_DENIED:
                results.append(self._error_result(call["id"], call["policy_reason"]))
                run.log("tool_denied", tool=call["name"], reason=call["policy_reason"])
                continue

            if call["decision"] == policy.DECISION_APPROVAL:
                approved = bool(decisions.get(call["id"], False))
                run.log(
                    "approval_decision",
                    tool=call["name"],
                    approved=approved,
                    reviewer=reviewer,
                    note=note,
                )
                if not approved:
                    results.append(
                        self._error_result(
                            call["id"],
                            "A human reviewer declined this action{}. Do not retry it "
                            "and do not route around it.".format(
                                ": " + note if note else ""
                            ),
                        )
                    )
                    continue

            results.append(await self._execute(run, call))

        run.messages.append({"role": "user", "content": results})
        run.pending = None
        run.status = STATUS_RUNNING
        self.store.save(run)
        return await self._loop(run)

    # ------------------------------------------------------------------
    # loop
    # ------------------------------------------------------------------

    async def _loop(self, run: Run) -> Run:
        book = playbooks.get(run.playbook)
        tools = self.registry.tools_for(book.allowed_tools)

        while True:
            if run.iterations >= settings.max_iterations:
                return await self._fail(
                    run, "iteration limit ({}) reached".format(settings.max_iterations)
                )
            if run.tool_calls >= settings.max_tool_calls:
                return await self._fail(
                    run, "tool-call budget ({}) exhausted".format(settings.max_tool_calls)
                )

            run.iterations += 1
            try:
                response = await self._call_model(run, book, tools)
            except Exception as exc:
                return await self._fail(run, "{}: {}".format(type(exc).__name__, exc))

            run.add_usage(response.usage.input_tokens, response.usage.output_tokens)
            content = [
                block.model_dump(mode="json", exclude_none=True)
                for block in response.content
            ]

            if response.stop_reason == "refusal":
                details = getattr(response, "stop_details", None)
                return await self._fail(
                    run,
                    "the model declined this request (category: {})".format(
                        getattr(details, "category", "unknown")
                    ),
                )

            if response.stop_reason == "max_tokens":
                return await self._fail(run, "response hit max_tokens; raise DEVFLOW_MAX_TOKENS")

            if response.stop_reason == "pause_turn":
                run.messages.append({"role": "assistant", "content": content})
                self.store.save(run)
                continue

            if response.stop_reason != "tool_use":
                run.summary = self._text_of(response)
                run.status = STATUS_COMPLETED
                run.messages.append({"role": "assistant", "content": content})
                run.log("completed", summary=run.summary)
                self.store.save(run)
                await self._notify("run.completed", run)
                return run

            run.messages.append({"role": "assistant", "content": content})

            calls = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                decision = policy.evaluate(block.name, run.autonomy, book.allowed_tools)
                calls.append(
                    {
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                        "decision": decision.action,
                        "tier": decision.tier,
                        "policy_reason": decision.reason,
                    }
                )
                run.log(
                    "tool_proposed",
                    tool=block.name,
                    tier=decision.tier,
                    decision=decision.action,
                    reason=decision.reason,
                )

            if any(c["decision"] == policy.DECISION_APPROVAL for c in calls):
                run.pending = {
                    "calls": calls,
                    "approvals": [
                        {
                            "tool_use_id": c["id"],
                            "tool": c["name"],
                            "tier": c["tier"],
                            "reason": c["policy_reason"],
                            "arguments": _preview(c["input"]),
                        }
                        for c in calls
                        if c["decision"] == policy.DECISION_APPROVAL
                    ],
                }
                run.status = STATUS_AWAITING_APPROVAL
                run.summary = self._text_of(response) or "Waiting for human approval."
                self.store.save(run)
                await self._notify("run.approval_required", run)
                return run

            results = []
            for call in calls:
                if call["decision"] == policy.DECISION_DENIED:
                    results.append(self._error_result(call["id"], call["policy_reason"]))
                    run.log("tool_denied", tool=call["name"], reason=call["policy_reason"])
                else:
                    results.append(await self._execute(run, call))

            run.messages.append({"role": "user", "content": results})
            self.store.save(run)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _call_model(self, run: Run, book: playbooks.Playbook, tools) -> Any:
        # Streaming keeps long tool-heavy turns under the HTTP timeout; the
        # cache breakpoint on the system block covers the (stable) tool list too.
        async with self.client.beta.messages.stream(
            model=settings.model,
            max_tokens=settings.max_tokens,
            system=[
                {
                    "type": "text",
                    "text": book.system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=run.messages,
            tools=tools,
            thinking={"type": "adaptive"},
            output_config={"effort": settings.effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            return await stream.get_final_message()

    async def _execute(self, run: Run, call: dict[str, Any]) -> dict[str, Any]:
        run.tool_calls += 1
        text, is_error = await self.registry.call(call["name"], call["input"])
        run.log(
            "tool_result",
            tool=call["name"],
            tier=call["tier"],
            approved=call["decision"] == policy.DECISION_APPROVAL,
            arguments=_preview(call["input"]),
            ok=not is_error,
            result=text[:1500],
        )
        self.store.save(run)
        return {
            "type": "tool_result",
            "tool_use_id": call["id"],
            "content": text,
            **({"is_error": True} if is_error else {}),
        }

    @staticmethod
    def _error_result(tool_use_id: str, message: str) -> dict[str, Any]:
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": message,
            "is_error": True,
        }

    @staticmethod
    def _text_of(response) -> str:
        return "\n".join(b.text for b in response.content if b.type == "text").strip()

    async def _fail(self, run: Run, message: str) -> Run:
        run.status = STATUS_FAILED
        run.error = message
        run.log("failed", error=message)
        self.store.save(run)
        await self._notify("run.failed", run)
        return run

    async def _notify(self, event: str, run: Run) -> None:
        """Best-effort callback into n8n. A dead webhook must not kill a run."""
        if not settings.approval_webhook:
            return
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    settings.approval_webhook,
                    json={"event": event, **run.public()},
                    headers={"X-Devflow-Token": settings.service_token},
                )
        except Exception as exc:
            log.warning("callback to n8n failed (%s): %s", event, exc)


def _preview(value: Any, limit: int = 600) -> str:
    """Compact argument rendering for approval cards and the audit log."""
    try:
        text = json.dumps(value, indent=2, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"
