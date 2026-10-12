class InsufficientFunds(Exception):
    pass


class Account:
    """A bank account that cannot go below zero."""

    def __init__(self, balance=0):
        if balance < 0:
            raise ValueError("opening balance cannot be negative")
        self.balance = balance

    def deposit(self, amount):
        if amount <= 0:
            raise ValueError("deposit must be positive")
        self.balance += amount

    def withdraw(self, amount):
        if amount < 0:
            raise ValueError("withdrawal must be positive")
        if amount > self.balance:
            raise InsufficientFunds("balance is " + str(self.balance))
        self.balance -= amount

    def transfer(self, other, amount):
        self.withdraw(amount)
        other.deposit(amount)
