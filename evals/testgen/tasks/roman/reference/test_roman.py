import pytest

from roman import roman_to_int


def test_single_symbols():
    assert [roman_to_int(c) for c in "IVXLCDM"] == [1, 5, 10, 50, 100, 500, 1000]


def test_additive_numerals():
    assert roman_to_int("XX") == 20
    assert roman_to_int("VIII") == 8
    assert roman_to_int("MMM") == 3000


def test_subtractive_numerals():
    assert roman_to_int("IV") == 4
    assert roman_to_int("IX") == 9
    assert roman_to_int("XL") == 40
    assert roman_to_int("CM") == 900


def test_a_long_mixed_numeral():
    assert roman_to_int("MCMXCIV") == 1994


def test_empty_string_is_an_error():
    with pytest.raises(ValueError):
        roman_to_int("")


def test_invalid_character_is_a_value_error():
    with pytest.raises(ValueError):
        roman_to_int("ABC")
    with pytest.raises(ValueError):
        roman_to_int("XIZ")
