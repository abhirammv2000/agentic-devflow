def split_bill(total_cents, people):
    """Split a bill into one share in cents per person."""
    if people < 1:
        raise ValueError("people must be at least 1")
    base, extra = divmod(total_cents, people)
    return [base + 1] * extra + [base] * (people - extra)
