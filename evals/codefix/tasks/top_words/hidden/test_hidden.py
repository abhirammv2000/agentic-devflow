from wordcount import top_words


def test_counts_come_with_the_words():
    assert top_words("a b a", 2) == [("a", 2), ("b", 1)]


def test_case_and_punctuation_are_ignored():
    assert top_words("The cat. the dog, THE end", 1) == [("the", 3)]


def test_ties_are_alphabetical():
    assert top_words("pear apple fig", 3) == [("apple", 1), ("fig", 1), ("pear", 1)]


def test_fewer_words_than_k():
    assert top_words("one two", 10) == [("one", 1), ("two", 1)]


def test_quotes_and_question_marks_are_stripped():
    assert top_words('"Hi!" hi? hi', 1) == [("hi", 3)]


def test_punctuation_alone_is_not_a_word():
    assert top_words("a ... , a", 2) == [("a", 2)]


def test_empty_text():
    assert top_words("", 3) == []


def test_k_zero():
    assert top_words("a b c", 0) == []


def test_ordering_by_count_then_name():
    text = "b b a a c c c d"
    assert top_words(text, 4) == [("c", 3), ("a", 2), ("b", 2), ("d", 1)]
