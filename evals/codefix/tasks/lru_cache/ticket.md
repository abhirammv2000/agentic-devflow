# Reading a key does not keep it in the cache

With capacity 2, put("a", 1), put("b", 2), get("a"), put("c", 3) evicts "a", but "a" was just read. A read should count as using the key, so "b" should be evicted instead.

Updating the value of a key that is already in the cache also counts as using it.
