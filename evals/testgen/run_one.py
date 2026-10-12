"""One test-writing attempt: one module, one agent set-up, one model. Runs in its own process, like codefix/run_one.py."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

os.environ["DEVFLOW_MOCK"] = "1"
os.environ["N8N_APPROVAL_WEBHOOK"] = ""

from evals.codefix.run_one import behaviour, provider_failed  # noqa: E402
from evals.testgen import bench_playbooks  # noqa: E402
from evals.testgen.suite import grade, load_tasks  # noqa: E402
from orchestrator.engine import AgentEngine  # noqa: E402
from orchestrator.mcp_registry import registry  # noqa: E402
from orchestrator.store import RunStore  # noqa: E402


async def run_attempt(task_id: str, variant: str, workspace: Path, provider=None) -> dict:
    task = load_tasks([task_id])[0]
    workspace = workspace.resolve()
    if Path(os.environ.get("DEVFLOW_WORKSPACE", "")).resolve() != workspace:
        raise RuntimeError("DEVFLOW_WORKSPACE must point at the workspace; the repo server reads it when it starts")

    bench_playbooks.register()
    store = RunStore(Path(os.environ["DEVFLOW_DATA_DIR"]) / "runs")
    engine = AgentEngine(registry, store, provider)
    await registry.start()
    started = time.perf_counter()
    try:
        run = await engine.start(variant, {"ticket": task.ticket}, "semi")
    finally:
        seconds = time.perf_counter() - started
        await registry.stop()

    return {
        "task": task.id,
        "variant": variant,
        "model": f"{engine.provider.name}:{engine.provider.model}",
        "status": run.status,
        "error": run.error,
        "provider_failed": provider_failed(run),
        "seconds": round(seconds, 1),
        "iterations": run.iterations,
        "tool_calls": run.tool_calls,
        "input_tokens": run.usage.get("input_tokens", 0),
        "output_tokens": run.usage.get("output_tokens", 0),
        "summary": run.summary[:600],
        **behaviour(run.events),
        **grade(task, workspace),
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--variant", required=True, choices=bench_playbooks.VARIANTS)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = await run_attempt(args.task, args.variant, args.workspace)
    args.out.write_text(json.dumps(result, indent=1), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
