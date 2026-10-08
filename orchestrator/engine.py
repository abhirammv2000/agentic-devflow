"""The agent loop.

It is written by hand instead of using an SDK tool runner because a run has to be able to
stop in the middle of a turn, save itself, and be resumed by a different HTTP request once
a human approves. See store.py.

Each turn goes like this:

    model proposes tool calls
        -> policy.evaluate() on each one
        -> all auto: run them, feed the results back, continue
        -> any needs approval: save, notify n8n, return, resume later
        -> any denied: feed back an error and let the model adjust

Nothing in here is specific to one vendor. The model is reached through a Provider
(providers/base.py) and the tools through MCP, so swapping Claude for a local open-weight
model is a config change.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from . import guard, playbooks, policy, providers, telemetry
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

# Decided in the engine, not the policy: the call is not risky, it is a repeat.
DECISION_REPEAT = "repeat"
REPEAT_MESSAGE = (
    "You already made this exact call and it worked. Do not make it again. "
    "Continue with the next step, or finish and report."
)


def call_key(name: str, arguments: Any) -> str:
    """The identity of a call: the tool and its arguments, with key order and spacing ignored."""
    return name + "\x00" + json.dumps(arguments, sort_keys=True, default=str)


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

    # public entry points

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
            if call["decision"] == DECISION_REPEAT:
                results.append(self._refuse_repeat(run, call))
                continue

            if call["decision"] == policy.DECISION_DENIED:
                results.append(ToolResult(call["id"], call["policy_reason"], True))
                run.log("tool_denied", tool=call["name"], reason=call["policy_reason"])
                continue

            if call["decision"] == policy.DECISION_APPROVAL:
                approved = bool(decisions.get(call["id"], False))
                telemetry.APPROVALS.labels("approved" if approved else "rejected").inc()
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

    # loop

    async def _loop(self, run: Run) -> Run:
        """One stretch of a run: from start or resume until it completes, fails or waits for a human."""
        started = time.monotonic()
        tokens_before = sum(run.usage.values())
        with telemetry.span("devflow.run", **{"devflow.playbook": run.playbook, "devflow.autonomy": run.autonomy}) as span:
            run = await self._turns(run)
            span.set_attribute("devflow.status", run.status)
            span.set_attribute("devflow.iterations", run.iterations)
            span.set_attribute("devflow.tool_calls", run.tool_calls)
            span.set_attribute("devflow.tokens", sum(run.usage.values()) - tokens_before)
            span.set_attribute("devflow.tainted", run.tainted)
        telemetry.RUNS.labels(run.playbook, run.status).inc()
        telemetry.RUN_SECONDS.labels(run.playbook).observe(time.monotonic() - started)
        return run

    async def _turns(self, run: Run) -> Run:
        book = playbooks.get(run.playbook)
        system = book.system + guard.UNTRUSTED_RULES
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

            if sum(run.usage.values()) >= settings.max_run_tokens:
                return await self._fail(
                    run, "token budget ({}) exhausted".format(settings.max_run_tokens)
                )

            run.iterations += 1
            try:
                with telemetry.span("devflow.llm_turn") as turn_span:
                    turn = await self.provider.complete(system, run.messages, tools)
                    turn_span.set_attribute("llm.input_tokens", turn.input_tokens)
                    turn_span.set_attribute("llm.output_tokens", turn.output_tokens)
            except Exception as exc:
                return await self._fail(run, "{}: {}".format(type(exc).__name__, exc))

            run.add_usage(turn.input_tokens, turn.output_tokens)
            telemetry.TOKENS.labels("input").inc(turn.input_tokens)
            telemetry.TOKENS.labels("output").inc(turn.output_tokens)

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

            # Calls in one turn run in order, so a read later in the turn counts too: a publish proposed
            # alongside it would otherwise be judged before the outside text arrives.
            tainted = settings.taint_rule and (
                run.tainted or any(policy.reads_outside_text(c.name) for c in turn.tool_calls)
            )
            calls = []
            for call in turn.tool_calls:
                if call_key(call.name, call.arguments) in run.seen_calls and not call.parse_error:
                    calls.append({"id": call.id, "name": call.name, "input": call.arguments, "parse_error": "",
                                  "decision": DECISION_REPEAT, "tier": policy.tier_of(call.name),
                                  "policy_reason": "repeat of a call that already worked"})
                    continue
                decision = policy.evaluate(call.name, run.autonomy, book.allowed_tools, tainted=tainted)
                telemetry.TOOL_DECISIONS.labels(call.name, decision.tier, decision.action).inc()
                if tainted and decision.action == policy.DECISION_APPROVAL and "read text from outside" in decision.reason:
                    telemetry.TAINT_ESCALATIONS.inc()
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
                    arguments=_preview(call.arguments),
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
                if call["decision"] == DECISION_REPEAT:
                    results.append(self._refuse_repeat(run, call))
                elif call["decision"] == policy.DECISION_DENIED:
                    results.append(ToolResult(call["id"], call["policy_reason"], True))
                    run.log("tool_denied", tool=call["name"], reason=call["policy_reason"])
                else:
                    results.append(await self._execute(run, call))

            run.messages.extend(self.provider.tool_result_messages(results))
            self.store.save(run)
            if run.repeated_calls >= settings.max_repeated_calls:
                return await self._fail(
                    run, "the model kept repeating calls that already worked ({} refused)".format(run.repeated_calls)
                )

    # helpers

    def _refuse_repeat(self, run: Run, call: dict[str, Any]) -> ToolResult:
        run.repeated_calls += 1
        telemetry.REPEATED_CALLS.labels(call["name"]).inc()
        run.log("tool_repeated", tool=call["name"], arguments=_preview(call["input"]))
        return ToolResult(call["id"], REPEAT_MESSAGE, True)

    async def _execute(self, run: Run, call: dict[str, Any]) -> ToolResult:
        run.tool_calls += 1
        with telemetry.span("devflow.tool", **{"devflow.tool": call["name"], "devflow.tier": call["tier"]}) as tool_span:
            text, is_error = await self.registry.call(call["name"], call["input"])
            tool_span.set_attribute("devflow.ok", not is_error)
        telemetry.TOOL_RESULTS.labels(call["name"], str(not is_error).lower()).inc()
        if not is_error:
            if not policy.reads_outside_text(call["name"]):
                # something changed, so reading the same thing again is legitimate (a file after an edit,
                # the tests after a fix). Writes and publishes stay remembered, because doing one twice is the harm.
                run.seen_calls = [k for k in run.seen_calls if not policy.reads_outside_text(k.split("\x00")[0])]
            run.seen_calls.append(call_key(call["name"], call["input"]))
        run.log(
            "tool_result",
            tool=call["name"],
            tier=call["tier"],
            approved=call["decision"] == policy.DECISION_APPROVAL,
            arguments=_preview(call["input"]),
            ok=not is_error,
            result=text[:1500],
        )
        if policy.reads_outside_text(call["name"]):
            run.tainted = True
            text = guard.wrap_untrusted(call["name"], text)
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
