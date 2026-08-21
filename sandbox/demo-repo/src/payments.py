"""Checkout payment helpers."""

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
