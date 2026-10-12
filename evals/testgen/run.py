"""Run the test-writing benchmark against one model.

    DEVFLOW_PROVIDER=ollama DEVFLOW_MODEL=qwen2.5-coder:7b \
      python -m evals.testgen.run

Same behaviour as the code-fix runner: results are appended to evals/results/testgen_<model>.jsonl, an interrupted
run resumes, and attempts where the provider failed are reported and not saved.
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

from evals.testgen.bench_playbooks import VARIANTS  # noqa: E402
from evals.testgen.suite import load_tasks, materialize  # noqa: E402

RESULTS = ROOT / "evals" / "results"
ATTEMPT_TIMEOUT_SECONDS = 20 * 60


def result_path(model: str) -> Path:
    return RESULTS / ("testgen_" + model.replace("/", "_").replace(":", "_") + ".jsonl")


def done(path: Path) -> set[tuple[str, str, int]]:
    if not path.exists():
        return set()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {(r["task"], r["variant"], r["repeat"]) for r in rows}


def attempt(task_id: str, variant: str) -> dict | None:
    with tempfile.TemporaryDirectory(prefix="testgen_") as tmp:
        tmp_path = Path(tmp)
        workspace = tmp_path / "workspace"
        materialize(load_tasks([task_id])[0], workspace)
        out = tmp_path / "result.json"
        env = dict(os.environ)
        env["DEVFLOW_WORKSPACE"] = str(workspace)
        env["DEVFLOW_DATA_DIR"] = str(tmp_path / "data")
        argv = [sys.executable, "-m", "evals.testgen.run_one", "--task", task_id, "--variant", variant,
                "--workspace", str(workspace), "--out", str(out)]
        try:
            proc = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, timeout=ATTEMPT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return {"task": task_id, "variant": variant, "status": "timeout", "provider_failed": False, "valid": False,
                    "why_invalid": "attempt timed out", "kill_rate": 0.0, "seconds": ATTEMPT_TIMEOUT_SECONDS,
                    "error": "attempt timed out", "tests": 0, "assertions": 0, "mutants": 0, "survivors": [],
                    "src_modified": False, "ran_tests": 0, "input_tokens": 0, "output_tokens": 0}
        if not out.exists():
            print(f"  crashed: {proc.stderr[-400:]}", file=sys.stderr)
            return None
        return json.loads(out.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--variants", nargs="*", default=VARIANTS, choices=VARIANTS)
    parser.add_argument("--tasks", nargs="*")
    args = parser.parse_args()

    from orchestrator.config import settings

    model = f"{settings.provider}:{settings.model}"
    RESULTS.mkdir(exist_ok=True)
    path = result_path(model)
    finished = done(path)
    plan = [(t.id, v, r) for r in range(args.repeats) for t in load_tasks(args.tasks) for v in args.variants]
    todo = [p for p in plan if p not in finished]
    print(f"{model}: {len(plan)} attempts planned, {len(finished & set(plan))} already done, {len(todo)} to run")

    provider_failures = 0
    for n, (task_id, variant, repeat) in enumerate(todo, 1):
        started = time.perf_counter()
        row = attempt(task_id, variant)
        if row is None:
            continue
        row["repeat"] = repeat
        if row.get("provider_failed"):
            provider_failures += 1
            print(f"[{n}/{len(todo)}] {task_id} {variant}: provider failure, not saved: {row['error'][:120]}")
            if provider_failures >= 3:
                sys.exit("3 provider failures, stopping. Check the model is running and the name is right.")
            continue
        provider_failures = 0
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        verdict = f"kill rate {row.get('kill_rate', 0):.0%}" if row.get("valid") else "invalid: " + str(row.get("why_invalid"))
        print(f"[{n}/{len(todo)}] {task_id:10} {variant:13} {verdict:28} {row.get('seconds', 0):6.1f}s "
              f"({time.perf_counter() - started:.0f}s wall)", flush=True)


if __name__ == "__main__":
    main()
