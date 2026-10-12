from versions import compare_versions


def test_plain_order():
    assert compare_versions("1.2.0", "1.3.0") == -1


def test_ten_is_newer_than_nine():
    assert compare_versions("1.10.0", "1.9.0") == 1
