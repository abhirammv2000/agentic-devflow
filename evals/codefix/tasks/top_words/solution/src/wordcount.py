def top_words(text, k):
    """The k most common words with their counts, most common first."""
    counts = {}
    for word in text.split():
        word = word.strip(".,!?;:\"'").lower()
        if word:
            counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:k]
