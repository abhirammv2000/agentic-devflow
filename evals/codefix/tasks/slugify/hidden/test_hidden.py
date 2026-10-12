from slugify import slugify


def test_simple_title():
    assert slugify("Hello World") == "hello-world"


def test_messy_title():
    assert slugify("  Hello,   World!  ") == "hello-world"


def test_symbols_between_words_collapse():
    assert slugify("Rock & Roll 101") == "rock-roll-101"


def test_underscores_and_dots_are_separators():
    assert slugify("a_b.c") == "a-b-c"


def test_already_a_slug_is_unchanged():
    assert slugify("already-a-slug") == "already-a-slug"


def test_only_symbols_gives_empty_string():
    assert slugify("---") == ""
    assert slugify("") == ""


def test_trailing_punctuation_is_dropped():
    assert slugify("What?!") == "what"
