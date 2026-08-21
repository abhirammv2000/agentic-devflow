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
