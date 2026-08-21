"""Boots the real FastAPI app -- which spawns the three MCP servers over stdio --
and checks the HTTP contract n8n depends on. No model calls are made.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The engine constructs an Anthropic client at startup; it is never called here.
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-placeholder-for-tests")

from fastapi.testclient import TestClient  # noqa: E402

from orchestrator.app import app  # noqa: E402
from orchestrator.config import settings  # noqa: E402

AUTH = {"X-Devflow-Token": settings.service_token}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_healthz_reports_the_live_tool_count(client):
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["mcp_tools"] == 23


def test_every_playbook_is_listed_with_its_inputs(client):
    names = {p["name"]: p for p in client.get("/playbooks").json()["playbooks"]}
    assert set(names) == {"issue_triage", "implement_ticket", "review_pr",
                          "document_change"}
    assert names["implement_ticket"]["required_inputs"] == ["jira_key", "repo"]


def test_tools_endpoint_exposes_the_risk_tier(client):
    tools = {t["name"]: t["tier"] for t in client.get("/tools").json()["tools"]}
    assert tools["gh_get_issue"] == "read"
    assert tools["gh_commit_file"] == "write"
    assert tools["gh_open_pull_request"] == "publish"
    assert tools["gh_merge_pull_request"] == "critical"


def test_runs_require_the_service_token(client):
    assert client.post("/runs", json={"playbook": "review_pr"}).status_code == 401
    assert client.get("/runs").status_code == 401


def test_unknown_playbook_is_404(client):
    resp = client.post("/runs", json={"playbook": "nope"}, headers=AUTH)
    assert resp.status_code == 404


def test_missing_required_input_is_422(client):
    resp = client.post(
        "/runs",
        json={"playbook": "implement_ticket", "inputs": {"repo": "a/b"}},
        headers=AUTH,
    )
    assert resp.status_code == 422
    assert "jira_key" in resp.json()["detail"]


def test_unknown_run_is_404(client):
    assert client.get("/runs/run_nope", headers=AUTH).status_code == 404
    assert client.post("/runs/run_nope/approve", json={}, headers=AUTH).status_code == 404
