from slugify import slugify


def test_simple_title():
    assert slugify("Hello World") == "hello-world"


def test_messy_title():
    assert slugify("  Hello,   World!  ") == "hello-world"
