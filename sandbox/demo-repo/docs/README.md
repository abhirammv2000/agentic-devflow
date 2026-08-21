# checkout-service

Payment helpers for the Acme checkout flow.

## `charge(provider, amount_cents, card_token)`

Charges a card and returns the provider response.

If the provider times out, the call is retried once. The function returns the
final `ProviderResponse`; callers should check `response.charge_id`.

## Retry semantics

A timeout from the provider is ambiguous: the charge may or may not have been
captured. The current retry policy is documented above.
