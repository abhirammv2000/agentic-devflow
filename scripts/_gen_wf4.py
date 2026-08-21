"""Generates n8n/workflows/04-human-approval-gate.json (kept as a generator so the
embedded JavaScript stays readable instead of being escaped by hand)."""

import json
import pathlib

JS_CARD = r"""
// Turn a run.approval_required callback into a reviewer-facing approval card.
const run = $input.first().json;

if (run.event !== 'run.approval_required') {
  return [{ json: { skipped: true, event: run.event, run_id: run.run_id } }];
}

const base = ($env.N8N_PUBLIC_URL || 'http://localhost:5678').replace(/\/$/, '');
const approveUrl = base + '/webhook/devflow-approve?run_id=' + run.run_id + '&decision=approve';
const rejectUrl  = base + '/webhook/devflow-approve?run_id=' + run.run_id + '&decision=reject';

const lines = run.pending_approvals.map((a) =>
  '- *' + a.tool + '*  (' + a.tier + ')\n' +
  '   ' + a.reason + '\n' +
  '```' + a.arguments + '```'
);

const text = [
  'DevFlow needs a decision on run `' + run.run_id + '` (' + run.playbook + ')',
  '',
  run.summary || '(no interim summary)',
  '',
  'Pending actions:',
  lines.join('\n'),
  '',
  'Approve: ' + approveUrl,
  'Reject:  ' + rejectUrl,
].join('\n');

return [{ json: { skipped: false, run_id: run.run_id, playbook: run.playbook, text: text, approveUrl: approveUrl, rejectUrl: rejectUrl } }];
""".strip()

JS_RESULT = r"""
// Render the orchestrator's response as a plain confirmation page.
const r = $input.first().json;
const html = [
  '<!doctype html><meta charset="utf-8">',
  '<title>DevFlow decision recorded</title>',
  '<body style="font:16px/1.5 system-ui;margin:3rem auto;max-width:44rem">',
  '<h1>Decision recorded</h1>',
  '<p>Run <code>' + r.run_id + '</code> is now <strong>' + r.status + '</strong>.</p>',
  '<pre style="white-space:pre-wrap;background:#f4f4f5;padding:1rem;border-radius:8px">' +
    (r.summary || '') + '</pre>',
  '</body>',
].join('');
return [{ json: { html: html } }];
""".strip()

ORCH = "$env.DEVFLOW_URL || 'http://orchestrator:8088'"
TOKEN = "={{ $env.DEVFLOW_SERVICE_TOKEN }}"

