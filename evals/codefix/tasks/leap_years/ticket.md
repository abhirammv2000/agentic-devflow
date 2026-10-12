# 1900 is treated as a leap year

days_in_month(1900, 2) returns 29, but 1900 was not a leap year. A year divisible by 100 is only a leap year if it is also divisible by 400, so 2000 and 2400 are leap years and 1900 and 2100 are not.

A month outside 1 to 12 should raise ValueError.
