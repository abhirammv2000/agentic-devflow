"""Signed approve and reject links. The public n8n webhook forwards a click, and the orchestrator checks the
signature before it resumes anything. No model and no network."""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-placeholder-for-tests")

from fastapi.testclient import TestClient  # noqa: E402

from orchestrator import app as app_module  # noqa: E402
from orchestrator import signing  # noqa: E402
from orchestrator.store import STATUS_AWAITING_APPROVAL, RunStore  # noqa: E402

SECRET = "link-secret"
IDS = ["t1", "t2"]
HEADERS = {"X-Devflow-Token": app_module.settings.service_token}
WORKFLOW = Path(__file__).resolve().parent.parent / "n8n" / "workflows" / "04-human-approval-gate.json"


# the token

def test_a_token_made_for_a_decision_checks_out():
    tokens = signing.make_link_tokens(SECRET, "run_1", IDS, 3600, now=1000)

    assert signing.check_link_token(SECRET, "run_1", "approve", IDS, tokens["expires"], tokens["approve"], now=1001) is None
    assert signing.check_link_token(SECRET, "run_1", "reject", IDS, tokens["expires"], tokens["reject"], now=1001) is None


def test_an_approve_token_cannot_be_used_to_reject_and_the_other_way_round():
    tokens = signing.make_link_tokens(SECRET, "run_1", IDS, 3600, now=1000)

    assert signing.check_link_token(SECRET, "run_1", "reject", IDS, tokens["expires"], tokens["approve"], now=1001) == "does not match"
    assert signing.check_link_token(SECRET, "run_1", "approve", IDS, tokens["expires"], tokens["reject"], now=1001) == "does not match"


@pytest.mark.parametrize("change", ["run", "pending", "secret", "expiry"])
def test_a_token_is_bound_to_the_run_the_pending_calls_the_secret_and_the_expiry(change):
    tokens = signing.make_link_tokens(SECRET, "run_1", IDS, 3600, now=1000)
    run, pending, secret, expires = "run_1", IDS, SECRET, tokens["expires"]
    if change == "run":
        run = "run_2"
    elif change == "pending":
        pending = ["t1", "t3"]  # a later pause of the same run, with different calls waiting
    elif change == "secret":
        secret = "another"
    else:
        expires += 1000  # stretching the lifetime of a stolen token

    assert signing.check_link_token(secret, run, "approve", pending, expires, tokens["approve"], now=1001) == "does not match"


def test_the_order_of_the_pending_ids_does_not_matter():
    tokens = signing.make_link_tokens(SECRET, "run_1", ["t2", "t1"], 3600, now=1000)

    assert signing.check_link_token(SECRET, "run_1", "approve", ["t1", "t2"], tokens["expires"], tokens["approve"], now=1001) is None


def test_a_token_stops_working_after_its_expiry_and_missing_values_are_refused():
    tokens = signing.make_link_tokens(SECRET, "run_1", IDS, 60, now=1000)

    assert signing.check_link_token(SECRET, "run_1", "approve", IDS, tokens["expires"], tokens["approve"], now=1061) == "expired"
    assert signing.check_link_token(SECRET, "run_1", "approve", IDS, tokens["expires"], None) == "no token"
    assert signing.check_link_token(SECRET, "run_1", "approve", IDS, None, tokens["approve"]) == "no token"
    assert signing.check_link_token(SECRET, "run_1", "approve", IDS, tokens["expires"], "") == "no token"


# the endpoint

@pytest.fixture
def paused(tmp_path, monkeypatch):
    """A run waiting for approval, in a store the app uses."""
    store = RunStore(tmp_path / "runs")
    monkeypatch.setattr(app_module, "run_store", store)
    run = store.create("review_pr", {"repo": "a/b", "number": 1}, "semi")
    run.status = STATUS_AWAITING_APPROVAL
    run.pending = {"calls": [], "approvals": [
        {"tool_use_id": "t1", "tool": "gh_review_pull_request", "tier": "publish", "reason": "x", "arguments": "{}"}]}
    store.save(run)

    class Recorder:
        resumed = []

        async def resume(self, run, decisions, reviewer="human", note=""):
            Recorder.resumed.append((decisions, reviewer))
            run.status = "completed"
            return run

    monkeypatch.setattr(app_module, "engine", Recorder())
    Recorder.resumed = []
    return run, Recorder


def click(client, run, decision, **override):
    links = run_links(run)
    body = {"source": "link", "token": links[decision], "expires": links["expires"],
            "approve_all": decision == "approve", "reject_all": decision == "reject", "reviewer": "link-click"}
    body.update(override)
    return client.post(f"/runs/{run.id}/approve", json=body, headers=HEADERS)


def run_links(run):
    return RunStore(app_module.run_store.dir).load(run.id).public()["approval_links"]


def test_the_run_view_carries_links_only_while_a_decision_is_waiting(paused):
    run, _ = paused

    links = run_links(run)

    assert set(links) == {"approve", "reject", "expires"}
    fresh = app_module.run_store.create("review_pr", {}, "semi")
    assert fresh.public()["approval_links"] is None


def test_a_click_with_a_valid_token_resumes_the_run(paused):
    run, recorder = paused
    with nullcontext(TestClient(app_module.app)) as client:  # no lifespan, so no MCP servers start
        response = click(client, run, "approve")

    assert response.status_code == 200
    assert recorder.resumed == [({"t1": True}, "link-click")]


