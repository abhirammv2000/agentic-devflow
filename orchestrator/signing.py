"""Signed approval links.

The approve and reject links in the reviewer's card open a public n8n webhook. Without a signature, anyone
who learns or guesses a run id could open one and approve a pending action. A link now carries a token the
orchestrator checks before it resumes anything. The token is an HMAC-SHA256 over:

  - the run id
  - the decision (an approve token cannot be used to reject, and the other way round)
  - the exact set of tool calls waiting for a decision, so a token for one pause cannot be replayed on a
    later pause of the same run
  - an expiry time

Tokens are compared in constant time. A token is also single use in practice: deciding resumes the run, so
the pending set it was made for is gone. The secret is DEVFLOW_APPROVAL_SECRET, or the service token if that
is not set.
"""

from __future__ import annotations

import hashlib
import hmac
import time


def _mac(secret: str, run_id: str, decision: str, pending_ids: list[str], expires: int) -> str:
    message = "|".join([run_id, decision, ",".join(sorted(pending_ids)), str(int(expires))])
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def make_link_tokens(secret: str, run_id: str, pending_ids: list[str], ttl_seconds: int, now: float | None = None) -> dict:
    """Tokens for the approve and reject links of one pause, and when they stop working."""
    expires = int((now if now is not None else time.time()) + ttl_seconds)
    return {
        "approve": _mac(secret, run_id, "approve", pending_ids, expires),
        "reject": _mac(secret, run_id, "reject", pending_ids, expires),
        "expires": expires,
    }


def check_link_token(secret: str, run_id: str, decision: str, pending_ids: list[str], expires: int | None,
                     token: str | None, now: float | None = None) -> str | None:
    """None if the token is good, otherwise a short reason. The reason is for the log, not for the caller."""
    if not token or expires is None:
        return "no token"
    if (now if now is not None else time.time()) > expires:
        return "expired"
    expected = _mac(secret, run_id, decision, pending_ids, expires)
    if not hmac.compare_digest(expected.encode(), token.encode()):
        return "does not match"
    return None
