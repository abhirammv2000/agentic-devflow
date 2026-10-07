"""Token totals across runs, and the token check on the API."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-placeholder-for-tests")

from orchestrator.store import RunStore  # noqa: E402


def saved_run(store, playbook, input_tokens, output_tokens):
    run = store.create(playbook, {}, "semi")
    run.add_usage(input_tokens, output_tokens)
    store.save(run)
    return run


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path)


def test_no_runs_gives_zero_totals(store):
    summary = store.usage_summary()
    assert summary["total"] == {"runs": 0, "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": None}
    assert summary["by_playbook"] == {}


def test_totals_add_up_overall_and_per_playbook(store):
    saved_run(store, "review_pr", 1000, 200)
    saved_run(store, "review_pr", 500, 100)
    saved_run(store, "issue_triage", 300, 50)

    summary = store.usage_summary()

    assert summary["total"]["runs"] == 3
    assert summary["total"]["input_tokens"] == 1800
    assert summary["total"]["output_tokens"] == 350
    assert summary["by_playbook"]["review_pr"]["runs"] == 2
    assert summary["by_playbook"]["review_pr"]["input_tokens"] == 1500
    assert summary["by_playbook"]["issue_triage"]["output_tokens"] == 50


def test_a_run_with_no_model_call_counts_as_zero_tokens(store):
    store.create("document_change", {}, "semi")

    summary = store.usage_summary()

    assert summary["total"]["runs"] == 1
    assert summary["total"]["input_tokens"] == 0


def test_cost_is_not_estimated_without_prices(store):
    saved_run(store, "review_pr", 1_000_000, 1_000_000)
    assert store.usage_summary()["total"]["estimated_cost_usd"] is None


def test_cost_uses_dollars_per_million_tokens(store):
    saved_run(store, "review_pr", 2_000_000, 500_000)
    saved_run(store, "issue_triage", 1_000_000, 500_000)

    summary = store.usage_summary(input_price=3.0, output_price=15.0)

    # input: 3 million tokens x $3 = $9. Output: 1 million x $15 = $15.
    assert summary["total"]["estimated_cost_usd"] == 24.0
    # review_pr: 2 x 3 + 0.5 x 15 = 13.5
    assert summary["by_playbook"]["review_pr"]["estimated_cost_usd"] == 13.5


def test_only_an_output_price_still_gives_an_estimate(store):
    saved_run(store, "review_pr", 1_000_000, 1_000_000)
    assert store.usage_summary(input_price=0.0, output_price=10.0)["total"]["estimated_cost_usd"] == 10.0