def test_a_reject_click_rejects(paused):
    run, recorder = paused
    with nullcontext(TestClient(app_module.app)) as client:  # no lifespan, so no MCP servers start
        response = click(client, run, "reject")

    assert response.status_code == 200 and recorder.resumed == [({"t1": False}, "link-click")]


@pytest.mark.parametrize("override", [
    {"token": None}, {"token": "0" * 64}, {"expires": 1}, {"expires": None},
])
def test_a_click_without_a_good_token_is_refused_and_nothing_resumes(paused, override):
    run, recorder = paused
    with nullcontext(TestClient(app_module.app)) as client:  # no lifespan, so no MCP servers start
        response = click(client, run, "approve", **override)

    assert response.status_code == 403 and response.json()["detail"] == "invalid or expired approval link"
    assert recorder.resumed == []


def test_the_reject_token_cannot_approve(paused):
    run, recorder = paused
    links = run_links(run)
    with nullcontext(TestClient(app_module.app)) as client:  # no lifespan, so no MCP servers start
        response = click(client, run, "approve", token=links["reject"])

    assert response.status_code == 403 and recorder.resumed == []


def test_a_link_decision_must_be_all_or_nothing(paused):
    run, recorder = paused
    with nullcontext(TestClient(app_module.app)) as client:  # no lifespan, so no MCP servers start
        neither = click(client, run, "approve", approve_all=False, reject_all=False)
        both = click(client, run, "approve", approve_all=True, reject_all=True)

    assert neither.status_code == 422 and both.status_code == 422 and recorder.resumed == []


def test_a_link_cannot_name_single_calls(paused):
    run, recorder = paused
    with nullcontext(TestClient(app_module.app)) as client:  # no lifespan, so no MCP servers start
        response = click(client, run, "approve", approve_all=False, decisions={"t1": True})

    assert response.status_code == 422 and recorder.resumed == []


def test_the_service_token_alone_still_works_for_a_direct_api_caller(paused):
    run, recorder = paused
    with nullcontext(TestClient(app_module.app)) as client:  # no lifespan, so no MCP servers start
        response = client.post(f"/runs/{run.id}/approve", json={"approve_all": True}, headers=HEADERS)

    assert response.status_code == 200 and recorder.resumed == [({"t1": True}, "human")]


def test_a_link_with_no_service_token_is_unauthorised_before_anything_else(paused):
    run, recorder = paused
    links = run_links(run)
    with nullcontext(TestClient(app_module.app)) as client:  # no lifespan, so no MCP servers start
        response = client.post(f"/runs/{run.id}/approve", json={"source": "link", "approve_all": True,
                                                                "token": links["approve"], "expires": links["expires"]})

    assert response.status_code == 401 and recorder.resumed == []


def test_the_signing_secret_can_be_set_separately_from_the_service_token(paused, monkeypatch):
    run, recorder = paused
    monkeypatch.setattr(app_module, "settings", dataclasses.replace(app_module.settings, approval_secret="separate"))
    from orchestrator import store as store_module
    monkeypatch.setattr(store_module, "settings", dataclasses.replace(store_module.settings, approval_secret="separate"))

    with nullcontext(TestClient(app_module.app)) as client:  # no lifespan, so no MCP servers start
        good = click(client, run, "approve")
        wrong = click(client, run, "approve", token=signing.make_link_tokens("other", run.id, ["t1"], 3600)["approve"])

    assert good.status_code == 200 and wrong.status_code == 403


# the n8n workflow

def card_script(run: dict, code: str) -> str:
    """The card builder's code wrapped so node can run it with n8n's $input and $env."""
    lines = [
        "const $input = { first: () => ({ json: " + json.dumps(run) + " }) };",
        "const $env = { N8N_PUBLIC_URL: 'http://n8n' };",
        "const out = (function () {",
        code,
        "})();",
        "console.log(JSON.stringify(out));",
    ]
    return "\n".join(lines) + "\n"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_workflow_builds_links_that_carry_the_orchestrators_tokens(tmp_path):
    """Runs the card builder's own JavaScript under node with a real orchestrator payload."""
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    code = next(n for n in workflow["nodes"] if n["name"] == "Build approval card")["parameters"]["jsCode"]
    run = {"event": "run.approval_required", "run_id": "run_abc", "playbook": "review_pr", "summary": "s",
           "pending_approvals": [{"tool": "gh_review_pull_request", "tier": "publish", "reason": "r", "arguments": "{}"}],
           "approval_links": {"approve": "A" * 64, "reject": "R" * 64, "expires": 1234567890}}
    script = tmp_path / "card.js"
    script.write_text(card_script(run, code), encoding="utf-8")

    output = json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, check=True).stdout)[0]["json"]

    assert output["approveUrl"] == "http://n8n/webhook/devflow-approve?run_id=run_abc&decision=approve&token=" + "A" * 64 + "&expires=1234567890"
    assert output["rejectUrl"].endswith("decision=reject&token=" + "R" * 64 + "&expires=1234567890")

    # an orchestrator that sent no tokens must not produce usable links
    run["approval_links"] = None
    script.write_text(card_script(run, code), encoding="utf-8")
    skipped = json.loads(subprocess.run(["node", str(script)], capture_output=True, text=True, check=True).stdout)[0]["json"]

    assert skipped["skipped"] is True and "approveUrl" not in skipped


def test_the_resume_node_forwards_the_token_and_marks_the_call_as_a_link():
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    body = next(n for n in workflow["nodes"] if n["name"] == "Resume the run")["parameters"]["jsonBody"]

    assert "source: 'link'" in body and "token: $json.query.token" in body and "expires: Number($json.query.expires)" in body
