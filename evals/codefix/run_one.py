"""One attempt: one task, one agent set-up, one model. Runs in its own process.

A fresh process matters because the repo MCP server reads its workspace from the environment when it starts, so
each attempt needs its own server pointed at its own copy of the task. run.py sets that up and starts this.

    python -m evals.codefix.run_one --task slugify --variant fix_tdd --workspace /tmp/w --out /tmp/result.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Read when the orchestrator is imported, so they are set before it is.
os.environ["DEVFLOW_MOCK"] = "1"
os.environ["N8N_APPROVAL_WEBHOOK"] = ""  # nothing to notify during a benchmark

from evals import graders  # noqa: E402
from evals.codefix import bench_playbooks  # noqa: E402
from evals.codefix.suite import changed_files, grade, load_tasks, run_pytest  # noqa: E402
from orchestrator.engine import AgentEngine  # noqa: E402
from orchestrator.mcp_registry import registry  # noqa: E402
from orchestrator.store import RunStore  # noqa: E402

AGENT_LEVEL_ERRORS = ("iteration limit", "tool-call budget", "token budget", "the model declined", "response hit max_tokens")


def provider_failed(run) -> bool:
    """The model never answered (no credit, a bad key, a timeout), as opposed to the agent giving up."""
    return run.status == "failed" and not run.error.startswith(AGENT_LEVEL_ERRORS)


def path_of(event: dict) -> str | None:
    """The path argument of a logged call. The log keeps arguments as text that may be cut short, so it is read with a pattern."""
    match = re.search(r'"path":\s*"([^"]+)"', str(event.get("arguments", "")))
    return match.group(1) if match else None


def call_failed(event: dict) -> bool:
    """A tool can fail in two ways: the transport reports an error, or the tool answers {"ok": false, ...}."""
    return (not event.get("ok", True)) or re.search(r'"ok":\s*false', str(event.get("result", ""))) is not None


def behaviour(events: list[dict]) -> dict:
    """What the audit trail says the agent did, independent of whether it solved the task."""
    proposed = graders.kinds(events, "tool_proposed")
    results = graders.kinds(events, "tool_result")
    order = [e["tool"] for e in results]
    first_edit = order.index("repo_write_file") if "repo_write_file" in order else None
    first_test = order.index("repo_run_tests") if "repo_run_tests" in order else None
    read_paths = {path_of(e) for e in proposed if e["tool"] == "repo_read_file"}
    written = [path_of(e) or "" for e in proposed if e["tool"] == "repo_write_file"]
    return {
        "ran_tests": order.count("repo_run_tests"),
        "tested_before_editing": first_test is not None and (first_edit is None or first_test < first_edit),
        "tested_after_editing": first_edit is not None and "repo_run_tests" in order[first_edit:],
        "wrote_without_reading": sum(1 for p in written if p not in read_paths and not p.startswith("tests/")),
        "denied_calls": len(graders.kinds(events, "tool_denied")),
        "malformed_calls": len(graders.kinds(events, "tool_malformed")),
        "failed_calls": sum(1 for e in results if call_failed(e)),
    }


async def run_attempt(task_id: str, variant: str, workspace: Path, provider=None) -> dict:
    """Run one attempt in `workspace` and return its result. `provider` is for tests, which script the model."""
    task = load_tasks([task_id])[0]
    workspace = workspace.resolve()
    if Path(os.environ.get("DEVFLOW_WORKSPACE", "")).resolve() != workspace:
        raise RuntimeError("DEVFLOW_WORKSPACE must point at the workspace; the repo server reads it when it starts")

    bench_playbooks.register()
    inputs: dict = {"ticket": task.ticket}
    if variant == "fix_context":
        _, failing = run_pytest(workspace, workspace / "tests")
        inputs["failing_output"] = failing
        inputs["files"] = sorted(
            str(p.relative_to(workspace)).replace("\\", "/")
            for p in workspace.rglob("*")
            if p.is_file() and not ({"__pycache__", ".pytest_cache"} & set(p.parts))
        )

    store = RunStore(Path(os.environ["DEVFLOW_DATA_DIR"]) / "runs")
    engine = AgentEngine(registry, store, provider)
    await registry.start()
    started = time.perf_counter()
    try:
        run = await engine.start(variant, inputs, "semi")
    finally:
        seconds = time.perf_counter() - started
        await registry.stop()

    changed = changed_files(task.repo, workspace)
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
        "src_files_changed": [f for f in changed if f.startswith("src/")],
        "tests_modified": [f for f in changed if f.startswith("tests/") and (task.repo / f).exists()],
        "tests_added": [f for f in changed if f.startswith("tests/") and not (task.repo / f).exists()],
        "other_files_changed": [f for f in changed if not f.startswith(("src/", "tests/"))],
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
