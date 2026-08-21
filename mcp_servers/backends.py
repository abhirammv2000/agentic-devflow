"""Storage + HTTP backends shared by the three MCP servers.

Every server runs in one of two modes:

  mock (DEVFLOW_MOCK=1)  -> all state lives in data/mock_state.json
  live                   -> real GitHub / Jira REST calls via httpx

Mock mode exists so the whole prototype is runnable end-to-end with no
credentials; the tool surface Claude sees is byte-identical in both modes.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any

import httpx

MOCK = os.getenv("DEVFLOW_MOCK", "1") == "1"
DATA_DIR = Path(os.getenv("DEVFLOW_DATA_DIR", "./data")).resolve()
STATE_FILE = DATA_DIR / "mock_state.json"

_LOCK = threading.Lock()


# --------------------------------------------------------------------------
# mock store
# --------------------------------------------------------------------------

def _seed() -> dict[str, Any]:
    return {
        "github": {
            "repos": {
                "acme/checkout-service": {
                    "default_branch": "main",
                    "branches": {"main": {"sha": "a1b2c3d"}},
                    "issues": {
                        "41": {
                            "number": 41,
                            "title": "Checkout retries charge the card twice",
                            "body": (
                                "When the payment provider times out, our retry path calls "
                                "`charge()` again without an idempotency key. Two customers "
                                "were double-charged on 2026-08-14."
                            ),
                            "state": "open",
                            "labels": [],
                            "author": "dana-ops",
                            "comments": [],
                        }
                    },
                    "pulls": {},
                    "files": {
                        "src/payments.py": (
                            "def charge(amount_cents, card_token):\n"
                            "    resp = provider.charge(amount_cents, card_token)\n"
                            "    if resp.timed_out:\n"
                            "        resp = provider.charge(amount_cents, card_token)\n"
                            "    return resp\n"
                        )
                    },
                }
            },
            "next_issue": 42,
            "next_pr": 100,
        },
        "jira": {
            "issues": {},
            "next": {"OPS": 1, "ENG": 1},
        },
        "audit": [],
    }


def _load() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        STATE_FILE.write_text(json.dumps(_seed(), indent=2), encoding="utf-8")
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def _save(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


class Store:
    """Tiny JSON-file store. Serialised by a lock; adequate for a prototype."""

    def read(self) -> dict[str, Any]:
        with _LOCK:
            return _load()

    def mutate(self, fn):
        with _LOCK:
            state = _load()
            result = fn(state)
            _save(state)
            return result

    def audit(self, actor: str, action: str, detail: dict[str, Any]) -> None:
        def _add(state):
            state["audit"].append(
                {"ts": time.time(), "actor": actor, "action": action, "detail": detail}
            )
        self.mutate(_add)


store = Store()


def reset_mock_state() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _save(_seed())


# --------------------------------------------------------------------------
# live HTTP clients
# --------------------------------------------------------------------------

class MissingCredentials(RuntimeError):
    pass


def github_client() -> httpx.Client:
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise MissingCredentials(
            "GITHUB_TOKEN is not set. Either export a token or run with DEVFLOW_MOCK=1."
        )
    return httpx.Client(
        base_url=os.getenv("GITHUB_API", "https://api.github.com"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30.0,
    )


def jira_client() -> httpx.Client:
    base = os.getenv("JIRA_BASE_URL")
    email = os.getenv("JIRA_EMAIL")
    token = os.getenv("JIRA_API_TOKEN")
    if not (base and email and token):
        raise MissingCredentials(
            "JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN are not all set. "
            "Either configure them or run with DEVFLOW_MOCK=1."
        )
    return httpx.Client(
        base_url=base.rstrip("/") + "/rest/api/3",
        auth=(email, token),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        timeout=30.0,
    )


def adf(text: str) -> dict[str, Any]:
    """Wrap plain text in Atlassian Document Format (Jira Cloud v3 comment bodies)."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": line or " "}]}
            for line in text.split("\n")
        ],
    }


def ok(**kwargs: Any) -> dict[str, Any]:
    return {"ok": True, **kwargs}


def err(message: str, **kwargs: Any) -> dict[str, Any]:
    return {"ok": False, "error": message, **kwargs}
