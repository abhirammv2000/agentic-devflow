# Splitting a bill loses cents

split_bill(100, 3) returns [33, 33, 33], which adds up to 99 cents.

The shares must always add up to the total. They should differ by at most one cent, and the extra cents go to the first people in the list, so split_bill(100, 3) is [34, 33, 33]. people below 1 should raise ValueError.
