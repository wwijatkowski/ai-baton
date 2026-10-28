"""Small text statistics used by the newsletter tools."""
import re

WORD = re.compile(r"[A-Za-z']+")


def words(text):
    """The words of a text, in order."""
    return WORD.findall(text)


def sentence_count(text):
    return len([s for s in re.split(r'[.!?]+', text) if s.strip()])


def average_word_length(text):
    found = words(text)
    return round(sum(len(w) for w in found) / len(found), 2) if found else 0.0


def word_frequencies(text, top=None, stopwords=None):
    if top is not None and top < 0:
        raise ValueError('top must not be negative')
    skip = {w.lower() for w in stopwords or ()}
    counts = {}
    for word in words(text):
        word = word.strip("'").lower()
        if word and word not in skip:
            counts[word] = counts.get(word, 0) + 1
    pairs = sorted(counts.items(), key=lambda p: (-p[1], p[0]))
    return pairs if top is None else pairs[:top]
