"""The two test-writing agent set-ups the benchmark compares, registered only inside the benchmark process.

    write_plain    the task and nothing else
    write_method   the task plus a method: list behaviours, boundaries and errors, write exact assertions, run them
"""

from __future__ import annotations

from typing import Any

from orchestrator import playbooks
from orchestrator.playbooks import Playbook, REPO_READ, SHARED_RULES

TOOLS = REPO_READ + ["repo_write_file"]

PLAIN_SYSTEM = SHARED_RULES + "\nTask: write unit tests with pytest for a module in the working copy, using the repo_* tools."

METHOD_SYSTEM = SHARED_RULES + (
    "\nTask: write unit tests with pytest for a module in the working copy, using the repo_* tools.\n"
    "Method:\n"
    "1. Read the module and its docstrings. List what each function promises.\n"
    "2. For each promise, think of the ways a small bug could break it: a comparison that is off by one, "
    "a boundary where two values are equal, zero, empty input, a negative number, an error that should be raised, "
    "state that should or should not change after a failure.\n"
    "3. Write one test per behaviour with exact expected values. Never write a test that cannot fail, such as "
    "assert True. Check that errors are the right exception type, using pytest.raises.\n"
    "4. Run the tests. If one fails, read the module again to see what it really does and fix the expectation. "
    "Do not weaken a test just to make it pass, and do not edit the module.\n"
    "5. Finish with one sentence saying what you covered."
)


def _render(i: dict[str, Any]) -> str:
    return i["ticket"]


def register() -> None:
    playbooks.PLAYBOOKS["write_plain"] = Playbook(
        "write_plain", "Write tests, no extra method.", PLAIN_SYSTEM, TOOLS, ["ticket"], _render
    )
    playbooks.PLAYBOOKS["write_method"] = Playbook(
        "write_method", "Write tests with a boundary-and-error checklist.", METHOD_SYSTEM, TOOLS, ["ticket"], _render
    )


VARIANTS = ["write_plain", "write_method"]
