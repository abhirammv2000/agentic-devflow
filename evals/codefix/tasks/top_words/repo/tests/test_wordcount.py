from wordcount import top_words


def test_counts_come_with_the_words():
    assert top_words("a b a", 2) == [("a", 2), ("b", 1)]


def test_case_and_punctuation_are_ignored():
    assert top_words("The cat. the dog, THE end", 1) == [("the", 3)]
