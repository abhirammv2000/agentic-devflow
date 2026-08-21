"""The agent loop.

Manual rather than an SDK tool-runner on purpose: a run must be able to stop in
the middle of a turn, persist itself, and be resumed by a *different* HTTP
request once a human has approved the pending action. See store.py.

Turn structure:

    model proposes tool calls
        -> policy.evaluate() each one
        -> all auto?      execute them, feed results back, keep going
        -> any needs approval?  persist, notify n8n, return; resume later
        -> any denied?    feed back an error result and let the model adapt

Nothing here is vendor-specific. The model is reached through a Provider
(providers/base.py) and the tools through MCP, so swapping Claude for a
locally-served open-weights model changes configuration, not this file.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from . import playbooks, policy, providers
from .config import settings
from .mcp_registry import MCPRegistry
from .providers import Provider, ToolResult
from .store import (
    STATUS_AWAITING_APPROVAL,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_RUNNING,
    Run,
    RunStore,
)

log = logging.getLogger("devflow.engine")


class AgentEngine:
    def __init__(
        self,
        registry: MCPRegistry,
        store: RunStore,
        provider: Provider | None = None,
    ) -> None:
        self.registry = registry
        self.store = store
        # Injectable so tests can drive the loop without a model behind it.
        self.provider = provider or providers.build_provider(settings)

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
        run.provider = "{}:{}".format(self.provider.name, self.provider.model)
        run.messages = [self.provider.user_message(book.render(inputs))]
        run.log(
            "started",
            playbook=playbook_name,
            inputs=inputs,
            autonomy=run.autonomy,
            provider=run.provider,
        )
        self.store.save(run)
        return await self._loop(run)

    async def resume(
        self, run: Run, decisions: dict[str, bool], reviewer: str = "human", note: str = ""
    ) -> Run:
        """Apply a human's approve/reject decisions and continue the run.

        `decisions` maps tool call id -> approved. Anything left unspecified is
        treated as rejected: silence is not consent.
        """
        if run.status != STATUS_AWAITING_APPROVAL or not run.pending:
            raise ValueError("run {} is not awaiting approval".format(run.id))

        results: list[ToolResult] = []

        for call in run.pending["calls"]:
            if call["decision"] == policy.DECISION_DENIED:
                results.append(ToolResult(call["id"], call["policy_reason"], True))
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
                        ToolResult(
                            call["id"],
                            "A human reviewer declined this action{}. Do not retry it "
                            "and do not route around it.".format(
                                ": " + note if note else ""
                            ),
                            True,
                        )
                    )
                    continue

            results.append(await self._execute(run, call))

        run.messages.extend(self.provider.tool_result_messages(results))
        run.pending = None
        run.status = STATUS_RUNNING
        self.store.save(run)
        return await self._loop(run)

    # ------------------------------------------------------------------
    # loop
    # ------------------------------------------------------------------

    async def _loop(self, run: Run) -> Run:
        book = playbooks.get(run.playbook)
        tools = self.provider.prepare_tools(self.registry.tools_for(book.allowed_tools))

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
                turn = await self.provider.complete(book.system, run.messages, tools)
            except Exception as exc:
                return await self._fail(run, "{}: {}".format(type(exc).__name__, exc))

            run.add_usage(turn.input_tokens, turn.output_tokens)

            if turn.stop_reason == providers.REFUSAL:
                return await self._fail(
                    run, "the model declined this request ({})".format(turn.detail or "?")
                )

            if turn.stop_reason == providers.MAX_TOKENS:
                return await self._fail(
                    run, "response hit max_tokens; raise DEVFLOW_MAX_TOKENS"
                )

            if turn.stop_reason == "pause_turn":
                run.messages.append(turn.assistant_message)
                self.store.save(run)
                continue

            if turn.stop_reason != providers.TOOL_USE:
                run.summary = turn.text
                run.status = STATUS_COMPLETED
                run.messages.append(turn.assistant_message)
                run.log("completed", summary=run.summary)
                self.store.save(run)
                await self._notify("run.completed", run)
                return run

            run.messages.append(turn.assistant_message)

            calls = []
            for call in turn.tool_calls:
                decision = policy.evaluate(call.name, run.autonomy, book.allowed_tools)
                calls.append(
                    {
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                        "parse_error": call.parse_error,
                        "decision": decision.action,
                        "tier": decision.tier,
                        "policy_reason": decision.reason,
                    }
                )
                run.log(
                    "tool_proposed",
                    tool=call.name,
                    tier=decision.tier,
                    decision=decision.action,
                    reason=decision.reason,
                )

            # A malformed tool call is answered immediately: it never reaches a
            # human, because there is nothing coherent to approve. Weaker open
            # models emit unparseable arguments often enough to matter.
            if any(c["parse_error"] for c in calls):
                results = []
                for c in calls:
                    if c["parse_error"]:
                        run.log("tool_malformed", tool=c["name"], reason=c["parse_error"])
                        results.append(ToolResult(c["id"], c["parse_error"], True))
                    else:
                        results.append(
                            ToolResult(
                                c["id"],
                                "Not executed: another tool call in this turn was "
                                "malformed. Reissue the whole turn.",
                                True,
                            )
                        )
                run.messages.extend(self.provider.tool_result_messages(results))
                self.store.save(run)
                continue

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
                run.summary = turn.text or "Waiting for human approval."
                self.store.save(run)
                await self._notify("run.approval_required", run)
                return run

            results = []
            for call in calls:
                if call["decision"] == policy.DECISION_DENIED:
                    results.append(ToolResult(call["id"], call["policy_reason"], True))
                    run.log("tool_denied", tool=call["name"], reason=call["policy_reason"])
                else:
                    results.append(await self._execute(run, call))

            run.messages.extend(self.provider.tool_result_messages(results))
            self.store.save(run)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    async def _execute(self, run: Run, call: dict[str, Any]) -> ToolResult:
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
        return ToolResult(call["id"], text, is_error)

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
