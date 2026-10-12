import pytest

from account import Account, InsufficientFunds


def test_opening_balance():
    assert Account().balance == 0
    assert Account(50).balance == 50


def test_negative_opening_balance_is_an_error():
    with pytest.raises(ValueError):
        Account(-1)


def test_deposit_adds_to_the_balance():
    account = Account(10)
    account.deposit(5)
    assert account.balance == 15


def test_deposit_must_be_positive():
    account = Account(10)
    for bad in (0, -5):
        with pytest.raises(ValueError):
            account.deposit(bad)
    assert account.balance == 10


def test_withdraw_subtracts_from_the_balance():
    account = Account(10)
    account.withdraw(4)
    assert account.balance == 6


def test_withdraw_must_be_positive():
    account = Account(10)
    for bad in (0, -5):
        with pytest.raises(ValueError):
            account.withdraw(bad)
    assert account.balance == 10


def test_can_withdraw_the_whole_balance():
    account = Account(10)
    account.withdraw(10)
    assert account.balance == 0


def test_cannot_withdraw_more_than_the_balance():
    account = Account(10)
    with pytest.raises(InsufficientFunds):
        account.withdraw(11)
    assert account.balance == 10


def test_transfer_moves_money():
    a, b = Account(10), Account(1)
    a.transfer(b, 4)
    assert (a.balance, b.balance) == (6, 5)


def test_failed_transfer_changes_nothing():
    a, b = Account(3), Account(1)
    with pytest.raises(InsufficientFunds):
        a.transfer(b, 4)
    assert (a.balance, b.balance) == (3, 1)
