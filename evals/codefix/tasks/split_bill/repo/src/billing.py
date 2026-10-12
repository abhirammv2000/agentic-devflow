def split_bill(total_cents, people):
    """Split a bill into one share in cents per person."""
    share = total_cents // people
    return [share] * people
