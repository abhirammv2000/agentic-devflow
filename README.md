# DevFlow — a semi-autonomous agentic developer workflow

A working prototype of an agent that does real engineering chores — triaging
issues, turning tickets into tested pull requests, reviewing diffs, keeping docs
honest — where **n8n** owns the triggers and the human approvals, **MCP** owns
the tool layer, and any tool-calling LLM owns the reasoning: Claude, or an
open-weights model served locally.

The interesting part is not that an agent can call the GitHub API. It is the
word *semi*: every action is classified by blast radius, and anything past the
configured line stops the run mid-turn, persists it, and waits for a person.

```
GitHub / Jira webhook
        │
        ▼
    ┌───────┐   POST /runs        ┌──────────────┐   stdio    ┌─────────────┐
    │  n8n  │────────────────────▶│ orchestrator │───────────▶│ MCP servers │
    │       │◀────────────────────│  (agent loop)│◀───────────│ gh/jira/repo│
    └───────┘  run.approval_...   └──────────────┘            └─────────────┘
        │                                 ▲
        ▼  Slack card, approve/reject     │
     a human ─────────────────────────────┘  POST /runs/{id}/approve
```

## Run it in two minutes

No GitHub token, Jira account, or n8n instance is needed — the tool layer ships
with a mock backend seeded with a real-looking bug.

```bash
python -m venv .venv && .venv/Scripts/activate     # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                               # then set ANTHROPIC_API_KEY

python scripts/smoke_test.py                       # no model calls — checks MCP + policy
python -m pytest -q                                # 55 tests

python scripts/demo.py issue_triage --repo acme/checkout-service --number 41
```

`demo.py` runs the same engine the n8n workflows drive; only the approval
transport differs (a stdin prompt here, a Slack card there). When the agent
reaches a gated action it stops and asks:

```
PAUSED -- 1 action(s) need a human

  tool   : jira_create_issue
  tier   : publish
  why    : 'publish' tier exceeds the 'semi' autonomy ceiling ('write')
  args   : { "project": "ENG", "summary": "Retry path double-charges the card", ... }
  approve? [y/N]
```

`python scripts/reset_demo.py` restores the mock world between runs.

## The four playbooks

| Playbook | Trigger | What it does | Tools it can reach |
|---|---|---|---|
| `issue_triage` | issue opened | classify, label, open/dedupe the Jira ticket, comment back | 10 — no code, no PRs |
| `implement_ticket` | ticket labelled `ai-assist` | read the ticket, find the bug, fix it, write a regression test, run the suite, open a PR, link it back | 18 |
| `review_pr` | PR opened / pushed | read the diff in context, post one review; may not `APPROVE` | 10 — read + review only |
| `document_change` | PR merged | rewrite only the doc sections the change invalidated | 13 |

Each playbook is a system prompt plus an explicit tool allow-list
([playbooks.py](orchestrator/playbooks.py)). The narrowing is a safety
mechanism, not just prompt hygiene: the triage playbook *physically cannot*
open a pull request, at any autonomy level.

## The autonomy policy

Four tiers, three levels ([policy.py](orchestrator/policy.py)):

| Tier | Examples | `supervised` | `semi` (default) | `autonomous` |
|---|---|---|---|---|
| `read` | `gh_get_issue`, `repo_search`, `repo_run_tests` | auto | auto | auto |
| `write` | `gh_create_branch`, `gh_commit_file`, `repo_write_file` | ask | auto | auto |
| `publish` | `gh_open_pull_request`, `jira_create_issue`, review comments | ask | ask | auto |
| `critical` | `gh_merge_pull_request` | ask | ask | **ask** |

Three properties worth calling out, each covered by a test:

- **The critical floor is not configurable.** `autonomous` still stops before a
  merge. An autonomy setting is a knob someone nudges in a `.env`; "merge to
  main" should not be one nudge away.
- **Unknown tools fail closed.** A tool nobody classified is treated as
  critical, so adding an MCP server can never silently widen what runs unattended.
- **A gated call parks the whole turn.** If the model proposes five tool calls
  in parallel and one needs approval, none of the five execute until the
  decision arrives — there is no such thing as a half-applied turn.

Rejections are fed back to the model as an error tool result telling it not to
retry or route around the block, and unanswered approvals count as rejections.

## Wiring up n8n

```bash
docker compose up --build          # orchestrator :8088, n8n :5678
```

Then import the four workflows from [n8n/workflows/](n8n/workflows/) — see
[n8n/README.md](n8n/README.md) for the webhook URLs, the environment variables
each one reads, and how to point real GitHub/Jira webhooks at them.

