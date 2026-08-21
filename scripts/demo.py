"""Run a playbook from the terminal, with the approval gate prompting inline.

This is the same engine, policy and MCP layer the n8n workflows drive -- only
the human-in-the-loop transport differs (stdin here, a chat message there). Use
it to see the whole thing work before wiring up n8n.

    python scripts/demo.py issue_triage    --repo acme/checkout-service --number 41
    python scripts/demo.py implement_ticket --jira-key ENG-1 --repo acme/checkout-service
    python scripts/demo.py review_pr        --repo acme/checkout-service --number 100
    python scripts/demo.py document_change  --repo acme/checkout-service --number 100
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import playbooks  # noqa: E402
from orchestrator.config import settings  # noqa: E402
from orchestrator.engine import AgentEngine  # noqa: E402
from orchestrator.mcp_registry import registry  # noqa: E402
from orchestrator.store import STATUS_AWAITING_APPROVAL, RunStore  # noqa: E402

DIM = "\033[2m"
BOLD = "\033[1m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RED = "\033[31m"
OFF = "\033[0m"

TIER_COLOR = {"read": DIM, "write": "", "publish": YELLOW, "critical": RED}


def show_events(run, seen: int) -> int:
    for event in run.events[seen:]:
        kind = event["kind"]
        if kind == "tool_result":
            mark = GREEN + "ok " + OFF if event["ok"] else RED + "err" + OFF
            colour = TIER_COLOR.get(event["tier"], "")
            print("  {} {}{}{} {}{}{}".format(
                mark, colour, event["tool"], OFF, DIM, event["arguments"].replace("\n", " ")[:110], OFF
            ))
        elif kind == "tool_denied":
            print("  {}blocked{} {} -- {}".format(RED, OFF, event["tool"], event["reason"]))
        elif kind == "approval_decision":
            verdict = GREEN + "approved" + OFF if event["approved"] else RED + "rejected" + OFF
            print("  {} {} by {}".format(verdict, event["tool"], event["reviewer"]))
    return len(run.events)


def ask(run) -> dict[str, bool]:
    print("\n{}{}PAUSED -- {} action(s) need a human{}".format(
        BOLD, YELLOW, len(run.pending["approvals"]), OFF))
    if run.summary:
        print(DIM + run.summary + OFF)
    decisions = {}
    for approval in run.pending["approvals"]:
        print("\n  tool   : {}{}{}".format(BOLD, approval["tool"], OFF))
        print("  tier   : {}".format(approval["tier"]))
        print("  why    : {}".format(approval["reason"]))
        print("  args   : {}".format(approval["arguments"].replace("\n", "\n           ")))
        answer = input("  approve? [y/N] ").strip().lower()
        decisions[approval["tool_use_id"]] = answer in {"y", "yes"}
    return decisions


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("playbook", choices=sorted(playbooks.PLAYBOOKS))
    parser.add_argument("--repo", default="acme/checkout-service")
    parser.add_argument("--number", type=int)
    parser.add_argument("--jira-key")
    parser.add_argument("--jira-project", default="ENG")
    parser.add_argument("--branch")
    parser.add_argument("--docs-path")
    parser.add_argument("--autonomy", choices=["supervised", "semi", "autonomous"],
                        default=settings.autonomy)
    parser.add_argument("--yes", action="store_true",
                        help="approve every gated action without asking (demo only)")
    parser.add_argument("--json", action="store_true", help="dump the full run record")
    args = parser.parse_args()

    inputs = {
        k: v
        for k, v in {
            "repo": args.repo,
            "number": args.number,
            "jira_key": args.jira_key,
            "jira_project": args.jira_project,
            "branch": args.branch,
            "docs_path": args.docs_path,
        }.items()
        if v is not None
    }

    print("{}devflow{} playbook={} autonomy={} model={} mock={}".format(
        BOLD, OFF, args.playbook, args.autonomy, settings.model, settings.mock))

    await registry.start()
    engine = AgentEngine(registry, RunStore())
    try:
        run = await engine.start(args.playbook, inputs, args.autonomy)
        seen = show_events(run, 0)

        while run.status == STATUS_AWAITING_APPROVAL:
            if args.yes:
                decisions = {a["tool_use_id"]: True for a in run.pending["approvals"]}
                print("\n{}auto-approving {} action(s) (--yes){}".format(
                    YELLOW, len(decisions), OFF))
            else:
                decisions = ask(run)
            print()
            run = await engine.resume(run, decisions, reviewer="cli")
            seen = show_events(run, seen)
    finally:
        await registry.stop()

    colour = GREEN if run.status == "completed" else RED
    print("\n{}{}{}  {} iterations, {} tool calls, {} in / {} out tokens".format(
        colour, run.status.upper(), OFF, run.iterations, run.tool_calls,
        run.usage.get("input_tokens", 0), run.usage.get("output_tokens", 0)))
    print("\n" + (run.summary or run.error))
    if args.json:
        print("\n" + json.dumps(run.public(), indent=2, default=str))
    return 0 if run.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
