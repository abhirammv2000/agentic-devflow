# The n8n side

Four workflows. Three are triggers; the fourth is the human approval gate, and
it is the one that earns the "semi" in semi-autonomous.

| File | Trigger path | Playbook |
|---|---|---|
| `01-github-issue-triage.json` | `POST /webhook/github-issue-opened` | `issue_triage` |
| `02-jira-to-pull-request.json` | `POST /webhook/jira-ticket-ready` | `implement_ticket` |
| `03-pull-request-review.json` | `POST /webhook/github-pr-event` | `review_pr` |
| `04-human-approval-gate.json` | `POST /webhook/devflow-approval-request` (from the orchestrator)<br>`GET /webhook/devflow-approve` (reviewer's click) | — |

## Import

```bash
docker compose up --build
```

Open <http://localhost:5678>, then for each file: **Workflows → Import from
File**, pick it from `n8n/workflows/`, and activate it. (The compose file also
mounts them read-only at `/workflows` inside the container if you prefer the
CLI: `n8n import:workflow --separate --input=/workflows`.)

Activate **04 first** — the other three are useless if nobody can approve what
they park.

## Environment

Workflows read these via `$env.*`; docker-compose passes them to the n8n
container already. Note `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` is what makes
`$env` readable from expressions at all.

| Variable | Purpose | Default in compose |
|---|---|---|
| `DEVFLOW_URL` | where the orchestrator lives | `http://orchestrator:8088` |
| `DEVFLOW_SERVICE_TOKEN` | sent as `X-Devflow-Token` on every call | `dev-local-token` |
| `N8N_PUBLIC_URL` | base for the approve/reject links in the card | `http://localhost:5678` |
| `DEVFLOW_ALERT_WEBHOOK` | Slack/Teams incoming webhook for cards and alerts | orchestrator healthz (a harmless no-op) |
| `DEVFLOW_DEFAULT_REPO` | repo the Jira workflow targets | `acme/checkout-service` |
| `DEVFLOW_JIRA_PROJECT` | project key triage files tickets into | `ENG` |

Set `DEVFLOW_ALERT_WEBHOOK` to a real Slack incoming webhook to see approval
cards arrive; leave it as the default and the notification step just succeeds
against a healthz endpoint so the rest of the flow still works.

## How the approval round trip works

1. The agent proposes a `publish`- or `critical`-tier action.
2. The orchestrator parks the run — nothing executes — writes it to disk, and
   `POST`s `run.approval_required` to workflow **04**.
3. **04** renders a card listing each pending tool, its tier, the policy reason,
   and the exact arguments, plus an approve and a reject link.
4. The reviewer clicks. `GET /webhook/devflow-approve?run_id=…&decision=…` hits
   **04**'s second trigger, which calls
   `POST {DEVFLOW_URL}/runs/{run_id}/approve`.
5. The orchestrator resumes the parked run inside that request. The response is
   the run's *final* state, which is why that node's timeout is 30 minutes.

Because the run lives on disk rather than in n8n's memory, the gap in step 3–4
can be an hour and nothing is lost. It also means you can swap the whole
notification mechanism — Slack buttons, an email, a Jira transition, a PR
comment — without touching Python.

## Pointing real webhooks at it

**GitHub** → repo Settings → Webhooks → add
`https://<your-n8n>/webhook/github-issue-opened` (Issues events) and
`https://<your-n8n>/webhook/github-pr-event` (Pull requests). The workflows
already filter on `action`, drafts, and bot authorship.

**Jira** → Settings → System → WebHooks → add
`https://<your-n8n>/webhook/jira-ticket-ready` on issue created/updated.
Workflow 02 only proceeds for tickets carrying the `ai-assist` label.

## Before this touches a real repo

- The approve/reject links are **unauthenticated** — anyone with the URL can
  approve a merge. Add n8n webhook auth (header or basic) and put the
  orchestrator behind the same boundary.
- Give the agent a GitHub token scoped to one repo, and a Jira account whose
  permissions match the tools in `policy.py` — the tiers are a second line of
  defence, not the first one.
- Verify GitHub's `X-Hub-Signature-256` in the webhook node; right now the
  workflows trust the payload.
