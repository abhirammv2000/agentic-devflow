# The n8n side

Four workflows. Three are triggers; the fourth is the human approval gate, and
it is the one that earns the "semi" in semi-autonomous.

| File | Trigger path | Playbook |
|---|---|---|
| `01-github-issue-triage.json` | `POST /webhook/github-issue-opened` | `issue_triage` |
| `02-jira-to-pull-request.json` | `POST /webhook/jira-ticket-ready` | `implement_ticket` |
| `03-pull-request-review.json` | `POST /webhook/github-pr-event` | `review_pr` |
| `04-human-approval-gate.json` | `POST /webhook/devflow-approval-request` (from the orchestrator)<br>`GET /webhook/devflow-approve` (reviewer's click) | none |

## Import

```bash
docker compose up --build
```

Open <http://localhost:5678>, then for each file: **Workflows > Import from
File**, pick it from `n8n/workflows/`, and activate it. (The compose file also
mounts them read-only at `/workflows` inside the container if you prefer the
CLI: `n8n import:workflow --separate --input=/workflows`.)

Activate **04 first**, because the other three are useless if nobody can approve what
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
| `DEVFLOW_APPROVAL_SECRET` | signs the approve and reject links (orchestrator side) | falls back to the service token |
| `DEVFLOW_PUBLIC_URL` | where reviewers reach the orchestrator, for the confirm page links | empty (links go to the n8n webhook) |
| `DEVFLOW_ALERT_WEBHOOK` | Slack/Teams incoming webhook for cards and alerts | orchestrator healthz (a harmless no-op) |
| `DEVFLOW_DEFAULT_REPO` | repo the Jira workflow targets | `acme/checkout-service` |
| `DEVFLOW_JIRA_PROJECT` | project key triage files tickets into | `ENG` |

Set `DEVFLOW_ALERT_WEBHOOK` to a real Slack incoming webhook to see approval
cards arrive; leave it as the default and the notification step just succeeds
against a healthz endpoint so the rest of the flow still works.

## How the approval round trip works

1. The agent proposes a `publish`- or `critical`-tier action.
2. The orchestrator parks the run (nothing executes), writes it to disk, and
   `POST`s `run.approval_required` to workflow **04**.
3. **04** renders a card listing each pending tool, its tier, the policy reason,
   and the exact arguments, plus an approve and a reject link.
4. The reviewer clicks. `GET /webhook/devflow-approve?run_id=…&decision=…` hits
   **04**'s second trigger, which calls
   `POST {DEVFLOW_URL}/runs/{run_id}/approve`.
5. The orchestrator resumes the parked run inside that request. The response is
   the run's *final* state, which is why that node's timeout is 30 minutes.

Because the run lives on disk rather than in n8n's memory, the gap in steps 3 to 4
can be an hour and nothing is lost. It also means you can swap the whole
notification mechanism (Slack buttons, an email, a Jira transition, a PR
comment) without touching Python.

## Pointing real webhooks at it

**GitHub**: repo Settings > Webhooks > add
`https://<your-n8n>/webhook/github-issue-opened` (Issues events) and
`https://<your-n8n>/webhook/github-pr-event` (Pull requests). The workflows
already filter on `action`, drafts, and bot authorship.

**Jira**: Settings > System > WebHooks > add
`https://<your-n8n>/webhook/jira-ticket-ready` on issue created/updated.
Workflow 02 only proceeds for tickets carrying the `ai-assist` label.

## Before this touches a real repo

- The approve/reject links are signed. The orchestrator puts a token in the
  callback, the card carries it in each link, and the orchestrator refuses a
  click without a valid one (`orchestrator/signing.py`). A token is tied to one
  run, one decision (approve or reject), the exact calls waiting, and an expiry
  (`DEVFLOW_APPROVAL_TTL_SECONDS`, default one hour). Set
  `DEVFLOW_APPROVAL_SECRET`, or it falls back to the service token. Anyone who
  has the URL can still use it until it expires, so send cards only to the
  people who may approve. Some chat apps fetch a link to show a preview, and
  against the n8n webhook that fetch would count as a click. Set
  `DEVFLOW_PUBLIC_URL` to where reviewers can reach the orchestrator and the
  card links to its confirm page instead (`/decide/...`). Opening that link only
  shows what is waiting and a button, and the decision happens when the button
  is pressed, so a preview cannot approve anything. The page escapes everything
  a model or tool wrote, forbids scripts and framing, and gives the same answer
  for a missing run, a decided run and a bad token.
- Give the agent a GitHub token scoped to one repo, and a Jira account whose
  permissions match the tools in `policy.py`. The tiers are a second line of
  defence, not the first one.
- Verify GitHub's `X-Hub-Signature-256` in the webhook node; right now the
  workflows trust the payload.
