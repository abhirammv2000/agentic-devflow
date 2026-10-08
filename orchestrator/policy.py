"""Autonomy policy: which tool calls the agent may make without asking.

The model proposes tool calls and this decides whether each one runs now, waits for a
human, or is refused.

Four risk tiers, lowest to highest:

  read      no side effects
  write     side effects that stay local or are easy to undo
  publish   visible to other people (PRs, reviews, tickets, comments)
  critical  irreversible or wide blast radius (merges)

Three autonomy levels:

  supervised  auto-run read only
  semi        auto-run read and write            <- default
  autonomous  auto-run read, write and publish

critical always needs a human, at every level. That floor is deliberately not
configurable, because an autonomy setting is something someone changes in a .env file and
"merge to main" should not be one edit away.

One more rule, for prompt injection. Text from read tools (issue bodies, tickets, files, test
output) can be written by an attacker. Once a run has read any, publish needs a human even at
'autonomous'. Only the model's judgement stands between an injected instruction and a public
comment otherwise, and that is not enough. The rule is on by default (DEVFLOW_TAINT_RULE).
"""

from __future__ import annotations

from dataclasses import dataclass

READ = "read"
WRITE = "write"
PUBLISH = "publish"
CRITICAL = "critical"

TIER_ORDER = [READ, WRITE, PUBLISH, CRITICAL]

TOOL_TIERS: dict[str, str] = {
    # read
    "gh_list_issues": READ,
    "gh_get_issue": READ,
    "gh_get_file": READ,
    "gh_get_pull_request": READ,
    "jira_get_issue": READ,
    "jira_search": READ,
    "repo_list_files": READ,
    "repo_read_file": READ,
    "repo_search": READ,
    "repo_diff": READ,
    "repo_run_tests": READ,
    # write
    "gh_create_branch": WRITE,
    "gh_commit_file": WRITE,
    "gh_set_labels": WRITE,
    "repo_write_file": WRITE,
    # publish
    "gh_comment_issue": PUBLISH,
    "gh_open_pull_request": PUBLISH,
    "gh_review_pull_request": PUBLISH,
    "jira_create_issue": PUBLISH,
    "jira_comment": PUBLISH,
    "jira_transition": PUBLISH,
    "jira_link_pull_request": PUBLISH,
    # critical
    "gh_merge_pull_request": CRITICAL,
}

AUTO_CEILING: dict[str, str] = {
    "supervised": READ,
    "semi": WRITE,
    "autonomous": PUBLISH,
}

DECISION_AUTO = "auto"
DECISION_APPROVAL = "needs_approval"
DECISION_DENIED = "denied"


@dataclass(frozen=True)
class Decision:
    action: str          # auto | needs_approval | denied
    tier: str
    reason: str


def tier_of(tool_name: str) -> str:
    """Unknown tools are treated as critical, so the policy fails closed."""
    return TOOL_TIERS.get(tool_name, CRITICAL)


def reads_outside_text(tool_name: str) -> bool:
    """True if the tool returns text somebody else could have written."""
    return tier_of(tool_name) == READ


def evaluate(
    tool_name: str,
    autonomy: str,
    allowed_tools: list[str] | None = None,
    tainted: bool = False,
) -> Decision:
    """Decide how a single proposed tool call should be handled.

    `tainted` means the run has read outside text, or is about to in the same turn."""
    tier = tier_of(tool_name)

    if allowed_tools is not None and tool_name not in allowed_tools:
        return Decision(
            DECISION_DENIED,
            tier,
            "'{}' is outside this playbook's tool surface".format(tool_name),
        )

    if tool_name not in TOOL_TIERS:
        return Decision(
            DECISION_APPROVAL,
            tier,
            "'{}' has no risk classification; treated as critical".format(tool_name),
        )

    if tier == CRITICAL:
        return Decision(
            DECISION_APPROVAL,
            tier,
            "irreversible action, human approval is always required",
        )

    ceiling = AUTO_CEILING.get(autonomy, WRITE)
    if tainted and tier == PUBLISH and TIER_ORDER.index(tier) <= TIER_ORDER.index(ceiling):
        return Decision(
            DECISION_APPROVAL,
            tier,
            "this run has read text from outside (an issue, a ticket, a file), so '{}' needs a human "
            "even at the '{}' level".format(tool_name, autonomy),
        )
    if TIER_ORDER.index(tier) <= TIER_ORDER.index(ceiling):
        return Decision(DECISION_AUTO, tier, "'{}' tier is within the '{}' autonomy "
                                             "ceiling".format(tier, autonomy))
    return Decision(
        DECISION_APPROVAL,
        tier,
        "'{}' tier exceeds the '{}' autonomy ceiling ('{}')".format(tier, autonomy, ceiling),
    )