Workflow 04 is the one that makes this semi-autonomous: the orchestrator calls
it back on `run.approval_required`, it renders an approval card with
approve/reject links, and the reviewer's click resumes the parked run.

## Choosing a model

The engine never imports a vendor SDK. Backends live behind
[providers/](orchestrator/providers/) and are chosen with one env var.

```bash
# Claude (default)
DEVFLOW_PROVIDER=anthropic  DEVFLOW_MODEL=claude-opus-5  ANTHROPIC_API_KEY=...

# any OpenAI-compatible server: Ollama, vLLM, llama.cpp, LM Studio,
# OpenRouter, Together, Groq, ...
DEVFLOW_PROVIDER=ollama  DEVFLOW_MODEL=qwen3:32b
DEVFLOW_PROVIDER=openai_compat
DEVFLOW_BASE_URL=http://localhost:8000/v1
DEVFLOW_MODEL=Qwen/Qwen3-32B
```

MCP advertises plain JSON Schema, which both dialects accept unchanged — that is
what makes the tool layer portable. What the provider absorbs is the rest of the
dialect: the `function` envelope, arguments arriving as a JSON *string*, one
`tool` message per result instead of a batch, and a different `finish_reason`
vocabulary.

**Verified against a local open model.** `issue_triage` completes end to end on
`qwen2.5-coder:7b` via Ollama — tools called, gate honoured, side effects landed:

```
proposed  gh_set_labels      tier=write    -> auto
proposed  jira_create_issue  tier=publish  -> needs_approval
EXECUTED  gh_set_labels                         <- only after the human decided
human     jira_create_issue  approved=True
EXECUTED  jira_create_issue
```

**How good the model needs to be is a separate question.** Across two runs the
7B model graded the same double-charge bug sev2 once and sev1 once — the rubric
in its own system prompt says `sev1 = money loss`, so it was inconsistent rather
than reliably wrong. It also called one tool twice with identical arguments and
hallucinated a Jira hostname into a comment it published. The plumbing was
identical both times; the judgement was not. Two samples is not an evaluation,
which is rather the point: you cannot tell a good backend from a bad one by
watching it succeed once.

Expect to need a strong tool-calling model — the playbooks expose 10–18 tools
and require multi-step planning. `review_pr` and `issue_triage` are the
forgiving ones; `implement_ticket` is the demanding one. Two failure modes the
provider handles because small models cause them routinely: arguments that are
not valid JSON (fed back as a tool error rather than crashing the run) and
`finish_reason: "stop"` reported alongside tool calls.

## Going live

Set `DEVFLOW_MOCK=0` and supply `GITHUB_TOKEN` / `JIRA_*` credentials. The MCP
tools present an identical surface to the model in both modes — mock and live
differ only below the tool boundary, so nothing about the agent's behaviour
changes when you flip it.

## Layout

```
mcp_servers/       three MCP servers: GitHub, Jira, sandboxed working copy
orchestrator/
  policy.py        risk tiers and the autonomy ceiling      <- the safety boundary
  engine.py        the suspendable agent loop (vendor-neutral)
  providers/       model backends: Claude, or any OpenAI-compatible server
  playbooks.py     the four tasks: prompt + tool surface
  store.py         durable run state (survives the human round trip)
  mcp_registry.py  stdio MCP client -> one flat tool surface
  app.py           the HTTP API n8n drives
n8n/workflows/     four importable workflows
sandbox/demo-repo/ a small buggy repo for the agent to work on
scripts/           demo CLI, smoke test, reset
```

## Notes and limits

This is a prototype, and a few things are deliberately simple:

- **Run state is JSON files** under `data/runs/`. Fine for one process; use
  Postgres or Redis if you run more than one replica.
- **Mock git history is synthetic.** `gh_commit_file` in mock mode records file
  contents and a diff rather than real commits. Live mode uses the GitHub
  contents API properly.
- **No sandboxing of the test runner beyond an allow-list.** `repo_run_tests`
  restricts the executable and blocks shell interpretation, but a malicious test
  file in the working copy still runs as your user. Put it in a container before
  pointing this at code you do not control.
- **The approve/reject links in workflow 04 are unauthenticated.** Anyone with
  the URL can approve. Add n8n webhook auth, or signed tokens, before real use.
- **Model quality is not evaluated.** The 55 tests and the smoke test cover the
  loop, the policy, the MCP layer, the HTTP contract and both provider dialects,
  but none of them judge whether the agent's decisions are *good*. That needs an
  eval set, and it is the obvious next thing to build.
- **The Claude path is structurally checked, not run.** Every request parameter
  is verified against the installed SDK, but no live Anthropic call has been
  made here — that needs an `ANTHROPIC_API_KEY`. The open-model path has been
  run for real (see above), on one playbook, once.
