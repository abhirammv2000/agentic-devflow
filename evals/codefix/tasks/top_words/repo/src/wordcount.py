def top_words(text, k):
    """The k most common words, most common first."""
    counts = {}
    for word in text.split():
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts, key=lambda w: counts[w], reverse=True)
    return ranked[:k]
