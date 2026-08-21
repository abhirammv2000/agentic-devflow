"""The autonomy policy is the safety boundary, so it gets the closest tests."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator import policy  # noqa: E402
from orchestrator.playbooks import PLAYBOOKS  # noqa: E402


@pytest.mark.parametrize(
    "tool,autonomy,expected",
    [
        ("gh_get_issue", "supervised", policy.DECISION_AUTO),
        ("gh_create_branch", "supervised", policy.DECISION_APPROVAL),
        ("gh_create_branch", "semi", policy.DECISION_AUTO),
        ("gh_open_pull_request", "semi", policy.DECISION_APPROVAL),
        ("gh_open_pull_request", "autonomous", policy.DECISION_AUTO),
        ("jira_create_issue", "semi", policy.DECISION_APPROVAL),
        ("repo_write_file", "semi", policy.DECISION_AUTO),
    ],
)
def test_tier_ceilings(tool, autonomy, expected):
    assert policy.evaluate(tool, autonomy).action == expected


@pytest.mark.parametrize("autonomy", ["supervised", "semi", "autonomous"])
def test_merge_always_needs_a_human(autonomy):
    """The critical floor is not something an env var can lower."""
    decision = policy.evaluate("gh_merge_pull_request", autonomy)
    assert decision.action == policy.DECISION_APPROVAL
    assert decision.tier == policy.CRITICAL


def test_unknown_tool_fails_closed():
    decision = policy.evaluate("rm_minus_rf", "autonomous")
    assert decision.action == policy.DECISION_APPROVAL
    assert decision.tier == policy.CRITICAL


def test_playbook_tool_surface_is_enforced():
    """Triage may not open pull requests even at the highest autonomy."""
    triage = PLAYBOOKS["issue_triage"]
    decision = policy.evaluate("gh_open_pull_request", "autonomous", triage.allowed_tools)
    assert decision.action == policy.DECISION_DENIED


def test_every_playbook_tool_has_a_tier():
    """A tool nobody classified would silently become 'critical' at runtime."""
    for book in PLAYBOOKS.values():
        unclassified = [t for t in book.allowed_tools if t not in policy.TOOL_TIERS]
        assert not unclassified, "{}: {}".format(book.name, unclassified)


def test_review_playbook_cannot_reach_write_tools():
    review = PLAYBOOKS["review_pr"]
    for tool in ("gh_commit_file", "repo_write_file", "gh_merge_pull_request"):
        assert tool not in review.allowed_tools
