"""Playbooks: the four developer tasks this prototype automates.

A playbook is a name, a system prompt, the subset of MCP tools the agent may
touch, and how to render the trigger payload into an opening user message.
Narrowing the tool surface per task is a safety measure as much as a prompting
one -- the triage playbook physically cannot open a pull request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

SHARED_RULES = """\
You are DevFlow, a semi-autonomous engineering agent wired into a team's GitHub
and Jira through MCP tools.

Operating rules:
- Ground every claim in a tool result. Read before you write; never guess a file's
  contents, an issue number, or a ticket key.
- Some tool calls are intercepted and routed to a human for approval. If a result
  says the action was declined, do not retry it and do not attempt a workaround
  through a different tool -- report what is blocked and stop.
- Prefer one careful change over several speculative ones. If the task is
  under-specified or the codebase contradicts the request, say so and stop rather
  than inventing requirements.
- When you are finished, reply with a short plain-text report: what you did, the
  links or identifiers you created, and anything a human still needs to decide.
- Never include secrets, tokens, or customer data in anything you publish.
"""


@dataclass(frozen=True)
class Playbook:
    name: str
    description: str
    system: str
    allowed_tools: list[str]
    required_inputs: list[str]
    render: Callable[[dict[str, Any]], str]


def _triage_prompt(i: dict[str, Any]) -> str:
    return (
        "A new issue was opened: {repo}#{number}.\n\n"
        "1. Read the issue.\n"
        "2. Decide its type (bug / feature / question / docs), a severity "
        "(sev1..sev4) and the owning area.\n"
        "3. Apply labels on GitHub reflecting that judgement.\n"
        "4. Search Jira for an existing ticket covering the same problem. If none "
        "exists, create one in project {jira_project} with a clear reproduction "
        "summary and a priority matching the severity.\n"
        "5. Comment on the GitHub issue linking the Jira key and stating the "
        "triage decision in two sentences."
    ).format(
        repo=i["repo"], number=i["number"], jira_project=i.get("jira_project", "ENG")
    )


def _implement_prompt(i: dict[str, Any]) -> str:
    return (
        "Implement the change described by Jira ticket {key}.\n\n"
        "1. Read the ticket.\n"
        "2. Explore the working copy (repo_* tools) until you can point to the exact "
        "lines responsible. Do not start editing before you can.\n"
        "3. Make the smallest correct change, plus a regression test that fails "
        "without it.\n"
        "4. Run the test suite. If it fails, fix it -- do not proceed with a red suite.\n"
        "5. Create a branch named {branch}, commit the changed files to {repo}, and "
        "open a pull request whose body explains the root cause, the fix and the "
        "test evidence.\n"
        "6. Link the pull request on the Jira ticket and move it to In Review."
    ).format(
        key=i["jira_key"],
        repo=i["repo"],
        branch=i.get("branch", "devflow/" + str(i["jira_key"]).lower()),
    )


def _review_prompt(i: dict[str, Any]) -> str:
    return (
        "Review pull request {repo}#{number}.\n\n"
        "1. Fetch the pull request and its diff.\n"
        "2. Read enough surrounding code to judge the change in context.\n"
        "3. Look for correctness bugs, missing error handling, missing tests, and "
        "security or data-handling problems. Ignore pure style.\n"
        "4. Submit one review. Use REQUEST_CHANGES only for defects you can name a "
        "concrete failure scenario for; otherwise COMMENT. Do not APPROVE -- a human "
        "owns that call.\n"
        "5. Order findings most severe first and quote the offending lines."
    ).format(repo=i["repo"], number=i["number"])


def _docs_prompt(i: dict[str, Any]) -> str:
    return (
        "Update the documentation for the change in {repo}#{number}.\n\n"
        "1. Read the pull request diff and the files it touches.\n"
        "2. Read {docs_path} in the working copy (create it if it is missing).\n"
        "3. Rewrite only the sections the change invalidates. Keep the existing "
        "voice and structure; do not restate the diff.\n"
        "4. Commit the documentation to branch {branch} and open a pull request that "
        "references #{number}."
    ).format(
        repo=i["repo"],
        number=i["number"],
        docs_path=i.get("docs_path", "docs/README.md"),
        branch=i.get("branch", "devflow/docs-{}".format(i["number"])),
    )


GITHUB_READ = ["gh_list_issues", "gh_get_issue", "gh_get_file", "gh_get_pull_request"]
JIRA_READ = ["jira_get_issue", "jira_search"]
REPO_READ = ["repo_list_files", "repo_read_file", "repo_search", "repo_diff",
             "repo_run_tests"]

PLAYBOOKS: dict[str, Playbook] = {
    "issue_triage": Playbook(
        name="issue_triage",
        description="Classify a new GitHub issue, label it, and open the Jira ticket.",
        system=SHARED_RULES + (
            "\nTask: issue triage. You classify and route work. You never write code "
            "and never touch pull requests. Severity guide: sev1 = data loss, money "
            "loss or full outage; sev2 = a core flow broken for many users; sev3 = "
            "degraded behaviour with a workaround; sev4 = cosmetic."
        ),
        allowed_tools=GITHUB_READ + JIRA_READ + [
            "gh_set_labels", "gh_comment_issue", "jira_create_issue", "jira_comment",
        ],
        required_inputs=["repo", "number"],
        render=_triage_prompt,
    ),
    "implement_ticket": Playbook(
        name="implement_ticket",
        description="Turn a Jira ticket into a tested pull request.",
        system=SHARED_RULES + (
            "\nTask: implementation. You are writing production code. A change without "
            "a test that would have caught the bug is not finished. Match the "
            "surrounding code's style, naming and error-handling conventions rather "
            "than importing your own. Do not refactor code the ticket did not ask "
            "you to touch."
        ),
        allowed_tools=GITHUB_READ + JIRA_READ + REPO_READ + [
            "repo_write_file", "gh_create_branch", "gh_commit_file",
            "gh_open_pull_request", "jira_comment", "jira_transition",
            "jira_link_pull_request",
        ],
        required_inputs=["jira_key", "repo"],
        render=_implement_prompt,
    ),
    "review_pr": Playbook(
        name="review_pr",
        description="Review a pull request and post the findings.",
        system=SHARED_RULES + (
            "\nTask: code review. Report only defects you can describe a concrete "
            "failing input or state for. No nitpicks, no praise padding, no summary "
            "of what the diff does -- the author already knows. If the diff is clean, "
            "say so in one line."
        ),
        allowed_tools=GITHUB_READ + REPO_READ + ["gh_review_pull_request"],
        required_inputs=["repo", "number"],
        render=_review_prompt,
    ),
    "document_change": Playbook(
        name="document_change",
        description="Update project documentation to match a merged or open change.",
        system=SHARED_RULES + (
            "\nTask: documentation. You are editing docs a human wrote. Preserve their "
            "voice. Change the minimum needed for the docs to be true again, and never "
            "add a changelog entry describing your own edit."
        ),
        allowed_tools=GITHUB_READ + REPO_READ + [
            "repo_write_file", "gh_create_branch", "gh_commit_file",
            "gh_open_pull_request",
        ],
        required_inputs=["repo", "number"],
        render=_docs_prompt,
    ),
}


def get(name: str) -> Playbook:
    if name not in PLAYBOOKS:
        raise KeyError(
            "unknown playbook '{}'; available: {}".format(
                name, ", ".join(sorted(PLAYBOOKS))
            )
        )
    return PLAYBOOKS[name]


def validate_inputs(playbook: Playbook, inputs: dict[str, Any]) -> list[str]:
    return [key for key in playbook.required_inputs if not inputs.get(key)]
