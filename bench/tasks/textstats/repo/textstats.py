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
