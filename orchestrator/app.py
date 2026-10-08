"""HTTP API that the n8n workflows call.

n8n handles triggers, notifications and the human approval step. This service runs the
agent loop, the tools and the audit trail. Approval sits in n8n so that someone who isn't
an engineer can change it without touching Python.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from urllib.parse import parse_qs
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, Field

from . import decide_page, playbooks, signing, telemetry
from .config import settings
from .engine import AgentEngine
from .mcp_registry import registry
from .ratelimit import RateLimiter
from .store import STATUS_AWAITING_APPROVAL, RunStore

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("devflow.api")

run_store = RunStore()
engine: AgentEngine | None = None
run_limiter = RateLimiter(lambda: settings.runs_per_minute)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global engine
    telemetry.configure()
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


def limit_runs() -> None:
    wait = run_limiter.check()
    if wait is not None:
        raise HTTPException(
            status_code=429,
            detail="too many runs started in the last minute",
            headers={"Retry-After": str(wait)},
        )


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
    # "link" means the click came through the public approval link, which is not authenticated by itself,
    # so the signed token is required. "api" is a caller that already holds the service token.
    source: Literal["api", "link"] = "api"
    token: str | None = None
    expires: int | None = None


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

@app.post("/runs", dependencies=[Depends(require_token), Depends(limit_runs)])
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


@app.get("/metrics", dependencies=[Depends(require_token)])
async def metrics() -> Response:
    """Prometheus metrics: runs, tool decisions, approvals, tokens and run time. Never any issue or file text."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


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

    if req.source == "link":
        if req.approve_all == req.reject_all:
            raise HTTPException(status_code=422, detail="an approval link is all or nothing")
        reason = signing.check_link_token(
            settings.approval_secret or settings.service_token,
            run_id,
            "approve" if req.approve_all else "reject",
            pending_ids,
            req.expires,
            req.token,
        )
        if reason:
            log.warning("approval link refused for %s: %s", run_id, reason)
            raise HTTPException(status_code=403, detail="invalid or expired approval link")

    unknown = set(decisions) - set(pending_ids)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail="unknown tool_use_id(s): " + ", ".join(sorted(unknown)),
        )

    run = await eng.resume(run, decisions, reviewer=req.reviewer, note=req.note)
    return run.public()


# the confirm page behind the approve and reject links. These routes have no service token, because the
# reviewer who opens them does not have one. The signed token in the link is what authorises them.

def _page(html: str, status_code: int = 200) -> HTMLResponse:
    return HTMLResponse(html, status_code=status_code, headers=decide_page.SECURITY_HEADERS)


def _link_problem(run, decision: str, token: str, expires: int | None) -> tuple[int, str] | None:
    """A (status, message) if this link cannot be used, else None. The message is the same for a missing run, a
    run that is not waiting and a bad token, so a page cannot be used to find out which run ids exist."""
    unusable = (404, "This link is no longer valid. The run may have been decided already, or the link has expired.")
    if decision not in ("approve", "reject") or run is None or run.status != STATUS_AWAITING_APPROVAL:
        return unusable
    pending_ids = [a["tool_use_id"] for a in (run.pending or {}).get("approvals", [])]
    reason = signing.check_link_token(settings.approval_secret or settings.service_token, run.id, decision,
                                      pending_ids, expires, token)
    if reason:
        log.warning("decision page refused for %s: %s", run.id, reason)
        return unusable
    return None


@app.get("/decide/{run_id}", response_class=HTMLResponse)
async def decide_page_get(run_id: str, decision: str = "approve", token: str = "", expires: int | None = None):
    """Show what is waiting and a button. Deciding happens on POST, so a link preview cannot approve anything."""
    run = run_store.load(run_id)
    problem = _link_problem(run, decision, token, expires)
    if problem:
        return _page(decide_page.message("Link not valid", problem[1]), problem[0])
    return _page(decide_page.confirm(run.public(), decision, token, expires))


@app.post("/decide/{run_id}", response_class=HTMLResponse)
async def decide_page_post(run_id: str, request: Request):
    raw = await request.body()
    if len(raw) > 4096:
        return _page(decide_page.message("Too large", "That request is too large."), 413)
    form = {k: v[0] for k, v in parse_qs(raw.decode("utf-8", errors="replace")).items()}
    decision = form.get("decision", "")
    try:
        expires = int(form.get("expires", ""))
    except ValueError:
        expires = None
    run = run_store.load(run_id)
    problem = _link_problem(run, decision, form.get("token", ""), expires)
    if problem:
        return _page(decide_page.message("Link not valid", problem[1]), problem[0])

    reviewer = (form.get("reviewer", "").strip()[:60]) or "link-click"
    req = ApprovalRequest(approve_all=decision == "approve", reject_all=decision == "reject", reviewer=reviewer,
                          source="link", token=form.get("token"), expires=expires)
    try:
        result = await approve(run_id, req)
    except HTTPException as exc:
        return _page(decide_page.message("Not recorded", str(exc.detail)), exc.status_code)
    return _page(decide_page.done(result))


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


@app.post("/triggers/github-issue", dependencies=[Depends(require_token), Depends(limit_runs)])
async def trigger_issue(evt: GitHubIssueEvent) -> dict[str, Any]:
    run = await _engine().start("issue_triage", evt.model_dump())
    return run.public()


@app.post("/triggers/github-pr", dependencies=[Depends(require_token), Depends(limit_runs)])
async def trigger_pr(evt: GitHubPREvent) -> dict[str, Any]:
    run = await _engine().start("review_pr", evt.model_dump())
    return run.public()


@app.post("/triggers/jira-ticket", dependencies=[Depends(require_token), Depends(limit_runs)])
async def trigger_jira(evt: JiraEvent) -> dict[str, Any]:
    inputs = {k: v for k, v in evt.model_dump().items() if v is not None}
    run = await _engine().start("implement_ticket", inputs)
    return run.public()
