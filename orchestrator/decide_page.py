"""The confirm page behind the approve and reject links.

Opening a link (GET) only shows what is waiting and a button. The decision happens when the button is
pressed (POST). That matters because chat apps and mail scanners fetch links to make a preview, and a
link that decided on GET would be approved by the preview. Everything that came from the model or a tool is
escaped, because the arguments of a pending call can contain text an attacker wrote.
"""

from __future__ import annotations

import html
from typing import Any

# no scripts, no framing, no outside requests, and the page can only post back to itself
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",  # the token is in the URL
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}

_STYLE = ("body{font:16px/1.5 system-ui;margin:3rem auto;max-width:44rem;padding:0 1rem}"
          "pre{white-space:pre-wrap;background:#f4f4f5;padding:1rem;border-radius:8px}"
          "button{font:inherit;padding:.6rem 1.2rem;border-radius:8px;border:1px solid #888;cursor:pointer}"
          "input[type=text]{font:inherit;padding:.4rem;width:16rem}")


def _page(title: str, body: str) -> str:
    return ("<!doctype html><meta charset=\"utf-8\"><title>" + html.escape(title) + "</title>"
            "<style>" + _STYLE + "</style><body>" + body + "</body>")


def message(title: str, text: str) -> str:
    return _page(title, "<h1>" + html.escape(title) + "</h1><p>" + html.escape(text) + "</p>")


def confirm(run: dict[str, Any], decision: str, token: str, expires: int) -> str:
    """What is waiting, and one button that records the decision."""
    verb = "Approve" if decision == "approve" else "Reject"
    actions = "".join(
        "<li><strong>" + html.escape(a["tool"]) + "</strong> (" + html.escape(a["tier"]) + ")<br>"
        + html.escape(a["reason"]) + "<pre>" + html.escape(a["arguments"]) + "</pre></li>"
        for a in run.get("pending_approvals", [])
    )
    fields = "".join(
        '<input type="hidden" name="{}" value="{}">'.format(name, html.escape(str(value), quote=True))
        for name, value in (("decision", decision), ("token", token), ("expires", expires))
    )
    body = (
        "<h1>" + verb + " this run?</h1>"
        "<p>Run <code>" + html.escape(run["run_id"]) + "</code> (" + html.escape(run["playbook"]) + ") is waiting for a decision on:</p>"
        "<ul>" + actions + "</ul>"
        '<form method="post">' + fields +
        '<p><label>Your name (recorded in the audit log) <input type="text" name="reviewer" maxlength="60"></label></p>'
        "<button type=\"submit\">" + verb + "</button></form>"
    )
    return _page(verb + " this run?", body)


def done(run: dict[str, Any]) -> str:
    return _page(
        "Decision recorded",
        "<h1>Decision recorded</h1><p>Run <code>" + html.escape(run["run_id"]) + "</code> is now <strong>"
        + html.escape(run["status"]) + "</strong>.</p><pre>" + html.escape(run.get("summary") or "") + "</pre>",
    )
