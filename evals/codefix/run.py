"""Run the code-fix benchmark: every task, with each agent set-up, a number of times, against one model.

    DEVFLOW_PROVIDER=ollama DEVFLOW_MODEL=qwen2.5-coder:7b \
      python -m evals.codefix.run --repeats 2

Results are appended to evals/results/codefix_<model>.jsonl, one line per attempt, and the run can be stopped
and started again: attempts that are already in the file are skipped. Attempts where the provider failed
(no credit, a bad key, a timeout) are reported and left out of the file, so a table of errors cannot pass for
a result. Nothing here calls a paid API unless you point it at one.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.codefix.bench_playbooks import VARIANTS  # noqa: E402
from evals.codefix.suite import load_tasks, materialize  # noqa: E402

RESULTS = ROOT / "evals" / "results"
ATTEMPT_TIMEOUT_SECONDS = 20 * 60


def result_path(model: str) -> Path:
    return RESULTS / ("codefix_" + model.replace("/", "_").replace(":", "_") + ".jsonl")


def done(path: Path) -> set[tuple[str, str, int]]:
    if not path.exists():
        return set()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {(r["task"], r["variant"], r["repeat"]) for r in rows}


def attempt(task_id: str, variant: str) -> dict | None:
    """Run one attempt in a fresh process and workspace. Returns its result, or None if it crashed."""
    with tempfile.TemporaryDirectory(prefix="codefix_") as tmp:
        tmp_path = Path(tmp)
        workspace = tmp_path / "workspace"
        task = load_tasks([task_id])[0]
        materialize(task, workspace)
        out = tmp_path / "result.json"
        env = dict(os.environ)
        env["DEVFLOW_WORKSPACE"] = str(workspace)
        env["DEVFLOW_DATA_DIR"] = str(tmp_path / "data")
        argv = [sys.executable, "-m", "evals.codefix.run_one", "--task", task_id, "--variant", variant,
                "--workspace", str(workspace), "--out", str(out)]
        try:
            proc = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True,
                                  timeout=ATTEMPT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return {"task": task_id, "variant": variant, "status": "timeout", "provider_failed": False,
                    "solved": False, "seconds": ATTEMPT_TIMEOUT_SECONDS, "error": "attempt timed out"}
        if not out.exists():
            print(f"  crashed: {proc.stderr[-400:]}", file=sys.stderr)
            return None
        return json.loads(out.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--variants", nargs="*", default=VARIANTS, choices=VARIANTS)
    parser.add_argument("--tasks", nargs="*", help="task ids; default all")
    args = parser.parse_args()

    from orchestrator.config import settings

    model = f"{settings.provider}:{settings.model}"
    RESULTS.mkdir(exist_ok=True)
    path = result_path(model)
    finished = done(path)
    tasks = load_tasks(args.tasks)
    plan = [(t.id, v, r) for r in range(args.repeats) for t in tasks for v in args.variants]
    todo = [p for p in plan if p not in finished]
    print(f"{model}: {len(plan)} attempts planned, {len(finished & set(plan))} already done, {len(todo)} to run")

    provider_failures = 0
    for n, (task_id, variant, repeat) in enumerate(todo, 1):
        started = time.perf_counter()
        row = attempt(task_id, variant)
        if row is None:
            continue
        row["repeat"] = repeat
        elapsed = time.perf_counter() - started
        if row.get("provider_failed"):
            provider_failures += 1
            print(f"[{n}/{len(todo)}] {task_id} {variant}: provider failure, not saved: {row['error'][:120]}")
            if provider_failures >= 3:
                sys.exit("3 provider failures, stopping. Check the model is running and the name is right.")
            continue
        provider_failures = 0
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        mark = "solved" if row.get("solved") else "failed"
        print(f"[{n}/{len(todo)}] {task_id:16} {variant:12} r{repeat} {mark:7} {row.get('seconds', 0):6.1f}s "
              f"{row.get('tool_calls', 0)} calls  ({elapsed:.0f}s wall)", flush=True)


if __name__ == "__main__":
    main()
