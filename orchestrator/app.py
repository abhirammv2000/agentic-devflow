"""HTTP API that the n8n workflows call.

n8n handles triggers, notifications and the human approval step. This service runs the
agent loop, the tools and the audit trail. Approval sits in n8n so that someone who isn't
an engineer can change it without touching Python.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import playbooks
from .config import settings
from .engine import AgentEngine
from .mcp_registry import registry
from .store import STATUS_AWAITING_APPROVAL, RunStore

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("devflow.api")

run_store = RunStore()
engine: AgentEngine | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global engine
    await registry.start()
    engine = AgentEngine(registry, run_store)
    if settings.service_token == DEFAULT_TOKEN:
        log.warning(
            "DEVFLOW_SERVICE_TOKEN is the public default, so anyone who can reach this "
            "service can start runs. Set your own before exposing it."
        )
    log.info(
        "devflow ready | %s model=%s autonomy=%s mock=%s tools=%d",
        settings.provider,
        settings.model,
        settings.autonomy,
        settings.mock,
        len(registry.tools),
    )
    try:
        yield
    finally:
        await registry.stop()


app = FastAPI(
    title="DevFlow orchestrator",
    version="0.1.0",
    description="Semi-autonomous developer workflows over MCP, driven by n8n.",
    lifespan=lifespan,
)


DEFAULT_TOKEN = "dev-local-token"


def require_token(x_devflow_token: str = Header(default="")) -> None:
    # compare_digest takes the same time however many leading characters match
    if not hmac.compare_digest(x_devflow_token.encode(), settings.service_token.encode()):
        raise HTTPException(status_code=401, detail="bad or missing X-Devflow-Token")


def _engine() -> AgentEngine:
    if engine is None:
        raise HTTPException(status_code=503, detail="orchestrator is still starting")
    return engine


# models

class RunRequest(BaseModel):
    playbook: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    autonomy: str | None = None
    wait: bool = True


class ApprovalRequest(BaseModel):
    decisions: dict[str, bool] = Field(default_factory=dict)
    approve_all: bool = False
    reject_all: bool = False
    reviewer: str = "human"
    note: str = ""


# introspection

@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "ok": True,
        "provider": settings.provider,
        "model": settings.model,
        "autonomy": settings.autonomy,
        "mock": settings.mock,
        "mcp_tools": len(registry.tools),
    }


@app.get("/playbooks")
async def list_playbooks() -> dict[str, Any]:
    return {
        "playbooks": [
            {
                "name": p.name,
                "description": p.description,
                "required_inputs": p.required_inputs,
                "tools": p.allowed_tools,
            }
            for p in playbooks.PLAYBOOKS.values()
        ]
    }


@app.get("/tools")
async def list_tools() -> dict[str, Any]:
    from .policy import tier_of

    return {
        "tools": [
            {"name": t["name"], "tier": tier_of(t["name"]), "description": t["description"]}
            for t in registry.tools
        ]
    }


# runs

@app.post("/runs", dependencies=[Depends(require_token)])
async def create_run(req: RunRequest) -> dict[str, Any]:
    eng = _engine()
    try:
        playbooks.get(req.playbook)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if req.wait:
        try:
            run = await eng.start(req.playbook, req.inputs, req.autonomy)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return run.public()

    # Fire-and-forget: n8n gets an id immediately and is called back on the
    # approval webhook when the run needs a human or finishes.
    run = run_store.create(req.playbook, req.inputs, req.autonomy or settings.autonomy)
    asyncio.create_task(_background(eng, req, run.id))
    return run.public()


async def _background(eng: AgentEngine, req: RunRequest, placeholder_id: str) -> None:
    try:
        await eng.start(req.playbook, req.inputs, req.autonomy)
    except Exception:
        log.exception("background run failed (placeholder %s)", placeholder_id)


@app.get("/runs", dependencies=[Depends(require_token)])
async def list_runs(limit: int = 50) -> dict[str, Any]:
    return {"runs": run_store.list(limit)}


@app.get("/usage", dependencies=[Depends(require_token)])
async def usage() -> dict[str, Any]:
    """Token use across all runs. Set the DEVFLOW_*_PRICE_PER_MTOK variables for a cost estimate."""
    return run_store.usage_summary(settings.input_price_per_mtok, settings.output_price_per_mtok)


@app.get("/runs/{run_id}", dependencies=[Depends(require_token)])
async def get_run(run_id: str) -> dict[str, Any]:
    run = run_store.load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="no such run")
    return run.public()


@app.get("/runs/{run_id}/audit", dependencies=[Depends(require_token)])
async def get_audit(run_id: str) -> dict[str, Any]:
    run = run_store.load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="no such run")
    return {"run_id": run_id, "events": run.events}


@app.post("/runs/{run_id}/approve", dependencies=[Depends(require_token)])
async def approve(run_id: str, req: ApprovalRequest) -> dict[str, Any]:
    eng = _engine()
    run = run_store.load(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="no such run")
    if run.status != STATUS_AWAITING_APPROVAL:
        raise HTTPException(
            status_code=409,
            detail="run is '{}', not awaiting approval".format(run.status),
        )

    pending_ids = [a["tool_use_id"] for a in (run.pending or {}).get("approvals", [])]
    if req.approve_all and req.reject_all:
        raise HTTPException(status_code=422, detail="pick approve_all or reject_all")
    if req.approve_all:
        decisions = {i: True for i in pending_ids}
    elif req.reject_all:
        decisions = {i: False for i in pending_ids}
    else:
        decisions = req.decisions

    unknown = set(decisions) - set(pending_ids)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail="unknown tool_use_id(s): " + ", ".join(sorted(unknown)),
        )

    run = await eng.resume(run, decisions, reviewer=req.reviewer, note=req.note)
    return run.public()


# trigger adapters: thin mappings from webhook payloads to playbook runs

class GitHubIssueEvent(BaseModel):
    repo: str
    number: int
    jira_project: str = "ENG"


class GitHubPREvent(BaseModel):
    repo: str
    number: int


class JiraEvent(BaseModel):
    jira_key: str
    repo: str
    branch: str | None = None


@app.post("/triggers/github-issue", dependencies=[Depends(require_token)])
async def trigger_issue(evt: GitHubIssueEvent) -> dict[str, Any]:
    run = await _engine().start("issue_triage", evt.model_dump())
    return run.public()


@app.post("/triggers/github-pr", dependencies=[Depends(require_token)])
async def trigger_pr(evt: GitHubPREvent) -> dict[str, Any]:
    run = await _engine().start("review_pr", evt.model_dump())
    return run.public()


@app.post("/triggers/jira-ticket", dependencies=[Depends(require_token)])
async def trigger_jira(evt: JiraEvent) -> dict[str, Any]:
    inputs = {k: v for k, v in evt.model_dump().items() if v is not None}
    run = await _engine().start("implement_ticket", inputs)
    return run.public()
