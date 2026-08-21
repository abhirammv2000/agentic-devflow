"""Reset the mock GitHub/Jira store, the working copy and all run records."""

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_servers.backends import DATA_DIR, reset_mock_state  # noqa: E402
from orchestrator.config import settings  # noqa: E402

ORIGINAL_PAYMENTS = '''"""Checkout payment helpers."""

MAX_ATTEMPTS = 2


def charge(provider, amount_cents, card_token):
    """Charge a card, retrying once if the provider times out.

    BUG (OPS-1 / acme/checkout-service#41): the retry re-sends the charge with
    no idempotency key, so a provider that timed out *after* capturing the
    payment charges the customer twice.
    """
    response = provider.charge(amount_cents, card_token)
    if response.timed_out:
        response = provider.charge(amount_cents, card_token)
    return response
'''


def main() -> None:
    if DATA_DIR.exists():
        shutil.rmtree(DATA_DIR)
    reset_mock_state()

    payments = settings.workspace / "src" / "payments.py"
    payments.write_text(ORIGINAL_PAYMENTS, encoding="utf-8")

    for stray in (settings.workspace / "tests").glob("test_*regression*.py"):
        stray.unlink()

    print("reset:")
    print("  mock store   ", DATA_DIR / "mock_state.json")
    print("  run records  ", settings.runs_dir)
    print("  working copy ", settings.workspace)


if __name__ == "__main__":
    main()
