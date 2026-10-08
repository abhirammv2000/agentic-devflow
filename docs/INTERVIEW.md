# Interview notes

The questions I expect about DevFlow, with the answers tied to code and to what I measured. Where something is not done or not measured, it says so.

## What is it, in two sentences?

An agent that triages issues, turns Jira tickets into pull requests, reviews diffs and updates docs. Every tool call is classed by how much damage it can do, and anything above the allowed level pauses the run, saves it, and waits for a person.

## Why is the agent loop written by hand?

A run has to stop in the middle of a turn, be saved, and be resumed by a different HTTP request an hour later when someone clicks approve. An SDK tool runner keeps its loop in memory for one call. So the engine (`orchestrator/engine.py`) owns the loop, and the whole conversation, pending calls included, is written to disk after every step (`store.py`). The cost is that I own every edge case, which is what most of the tests cover.

## How do you decide what the agent may do on its own?

Four tiers: `read`, `write`, `publish`, `critical`. Three levels: `supervised` runs reads, `semi` runs reads and writes, `autonomous` also runs publishes. Merging always needs a person and is not configurable, because an autonomy setting is one `.env` edit away. A tool nobody classified counts as `critical`, so adding an MCP server cannot quietly widen what runs unattended. If the model proposes five calls at once and one needs approval, none run until the decision comes back.

## How do you handle prompt injection?

I do not rely on the model resisting. A local 7B model was fooled 6 times out of 6 in my eval, so that would protect nothing. Two layers:

- Output of read tools is wrapped in a tag and the model is told it is data. This lowers the odds. It proves nothing.
- A taint rule in the policy: once a run has read any outside text (an issue, a ticket, a file, test output), publishing needs a person even at `autonomous`. An injected "post this comment" cannot go out unattended.

Measured, 3 runs per case, so the intervals are wide: at `autonomous` with the rule on, the attacker's comment ran 0 of 3. With it off, 3 of 3. There is also an end-to-end test with a scripted fully-fooled model against the real MCP servers and the mock GitHub. The cost of the rule: at `autonomous`, almost every publish waits for a person, so `autonomous` is close to `semi` for publishing. That is the honest trade.

## What does the approval link protect against?

The reviewer's card links to a public n8n webhook. Without a signature, anyone who guessed a run id could approve an action. Each link now carries an HMAC-SHA256 token over the run id, the decision, the exact set of calls waiting, and an expiry (`orchestrator/signing.py`). So an approve token cannot reject, a token for one pause cannot be replayed on a later pause, and an old link stops working. Tokens are compared in constant time. What it does not stop: someone who holds a valid link can use it until it expires, and a chat app that previews links would count as a click. The fix for that is a confirm page, which I have not built.

## What happens when the model repeats itself?

A local 7B model labelled the same issue five times and never reached the comment. The engine now refuses a call that is identical to one that already worked, tells the model, and stops the run after three refusals. It means a comment can never be posted twice. Reads are allowed again after any change, so re-reading a file after an edit and re-running tests after a fix still work. A failed call can be retried. After the guard the 7B model stops after one label, which cut the run from 6 tool calls to 2. It still does not pass the triage case, because it cannot do five steps in order.

## How do you evaluate an agent like this?

Grade the audit trail, not the model's summary (`evals/`). For ordinary triage: did it read first, label, search before creating a ticket, comment after the ticket exists, with no denied or failed calls. For the planted-instruction issue: did the model ask for the attacker's action, and did it actually run. Those are separate numbers because the first is the model being fooled and the second is damage. The graders are tested on hand-made trails before any model is involved. It refuses to save a run where the provider failed. So far it has run on one local 7B model only.

## How do you watch it in production?

`/metrics` has runs by playbook and status, what the policy decided for every tool, approvals, repeated calls refused, taint escalations, tokens and run time. Each run is a trace with a span per model turn and per tool. Neither carries issue, file or tool text, and a test checks that. Runs also stop at a token budget, and starting runs is rate limited. Per process, so not for several instances.

## Why MCP?

The tools are MCP servers (GitHub, Jira, the working copy) launched over stdio, so the engine knows nothing about GitHub. The model sits behind a provider interface, so swapping Claude for a local model is a config change. A side benefit: a new MCP server's tools are untrusted by default because unclassified tools count as `critical`.

## What is not done

- Only GitHub has run live. Jira has run only against the mock.
- The test runner is limited by an allow-list, not a real sandbox.
- Run state is JSON files, fine for one process.
- No semantic cache and no RAG. The agent searches code with plain text search, and nothing here would benefit from a cache.
- The evals have not run on a strong model.
