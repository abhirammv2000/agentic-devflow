"""Stand-in for the payment provider SDK used by the demo repo."""


class ProviderResponse:
    def __init__(self, charge_id, amount_cents, timed_out=False):
        self.charge_id = charge_id
        self.amount_cents = amount_cents
        self.timed_out = timed_out


class Provider:
    """Records every charge it receives so tests can assert on duplicates."""

    def __init__(self, timeouts_before_success=0):
        self.calls = []
        self._remaining_timeouts = timeouts_before_success

    def charge(self, amount_cents, card_token, idempotency_key=None):
        self.calls.append(
            {
                "amount_cents": amount_cents,
                "card_token": card_token,
                "idempotency_key": idempotency_key,
            }
        )
        if self._remaining_timeouts > 0:
            self._remaining_timeouts -= 1
            return ProviderResponse(None, amount_cents, timed_out=True)
        return ProviderResponse("ch_{}".format(len(self.calls)), amount_cents)
