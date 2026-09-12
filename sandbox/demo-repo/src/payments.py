"""Checkout payment helpers."""

import uuid

MAX_ATTEMPTS = 2


def charge(provider, amount_cents, card_token):
    """Charge a card, retrying once if the provider times out.

    Both attempts carry the same idempotency key, so a provider that timed out
    *after* capturing the payment recognises the retry as the same charge
    instead of billing the customer twice.
    """
    idempotency_key = "idem_{}".format(uuid.uuid4().hex)
    response = provider.charge(
        amount_cents, card_token, idempotency_key=idempotency_key
    )
    if response.timed_out:
        response = provider.charge(
            amount_cents, card_token, idempotency_key=idempotency_key
        )
    return response
