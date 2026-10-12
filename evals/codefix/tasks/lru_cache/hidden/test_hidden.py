from lru import LRUCache


def test_oldest_key_is_evicted():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") is None
    assert cache.get("c") == 3


def test_a_read_keeps_the_key():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)
    assert cache.get("a") == 1
    assert cache.get("b") is None


def test_updating_a_key_keeps_it():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)
    cache.put("c", 3)
    assert cache.get("a") == 10
    assert cache.get("b") is None


def test_missing_key_gives_the_default():
    cache = LRUCache(2)
    assert cache.get("x") is None
    assert cache.get("x", "none") == "none"


def test_capacity_one():
    cache = LRUCache(1)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") is None
    assert cache.get("b") == 2


def test_a_missing_read_does_not_change_the_order():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("zzz")
    cache.put("c", 3)
    assert cache.get("a") is None
    assert cache.get("b") == 2
