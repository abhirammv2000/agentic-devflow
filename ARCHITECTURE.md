# Design notes

Why the pieces are arranged the way they are. Read
[README.md](README.md) first for what the thing does.

## The split: n8n owns workflow, the orchestrator owns the agent

It would be simpler to put everything in one Python service, or to build the
whole agent inside n8n's AI Agent node. Neither survives contact with the actual
requirement.

n8n is good at what it is good at: webhooks from a dozen SaaS products, retries,
credential storage, and a visual surface a non-engineer can rewire. The approval
step is a *workflow* concern — which channel, which reviewers, what the card
looks like, what happens on timeout. Every team wants that different, and none
of them should need to edit Python to get it.

The agent loop is the opposite: it needs precise control over tool dispatch,
policy evaluation, message history and persistence. Expressed as n8n nodes it
becomes an unreadable graph, and the policy — the safety-critical part — ends up
scattered across node parameters where it cannot be unit tested.

So the boundary is HTTP, and it falls where the concerns actually separate.

## Why MCP rather than direct API calls

The orchestrator never imports the GitHub or Jira code. It knows only that
servers exist and advertise tools ([mcp_registry.py](orchestrator/mcp_registry.py)).

That buys three things:

- **Substitutability.** Point `settings.mcp_servers` at a vendor's GitHub MCP
  server and nothing in the engine changes.
- **A real process boundary.** Tool code runs in its own process over stdio. The
  workspace server can be given a different filesystem view, or a container,
  without restructuring anything.
- **Uniform introspection.** Tool schemas arrive from the servers, so `/tools`
  and the policy table describe whatever is actually loaded, not a hardcoded list.

The cost is three extra processes and a startup handshake. For a prototype
that's an easy trade.

## Why a manual agent loop instead of the SDK tool runner

The SDK's `tool_runner` is the right default and the docs say so. This is the
documented exception.

A run must be able to stop mid-turn, persist, and be resumed **by a different
HTTP request** — possibly an hour later, possibly a different process — once a
human clicks approve. The tool runner's loop lives in memory for the duration of
one call. Gating inside the tool function would mean blocking a worker for the
length of a human's lunch break.

So [engine.py](orchestrator/engine.py) drives `messages.stream` itself and
serialises the entire conversation — including the pending `tool_use` blocks —
to disk after every step. Resumption reconstitutes it and continues.

The consequence worth knowing: thinking blocks are echoed back verbatim via
`model_dump(mode="json", exclude_none=True)`. They carry signatures the API
validates, so they must round-trip through JSON unmodified.

## Why a gated call parks the entire turn

When the model proposes several tool calls in one turn, the tempting
optimisation is to execute the auto-approved ones immediately and only wait on
the gated one. That is wrong.

A turn is a unit of intent. "Create the Jira ticket **and** comment the key on
the issue" is one plan; executing half of it while a human considers the other
half produces states the model never reasoned about — an issue comment
referencing a ticket that was ultimately rejected. So nothing in a turn executes
until every decision in it is resolved, and rejections come back as error tool
results that let the model adapt its plan.

## Why `critical` has no autonomy level that clears it

`AUTO_CEILING` maps autonomy levels to tiers, and it would be trivially
consistent to let `autonomous` clear `critical` too. It deliberately doesn't.

Autonomy is an environment variable. Environment variables get copied between
deployments, set to the permissive value during a demo, and forgotten. The set
of actions that are irreversible is small and known; keeping a hard floor under
it means the blast radius of a misconfigured `.env` is bounded by something
other than hope.

Same reasoning behind unknown tools resolving to `critical`: adding an MCP
server should never silently widen what runs unattended.

## Where the trust boundaries actually are

The tier system is a policy layer, not a sandbox. It constrains what the *model*
can do through tools it was given. It does nothing about:

- a compromised MCP server (they run as your user)
- a malicious test file in the working copy (`repo_run_tests` allow-lists the
  executable and disables shell interpretation, but the code it runs is code)
- anyone who can reach the approve URL

Those need process isolation, a container, and webhook authentication
respectively — listed in the README's limits section rather than pretended away
here.

## Testing strategy

Three layers, none of which call the model:

- **[test_policy.py](tests/test_policy.py)** — the decision matrix, the critical
  floor, fail-closed behaviour, and a check that every tool named by a playbook
  has a classification. That last one catches the failure mode where someone
  adds a tool and it silently becomes `critical` at runtime.
- **[test_engine.py](tests/test_engine.py)** — the loop, with the model replaced
  by a scripted sequence of responses and MCP by a recording stub. Suspension,
  resumption, rejection, unanswered approvals, partial-turn safety, iteration caps.
- **[test_mcp_tools.py](tests/test_mcp_tools.py)** / **[test_api.py](tests/test_api.py)**
  — the tool implementations against a temp store, and the real FastAPI app with
  all three MCP servers actually spawned.

`scripts/smoke_test.py` sits alongside them: it drives a complete
ticket → branch → commit → PR → review sequence through the live MCP layer and
prints what the current autonomy setting would gate. It is the fastest way to
confirm a change did not quietly widen the tool surface.

What none of this covers is the model's actual behaviour — whether the prompts
produce good triage decisions or correct patches. That needs an API key, real
runs, and an eval set, and it is the obvious next thing to build.
