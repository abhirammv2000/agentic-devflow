from versions import compare_versions


def test_plain_order():
    assert compare_versions("1.2.0", "1.3.0") == -1


def test_ten_is_newer_than_nine():
    assert compare_versions("1.10.0", "1.9.0") == 1


def test_equal_versions():
    assert compare_versions("2.0.1", "2.0.1") == 0


def test_missing_trailing_parts_are_zero():
    assert compare_versions("1.2", "1.2.0") == 0
    assert compare_versions("1.2", "1.2.1") == -1
    assert compare_versions("1.2.1", "1.2") == 1


def test_major_version_wins():
    assert compare_versions("10.0", "9.99.99") == 1


def test_single_numbers():
    assert compare_versions("3", "12") == -1


def test_order_is_antisymmetric():
    pairs = [("1.0", "1.0.1"), ("1.10", "1.9"), ("2", "2.0.0"), ("0.9.9", "1")]
    for a, b in pairs:
        assert compare_versions(a, b) == -compare_versions(b, a)
