def is_leap_year(year):
    return year % 4 == 0


def days_in_month(year, month):
    """Number of days in a month of a year."""
    if month == 2:
        return 29 if is_leap_year(year) else 28
    if month in (4, 6, 9, 11):
        return 30
    return 31
