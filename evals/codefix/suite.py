"""Loading the benchmark tasks and grading a working copy against them.

A task is a folder:

    ticket.md        what the agent is told
    repo/            the buggy project the agent works in (source, a pytest.ini, visible tests)
    solution/src/    a reference fix, used only to check that the task is solvable
    hidden/          tests the agent never sees. A task is solved when every one of them passes.

Hidden tests are what makes the result trustworthy. The agent can see and run the visible tests, and it
can edit anything in its working copy, so a model that rewrites a failing test or special-cases the
example from the ticket would look like it passed. Grading runs the hidden tests against whatever source
the agent left behind, and the visible tests are never what decides the result.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

TASKS_DIR = Path(__file__).resolve().parent / "tasks"
PYTEST_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class Task:
    id: str
    path: Path

    @property
    def ticket(self) -> str:
        return (self.path / "ticket.md").read_text(encoding="utf-8")

    @property
    def repo(self) -> Path:
        return self.path / "repo"

    @property
    def solution(self) -> Path:
        return self.path / "solution"

    @property
    def hidden(self) -> Path:
        return self.path / "hidden" / "test_hidden.py"


def load_tasks(only: list[str] | None = None) -> list[Task]:
    tasks = [Task(p.name, p) for p in sorted(TASKS_DIR.iterdir()) if (p / "ticket.md").exists()]
    if only:
        unknown = set(only) - {t.id for t in tasks}
        if unknown:
            raise SystemExit("unknown task(s): " + ", ".join(sorted(unknown)))
        tasks = [t for t in tasks if t.id in only]
    return tasks


def materialize(task: Task, workspace: Path) -> None:
    """Copy the task's repo into an empty folder for the agent to work in."""
    if workspace.exists():
        shutil.rmtree(workspace)
    shutil.copytree(task.repo, workspace)


def run_pytest(workspace: Path, target: Path | str | None = None) -> tuple[bool, str]:
    """Run pytest in the workspace. Returns (all passed, the end of the output)."""
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(workspace),
            "-c", str(workspace / "pytest.ini")]
    if target is not None:
        argv.append(str(target))
    try:
        proc = subprocess.run(argv, cwd=workspace, capture_output=True, text=True, timeout=PYTEST_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return False, "timed out"
    return proc.returncode == 0, (proc.stdout + proc.stderr)[-3000:]


def grade(task: Task, workspace: Path) -> dict:
    """Run the hidden tests against the agent's working copy."""
    passed, output = run_pytest(workspace, task.hidden)
    return {"solved": passed, "hidden_output": output if not passed else ""}


def tree_hash(root: Path, sub: str) -> str:
    """A hash of every file under root/sub, to tell whether the agent changed it."""
    digest = hashlib.sha256()
    base = root / sub
    if base.exists():
        for path in sorted(p for p in base.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            digest.update(str(path.relative_to(base)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def changed_files(original: Path, workspace: Path) -> list[str]:
    """Paths (relative) that differ between the original repo and the workspace, ignoring caches."""

    def files(root: Path) -> dict[str, bytes]:
        return {
            str(p.relative_to(root)).replace("\\", "/"): p.read_bytes()
            for p in root.rglob("*")
            if p.is_file() and not ({"__pycache__", ".pytest_cache"} & set(p.parts))
        }

    before, after = files(original), files(workspace)
    return sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
