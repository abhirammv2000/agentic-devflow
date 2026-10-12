"""The three agent set-ups the benchmark compares. They are registered only inside the benchmark process, so
the product's four playbooks are untouched.

All three give the model the same tools (read, search, write, run tests) and the same ticket. They differ in
the prompt and in the context handed over before the first turn, which is what the comparison measures:

    fix_plain    the ticket and nothing else
    fix_tdd      the ticket plus a working method: read, run the tests, make the smallest fix, run them again
    fix_context  the same method, and the first test run and the file list are already in the prompt
"""

from __future__ import annotations

from typing import Any

from orchestrator import playbooks
from orchestrator.playbooks import Playbook, REPO_READ, SHARED_RULES

TOOLS = REPO_READ + ["repo_write_file"]

PLAIN_SYSTEM = SHARED_RULES + (
    "\nTask: fix a bug in the working copy using the repo_* tools. The project has a visible test suite."
)

TDD_SYSTEM = SHARED_RULES + (
    "\nTask: fix a bug in the working copy using the repo_* tools.\n"
    "Method:\n"
    "1. List the files and read the source file the ticket is about, and the tests next to it.\n"
    "2. Run the tests and read the failure before you change anything.\n"
    "3. Make the smallest change to the source that fixes the cause. Do not edit the existing tests.\n"
    "4. Run the tests again. If anything still fails, read the failure and fix it. Repeat until they pass.\n"
    "5. Check the ticket again for behaviour the visible tests do not cover, such as empty input, "
    "boundaries and invalid arguments, and handle it.\n"
    "6. Finish with two sentences: what the cause was and what you changed."
)


def _plain(i: dict[str, Any]) -> str:
    return "Fix this bug.\n\n" + i["ticket"]


def _context(i: dict[str, Any]) -> str:
    return (
        "Fix this bug.\n\n"
        + i["ticket"]
        + "\n\nContext gathered for you before you start.\n\n"
        + "Files in the working copy:\n"
        + "\n".join("  " + f for f in i["files"])
        + "\n\nThe first run of the visible tests (python -m pytest -q) ended like this:\n\n"
        + i["failing_output"]
    )


def register() -> None:
    playbooks.PLAYBOOKS["fix_plain"] = Playbook(
        "fix_plain", "Fix a bug from a ticket, no extra method.", PLAIN_SYSTEM, TOOLS, ["ticket"], _plain
    )
    playbooks.PLAYBOOKS["fix_tdd"] = Playbook(
        "fix_tdd", "Fix a bug with a read, test, fix, retest method.", TDD_SYSTEM, TOOLS, ["ticket"], _plain
    )
    playbooks.PLAYBOOKS["fix_context"] = Playbook(
        "fix_context", "The same method with the first test run in the prompt.", TDD_SYSTEM, TOOLS,
        ["ticket", "files", "failing_output"], _context,
    )


VARIANTS = ["fix_plain", "fix_tdd", "fix_context"]
