import pytest

from wrap import wrap


def test_short_text_stays_on_one_line():
    assert wrap("hello world", 20) == ["hello world"]


def test_breaks_at_spaces():
    assert wrap("the quick brown fox", 10) == ["the quick", "brown fox"]


def test_a_line_may_be_exactly_the_width():
    assert wrap("abc def", 7) == ["abc def"]
    assert wrap("abc def", 6) == ["abc", "def"]


def test_long_word_gets_its_own_line():
    assert wrap("a extraordinarily b", 5) == ["a", "extraordinarily", "b"]


def test_extra_spaces_are_ignored():
    assert wrap("a   b", 10) == ["a b"]


def test_empty_text_gives_no_lines():
    assert wrap("", 10) == []
    assert wrap("   ", 10) == []


def test_width_below_one_is_an_error():
    for bad in (0, -3):
        with pytest.raises(ValueError):
            wrap("x", bad)


def test_every_word_is_kept_in_order():
    text = "one two three four five six seven eight nine ten"
    assert " ".join(wrap(text, 12)) == text
