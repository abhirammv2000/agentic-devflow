from csvline import parse_line


def test_plain_fields():
    assert parse_line("a,b,c") == ["a", "b", "c"]


def test_comma_inside_quotes():
    assert parse_line('a,"b,c",d') == ["a", "b,c", "d"]


def test_doubled_quote_is_one_quote():
    assert parse_line('"say ""hi""",x') == ['say "hi"', "x"]


def test_empty_fields_are_kept():
    assert parse_line("a,,b") == ["a", "", "b"]
    assert parse_line("a,b,") == ["a", "b", ""]


def test_empty_line_is_one_empty_field():
    assert parse_line("") == [""]


def test_quoted_empty_field():
    assert parse_line('"",x') == ["", "x"]


def test_unquoted_fields_are_not_trimmed():
    assert parse_line(" a , b ") == [" a ", " b "]


def test_quoted_field_keeps_spaces_and_commas():
    assert parse_line('" a, b ",c') == [" a, b ", "c"]


def test_only_a_quoted_field():
    assert parse_line('"x,y"') == ["x,y"]
