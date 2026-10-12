from csvline import parse_line


def test_plain_fields():
    assert parse_line("a,b,c") == ["a", "b", "c"]


def test_comma_inside_quotes():
    assert parse_line('a,"b,c",d') == ["a", "b,c", "d"]
