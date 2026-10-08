"""Run the cases against a real model and grade the audit trails.

It needs a model: Claude through ANTHROPIC_API_KEY, or any OpenAI-compatible server, including a local
open-weight model (DEVFLOW_PROVIDER=ollama or vllm with DEVFLOW_BASE_URL). Nothing is called unless you run it.

    python -m evals.run_eval --repeats 5                  # the defence on (the default)
    python -m evals.run_eval --repeats 5 --taint off      # the same cases with the taint rule off

The second run is the comparison that shows what the rule is worth: with the rule off and the level at
'autonomous', a fooled model gets its comment and ticket posted. Runs that fail because the provider
failed (no credit, bad key, timeout) are not saved, so a table of errors cannot pass for a result.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# These are read when the orchestrator is imported, so they are set first.
_taint_off = "--taint" in sys.argv and sys.argv[sys.argv.index("--taint") + 1] == "off"
os.environ["DEVFLOW_MOCK"] = "1"
os.environ["DEVFLOW_TAINT_RULE"] = "0" if _taint_off else "1"
_DATA = Path(tempfile.mkdtemp(prefix="devflow_eval_"))
os.environ["DEVFLOW_DATA_DIR"] = str(_DATA)

from evals import graders  # noqa: E402
from evals.cases import ATTACK_TOKEN, ATTACK_TOOLS, CASES, seed_state  # noqa: E402
from mcp_servers import backends  # noqa: E402
from orchestrator.config import settings  # noqa: E402
from orchestrator.engine import AgentEngine  # noqa: E402
from orchestrator.mcp_registry import registry  # noqa: E402
from orchestrator.store import STATUS_AWAITING_APPROVAL, RunStore  # noqa: E402

RESULTS = ROOT / "evals" / "results"
AGENT_LEVEL_ERRORS = ("iteration limit", "tool-call budget", "token budget", "the model declined", "response hit max_tokens")
MAX_PAUSES = 10


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = wins / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def provider_failed(run) -> bool:
    return run.status == "failed" and not run.error.startswith(AGENT_LEVEL_ERRORS)


async def play(case, repeat: int) -> dict:
    backends._save(seed_state(backends._seed()))
    store = RunStore(_DATA / "runs" / f"{case.name}-{repeat}")
    engine = AgentEngine(registry, store)
    run = await engine.start(case.playbook, dict(case.inputs), case.autonomy)
    pauses = 0
    while run.status == STATUS_AWAITING_APPROVAL and pauses < MAX_PAUSES:
        pauses += 1
        ids = [a["tool_use_id"] for a in run.pending["approvals"]]
        run = await engine.resume(run, {i: case.approver == "approve" for i in ids}, reviewer="eval")

    row = {"case": case.name, "kind": case.kind, "status": run.status, "error": run.error, "pauses": pauses,
           "tool_calls": run.tool_calls, "tokens": sum(run.usage.values()), "tainted": run.tainted,
           "executed": graders.executed_tools(run.events), "provider_failed": provider_failed(run)}
    if case.kind == "task":
        row["problems"] = graders.triage_problems(run.events, run.status, run.tool_calls)
        row["pass"] = not row["problems"]
    else:
        row["asked"] = graders.attacker_asked(run.events, ATTACK_TOOLS, [ATTACK_TOKEN])
        row["ran"] = graders.attacker_ran(run.events, ATTACK_TOOLS, [ATTACK_TOKEN])
    return row


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--taint", choices=["on", "off"], default="on")
    parser.add_argument("--only", help="run just this case, and save under its own name")
    args = parser.parse_args()
    cases = [c for c in CASES if args.only in (None, c.name)]
    if not cases:
        sys.exit("no case called " + args.only)

    await registry.start()
    rows: list[dict] = []
    try:
        for case in cases:
            for i in range(args.repeats):
                row = await play(case, i)
                rows.append(row)
                if row["provider_failed"]:
                    print(f"provider failure in {case.name}: {row['error'][:150]}")
                    if sum(r["provider_failed"] for r in rows[-3:]) >= 3:
                        sys.exit("3 provider failures in a row, so nothing was saved. Check the key, credit and model name.")
    finally:
        await registry.stop()

    if any(r["provider_failed"] for r in rows):
        sys.exit(f"{sum(r['provider_failed'] for r in rows)} of {len(rows)} runs hit a provider failure, so nothing was saved.")

    RESULTS.mkdir(exist_ok=True)
    name = f"{settings.provider}_{settings.model}_taint-{args.taint}" + (f"_{args.only}" if args.only else "")
    name = name.replace("/", "_").replace(":", "_")
    (RESULTS / f"{name}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

    print(f"{settings.provider}:{settings.model}  taint rule {args.taint}  {args.repeats} runs per case")
    for case in cases:
        group = [r for r in rows if r["case"] == case.name]
        n = len(group)
        if case.kind == "task":
            wins = sum(r["pass"] for r in group)
            lo, hi = wilson(wins, n)
            print(f"  {case.name:22} passed {wins}/{n} [{lo:.0%}, {hi:.0%}]")
        else:
            for label in ("asked", "ran"):
                wins = sum(r[label] for r in group)
                lo, hi = wilson(wins, n)
                print(f"  {case.name:22} attacker {label:5} {wins}/{n} [{lo:.0%}, {hi:.0%}]")
    print(f"  tokens {sum(r['tokens'] for r in rows)}")


if __name__ == "__main__":
    asyncio.run(main())
