"""Check that every task is a fair task before any model is run on it.

For each task this confirms that:
  - the buggy repo fails the hidden tests, so there is something to fix,
  - the buggy repo fails at least one visible test, so the ticket has a reproduction,
  - the reference solution passes the hidden tests and the visible tests, so the task is solvable,
  - the hidden tests contain every visible test, so passing them cannot be easier than passing the visible ones.

    python -m evals.codefix.validate
"""

from __future__ import annotations

import ast
import shutil
import sys
import tempfile
from pathlib import Path

from .suite import load_tasks, materialize, run_pytest


def test_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")}


def main() -> int:
    failures: list[str] = []
    tasks = load_tasks()
    with tempfile.TemporaryDirectory(prefix="codefix_validate_") as tmp:
        for task in tasks:
            work = Path(tmp) / task.id
            materialize(task, work)

            hidden_buggy, _ = run_pytest(work, task.hidden)
            visible_buggy, _ = run_pytest(work, work / "tests")
            if hidden_buggy:
                failures.append(f"{task.id}: the buggy repo already passes the hidden tests")
            if visible_buggy:
                failures.append(f"{task.id}: no visible test fails on the buggy repo, so there is no reproduction")

            shutil.copytree(task.solution / "src", work / "src", dirs_exist_ok=True)
            hidden_fixed, out = run_pytest(work, task.hidden)
            visible_fixed, out2 = run_pytest(work, work / "tests")
            if not hidden_fixed:
                failures.append(f"{task.id}: the reference solution fails the hidden tests\n{out}")
            if not visible_fixed:
                failures.append(f"{task.id}: the reference solution fails the visible tests\n{out2}")

            visible_names = set().union(*(test_names(p) for p in (work / "tests").glob("test_*.py")))
            missing = visible_names - test_names(task.hidden)
            if missing:
                failures.append(f"{task.id}: hidden tests lack visible tests {sorted(missing)}")
            print(f"{task.id:18} buggy fails hidden: {not hidden_buggy}  repro visible: {not visible_buggy}  "
                  f"solution passes: {hidden_fixed and visible_fixed}")

    if failures:
        print("\n" + "\n".join(failures))
        return 1
    print(f"\nall {len(tasks)} tasks are valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
