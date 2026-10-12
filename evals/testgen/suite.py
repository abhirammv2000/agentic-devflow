"""The test-generation benchmark: write unit tests for a module, graded by mutation.

A task is a folder:

    repo/src/<module>.py   the module the agent must test, and a pytest.ini. tests/ starts empty.
    mutants/*.py           copies of the module with one deliberate bug each
    reference/test_*.py    a hand-written test file used only to check the task itself

Passing tests are not the goal, because a test file with no assertions passes. So grading asks two things:
  1. valid:    do the agent's tests pass on the original module? A suite that fails on correct code, finds no
               tests, or does not run is worth nothing.
  2. kill rate: of the mutants, how many make at least one of the agent's tests fail? This is the usual measure of
               whether tests would notice a real bug.
Whatever the agent did to src/ is thrown away before grading, so editing the module cannot help.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

TASKS_DIR = Path(__file__).resolve().parent / "tasks"
PYTEST_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class Task:
    id: str
    path: Path

    @property
    def repo(self) -> Path:
        return self.path / "repo"

    @property
    def module(self) -> Path:
        return next((self.repo / "src").glob("*.py"))

    @property
    def mutants(self) -> list[Path]:
        return sorted((self.path / "mutants").glob("*.py"))

    @property
    def reference(self) -> Path:
        return next((self.path / "reference").glob("test_*.py"))

    @property
    def ticket(self) -> str:
        name = self.module.stem
        return (
            f"Write unit tests for the module src/{name}.py.\n\n"
            f"Put them in tests/test_{name}.py. They must pass on the module as it is now. They will be judged by "
            "how many deliberately broken versions of the module they catch, so test the behaviour the "
            "docstrings describe, including edge cases and invalid input."
        )


def load_tasks(only: list[str] | None = None) -> list[Task]:
    tasks = [Task(p.name, p) for p in sorted(TASKS_DIR.iterdir()) if (p / "repo").exists()]
    if only:
        unknown = set(only) - {t.id for t in tasks}
        if unknown:
            raise SystemExit("unknown task(s): " + ", ".join(sorted(unknown)))
        tasks = [t for t in tasks if t.id in only]
    return tasks


def materialize(task: Task, workspace: Path) -> None:
    if workspace.exists():
        shutil.rmtree(workspace)
    shutil.copytree(task.repo, workspace)


def run_tests(workspace: Path, tests: Path) -> tuple[int, str]:
    argv = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "--rootdir", str(workspace),
            "-c", str(workspace / "pytest.ini"), str(tests)]
    try:
        proc = subprocess.run(argv, cwd=workspace, capture_output=True, text=True, timeout=PYTEST_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return -1, "timed out"
    return proc.returncode, (proc.stdout + proc.stderr)[-2000:]


def count_tests(tests_dir: Path) -> tuple[int, int]:
    """(test functions, assertions) in the agent's test files. An assertion is an assert statement or a pytest.raises."""
    functions = asserts = 0
    for path in tests_dir.rglob("test_*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test"):
                functions += 1
            elif isinstance(node, ast.Assert):
                asserts += 1
            elif isinstance(node, ast.Attribute) and node.attr == "raises":
                asserts += 1
    return functions, asserts


def kills(task: Task, tests_source: Path) -> dict[str, bool]:
    """For each mutant, whether the tests in tests_source (a folder) fail against it."""
    result = {}
    for mutant in task.mutants:
        with tempfile.TemporaryDirectory(prefix="mutant_") as tmp:
            work = Path(tmp) / "w"
            shutil.copytree(task.repo, work)
            shutil.copy(mutant, work / "src" / task.module.name)
            shutil.copytree(tests_source, work / "tests", dirs_exist_ok=True)
            code, _ = run_tests(work, work / "tests")
            result[mutant.stem] = code != 0
    return result


def grade(task: Task, workspace: Path) -> dict:
    functions, asserts = count_tests(workspace / "tests")
    src_modified = (workspace / "src" / task.module.name).read_text(encoding="utf-8") != task.module.read_text(encoding="utf-8")
    base = {"tests": functions, "assertions": asserts, "src_modified": src_modified}

    with tempfile.TemporaryDirectory(prefix="testgen_grade_") as tmp:
        work = Path(tmp) / "w"
        shutil.copytree(task.repo, work)  # the original module, whatever the agent did to its copy
        shutil.copytree(workspace / "tests", work / "tests", dirs_exist_ok=True)
        if not any((work / "tests").rglob("test_*.py")):
            return {**base, "valid": False, "why_invalid": "no test file", "mutants": len(task.mutants), "killed": 0,
                    "kill_rate": 0.0, "survivors": [m.stem for m in task.mutants]}
        code, output = run_tests(work, work / "tests")
        if code != 0:
            why = {5: "no tests collected", -1: "timed out"}.get(code, "tests fail on the original module")
            return {**base, "valid": False, "why_invalid": why, "pytest_output": output, "mutants": len(task.mutants),
                    "killed": 0, "kill_rate": 0.0, "survivors": [m.stem for m in task.mutants]}
        outcome = kills(task, work / "tests")

    killed = sum(outcome.values())
    return {**base, "valid": True, "why_invalid": "", "mutants": len(outcome), "killed": killed,
            "kill_rate": killed / len(outcome), "survivors": sorted(k for k, v in outcome.items() if not v)}
