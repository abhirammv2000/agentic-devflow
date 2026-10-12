# The limiter lets one call too many through

With limit=2 and window=10, three calls made at the same moment are all allowed. The limiter should allow at most `limit` calls in any window of `window` seconds, so the third call should be refused.

A call made exactly `window` seconds after an earlier call is outside that call's window. A refused call does not count against the limit.
