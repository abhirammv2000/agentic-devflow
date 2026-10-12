"""Check that every test-generation task is fair before a model is run on it.

For each task the hand-written reference tests must pass on the original module and kill every mutant. If a
mutant survives the reference tests, it is either equivalent to the original (not a bug at all) or the reference
is incomplete, and either way the task cannot be scored fairly.

    python -m evals.testgen.validate
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

from .suite import kills, load_tasks, run_tests


def mutant_problems(task) -> list[str]:
    """A mutant must load without error and differ from the original, or 'killed' could just mean 'broken'."""
    problems = []
    original = task.module.read_text(encoding="utf-8")
    for mutant in task.mutants:
        source = mutant.read_text(encoding="utf-8")
        if source == original:
            problems.append(f"{task.id}/{mutant.stem}: identical to the original")
            continue
        try:
            exec(compile(source, str(mutant), "exec"), {"__name__": "mutant"})
        except Exception as error:  # a mutant that cannot even load would be 'killed' by every test
            problems.append(f"{task.id}/{mutant.stem}: does not load: {type(error).__name__}: {error}")
    return problems


def main() -> int:
    failures: list[str] = []
    tasks = load_tasks()
    for task in tasks:
        failures += mutant_problems(task)
        with tempfile.TemporaryDirectory(prefix="testgen_validate_") as tmp:
            work = Path(tmp) / "w"
            shutil.copytree(task.repo, work)
            shutil.copy(task.reference, work / "tests" / task.reference.name)
            code, output = run_tests(work, work / "tests")
            if code != 0:
                failures.append(f"{task.id}: the reference tests fail on the original module\n{output}")
                continue
            outcome = kills(task, work / "tests")
        survivors = sorted(k for k, v in outcome.items() if not v)
        print(f"{task.id:10} reference passes; kills {len(outcome) - len(survivors)} of {len(outcome)} mutants")
        if survivors:
            failures.append(f"{task.id}: mutants not killed by the reference tests: {survivors}")
    if failures:
        print("\n" + "\n".join(failures))
        return 1
    print(f"\nall {len(tasks)} tasks are valid ({sum(len(t.mutants) for t in tasks)} mutants)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