workflow = {
    "name": "DevFlow · 04 · Human approval gate",
    "nodes": [
        {
            "parameters": {
                "httpMethod": "POST",
                "path": "devflow-approval-request",
                "responseMode": "responseNode",
                "options": {},
            },
            "id": "wf4-callback",
            "name": "Orchestrator callback",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-400, -160],
            "webhookId": "devflow-approval-request",
            "notes": "The orchestrator POSTs here whenever a run parks on a gated action.",
            "notesInFlow": True,
        },
        {
            "parameters": {"jsCode": JS_CARD},
            "id": "wf4-card",
            "name": "Build approval card",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [-160, -160],
        },
        {
            "parameters": {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "loose",
                        "version": 2,
                    },
                    "conditions": [
                        {
                            "id": "is-approval",
                            "leftValue": "={{ $json.skipped }}",
                            "rightValue": False,
                            "operator": {
                                "type": "boolean",
                                "operation": "false",
                                "singleValue": True,
                            },
                        }
                    ],
                    "combinator": "and",
                },
                "looseTypeValidation": True,
                "options": {},
            },
            "id": "wf4-isapproval",
            "name": "Approval needed?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2.2,
            "position": [80, -160],
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ $env.DEVFLOW_ALERT_WEBHOOK }}",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ text: $json.text }) }}",
                "options": {"timeout": 15000},
            },
            "id": "wf4-notify",
            "name": "Notify reviewers",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [320, -240],
            "notes": "Swap for the Slack / Teams / email node your team actually uses.",
            "notesInFlow": True,
        },
        {
            "parameters": {
                "respondWith": "json",
                "responseBody": "={{ JSON.stringify({ notified: true, run_id: $json.run_id }) }}",
                "options": {},
            },
            "id": "wf4-ack1",
            "name": "Ack orchestrator",
            "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1,
            "position": [560, -160],
        },
        {
            "parameters": {
                "respondWith": "json",
                "responseBody": "={{ JSON.stringify({ notified: false, reason: 'event does not need a reviewer' }) }}",
                "options": {},
            },
            "id": "wf4-ack2",
            "name": "Ack (no action)",
            "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1,
            "position": [320, -60],
        },
        {
            "parameters": {
                "httpMethod": "GET",
                "path": "devflow-approve",
                "responseMode": "responseNode",
                "options": {},
            },
            "id": "wf4-decision",
            "name": "Reviewer clicks approve or reject",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [-400, 180],
            "webhookId": "devflow-approve",
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ (" + ORCH + ") + '/runs/' + $json.query.run_id + '/approve' }}",
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [{"name": "X-Devflow-Token", "value": TOKEN}]
                },
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": (
                    "={{ JSON.stringify({ approve_all: $json.query.decision === 'approve', "
                    "reject_all: $json.query.decision !== 'approve', "
                    "reviewer: $json.query.reviewer || 'link-click', "
                    "note: $json.query.note || '' }) }}"
                ),
                "options": {"timeout": 1800000},
            },
            "id": "wf4-resume",
            "name": "Resume the run",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [-140, 180],
            "notes": "Resuming re-enters the agent loop; the response is the run's final state.",
            "notesInFlow": True,
        },
        {
            "parameters": {"jsCode": JS_RESULT},
            "id": "wf4-page",
            "name": "Render confirmation page",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [120, 180],
        },
        {
            "parameters": {
                "respondWith": "text",
                "responseBody": "={{ $json.html }}",
                "options": {
                    "responseHeaders": {
                        "entries": [
                            {"name": "Content-Type", "value": "text/html; charset=utf-8"}
                        ]
                    }
                },
            },
            "id": "wf4-html",
            "name": "Show reviewer the outcome",
            "type": "n8n-nodes-base.respondToWebhook",
            "typeVersion": 1,
            "position": [360, 180],
        },
    ],
    "connections": {
        "Orchestrator callback": {
            "main": [[{"node": "Build approval card", "type": "main", "index": 0}]]
        },
        "Build approval card": {
            "main": [[{"node": "Approval needed?", "type": "main", "index": 0}]]
        },
        "Approval needed?": {
            "main": [
                [{"node": "Notify reviewers", "type": "main", "index": 0}],
                [{"node": "Ack (no action)", "type": "main", "index": 0}],
            ]
        },
        "Notify reviewers": {
            "main": [[{"node": "Ack orchestrator", "type": "main", "index": 0}]]
        },
        "Reviewer clicks approve or reject": {
            "main": [[{"node": "Resume the run", "type": "main", "index": 0}]]
        },
        "Resume the run": {
            "main": [[{"node": "Render confirmation page", "type": "main", "index": 0}]]
        },
        "Render confirmation page": {
            "main": [[{"node": "Show reviewer the outcome", "type": "main", "index": 0}]]
        },
    },
    "settings": {"executionOrder": "v1"},
    "active": False,
    "pinData": {},
    "tags": [{"name": "devflow"}],
}

out = pathlib.Path(__file__).resolve().parent.parent / "n8n" / "workflows"
out.mkdir(parents=True, exist_ok=True)
target = out / "04-human-approval-gate.json"
target.write_text(json.dumps(workflow, indent=2, ensure_ascii=False), encoding="utf-8")
print("wrote", target)
