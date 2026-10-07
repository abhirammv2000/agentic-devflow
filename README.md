# DevFlow

A semi-autonomous developer agent. It triages issues, turns Jira tickets into tested pull requests, reviews diffs and keeps docs up to date. n8n handles the triggers and the human approvals, MCP provides the tools, and the model can be Claude or any open-weight model you serve yourself.

The part I cared about is the word "semi". Every tool call is classified by how much damage it can do, and anything above the configured level pauses the run, saves it, and waits for a person.

```
webhook (GitHub / Jira)
        |
      [ n8n ] --POST /runs--> [ orchestrator: agent loop + policy ] --stdio--> [ MCP servers ]
        |                                  ^                                    github, jira, repo
        v                                  |
  approval card --- human clicks ---  POST /runs/{id}/approve
```

## Quick start

No GitHub token, Jira account or n8n needed. The tools ship with a mock backend.

```bash
python -m venv .venv && .venv/Scripts/activate     # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                               # set ANTHROPIC_API_KEY

python scripts/smoke_test.py                       # no model calls, checks MCP and policy
python -m pytest -q                                # 65 tests

python scripts/demo.py issue_triage --repo acme/checkout-service --number 41
```

When the agent reaches a gated action it stops and asks:

```
PAUSED: 1 action(s) need a human

  tool   : jira_create_issue
  tier   : publish
  why    : 'publish' tier exceeds the 'semi' autonomy ceiling ('write')
  approve? [y/N]
```

Run `python scripts/reset_demo.py` to reset the mock data between runs.

## Playbooks

Each playbook is a system prompt plus a fixed list of tools it may use ([playbooks.py](orchestrator/playbooks.py)). The triage playbook cannot open a pull request at any autonomy level.

| Playbook | Trigger | What it does | Tools |
|---|---|---|---|
| `issue_triage` | issue opened | classify, label, create or dedupe the Jira ticket, comment back | 10 |
| `implement_ticket` | ticket labelled `ai-assist` | find the bug, fix it, add a regression test, run the suite, open a PR | 18 |
| `review_pr` | PR opened or pushed | read the diff, post one review (never `APPROVE`) | 10 |
| `document_change` | PR merged | rewrite only the doc sections the change made wrong | 13 |

## Autonomy policy

Four risk tiers and three autonomy levels ([policy.py](orchestrator/policy.py)):

| Tier | Examples | `supervised` | `semi` (default) | `autonomous` |
|---|---|---|---|---|
| `read` | `gh_get_issue`, `repo_search` | auto | auto | auto |
| `write` | `gh_create_branch`, `repo_write_file` | ask | auto | auto |
| `publish` | `gh_open_pull_request`, `jira_create_issue` | ask | ask | auto |
| `critical` | `gh_merge_pull_request` | ask | ask | ask |

- Merging always needs a human, whatever the level. It is not configurable.
- A tool nobody classified is treated as `critical`, so adding an MCP server cannot quietly widen what runs unattended.
- If the model proposes five calls at once and one needs approval, none of them run until the decision comes back.

All three are covered by tests. [ARCHITECTURE.md](ARCHITECTURE.md) explains why the agent loop is hand-written instead of using an SDK tool runner.

## Models

Pick a backend with an environment variable. The engine never imports a vendor SDK.

```bash
DEVFLOW_PROVIDER=anthropic  DEVFLOW_MODEL=claude-opus-5  ANTHROPIC_API_KEY=...
DEVFLOW_PROVIDER=ollama     DEVFLOW_MODEL=qwen3:32b          # or any OpenAI-compatible server
```

What has actually been run:

- **Claude, live:** `review_pr` against [a real sandbox pull request](https://github.com/abhirammv2000/devflow-sandbox/pull/1). It found the planted double-charge bug and two smaller defects. It also hit something the mock never showed: GitHub rejects `APPROVE` on your own PR with a 422, so the tool now falls back to a plain comment.
- **A local 7B model:** `issue_triage` completed end to end on `qwen2.5-coder:7b` through Ollama, and the approval gate held. Across two runs it rated the same bug sev2 once and sev1 once, so a small model works mechanically but not reliably.

## Usage and cost

Every run records its input and output tokens. `GET /usage` (with the `X-Devflow-Token` header) adds them up overall and per playbook. Set `DEVFLOW_INPUT_PRICE_PER_MTOK` and `DEVFLOW_OUTPUT_PRICE_PER_MTOK` (dollars per million tokens, from your provider's price list) to get an estimated cost. Without them the cost shows as `null`, because the right price depends on the model you use. Calls to a local model have no cost, only tokens.

The API checks `X-Devflow-Token` against `DEVFLOW_SERVICE_TOKEN`. The default token is public, and the service logs a warning at startup until you set your own.

## Running with n8n

```bash
docker compose up --build          # orchestrator on :8088, n8n on :5678
```

Import the four workflows from [n8n/workflows/](n8n/workflows/). [n8n/README.md](n8n/README.md) lists the webhook URLs and settings. Workflow 04 is the approval gate: it sends the reviewer a card with approve and reject links, and the click resumes the saved run.

For live GitHub and Jira, set `DEVFLOW_MOCK=0` with `GITHUB_TOKEN` and `JIRA_*` credentials.

## Layout

```
mcp_servers/       GitHub, Jira and sandboxed working-copy MCP servers
orchestrator/      policy.py (risk tiers), engine.py (agent loop), providers/, playbooks.py, store.py, app.py
n8n/workflows/     four importable workflows
sandbox/demo-repo/ small repo for the agent to work on
scripts/           demo CLI, smoke test, reset
```

## Limits

- Run state is stored as JSON files, which is fine for one process and not for several.
- Only GitHub has been run live. Jira has only been run against the mock backend.
- The test runner is limited by an allow-list, not a real sandbox. Put it in a container before pointing it at code you don't trust.
- The approve and reject links in workflow 04 are unauthenticated.
- The 65 tests check the loop, policy, MCP layer, HTTP contract and both model formats. Nothing yet measures whether the agent's decisions are good.
