import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.payments import charge
from src.provider import Provider


def test_successful_charge_calls_provider_once():
    provider = Provider()
    response = charge(provider, 2500, "tok_visa")
    assert response.charge_id is not None
    assert len(provider.calls) == 1


def test_timeout_is_retried():
    provider = Provider(timeouts_before_success=1)
    response = charge(provider, 2500, "tok_visa")
    assert response.charge_id is not None
    assert len(provider.calls) == 2


def test_retry_after_timeout_reuses_the_same_idempotency_key():
    provider = Provider(timeouts_before_success=1)
    charge(provider, 2500, "tok_visa")
    first, retry = provider.calls
    assert first["idempotency_key"] is not None
    assert retry["idempotency_key"] == first["idempotency_key"]


def test_separate_charges_use_different_idempotency_keys():
    provider = Provider()
    charge(provider, 2500, "tok_visa")
    charge(provider, 2500, "tok_visa")
    first, second = provider.calls
    assert first["idempotency_key"] != second["idempotency_key"]
