# Word counts treat 'The' and 'the' as different words

top_words("The cat. the dog, THE end", 1) returns ["The"]. Words should be counted without regard to case and without the punctuation around them, so the result should be [("the", 3)].

top_words(text, k) should return a list of (word, count) tuples for the k most common words, most common first. Words with the same count are ordered alphabetically. Ignore these characters at the start and end of a word: . , ! ? ; : and quote marks. If there are fewer than k different words, return all of them.
