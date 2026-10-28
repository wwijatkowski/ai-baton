# Word frequencies

The newsletter tools need the most frequent words of a text.

## Requirements
`word_frequencies(text, top=None, stopwords=None)` in `textstats.py` returns a list of `(word, count)` pairs.
1. Words are found as `words()` finds them, compared in lower case; the returned words are lower case.
2. Sorted by count (highest first), then alphabetically.
3. `top=N` returns only the first N pairs; `top=None` returns all; `top=0` returns `[]`; a negative `top` raises
   `ValueError`.
4. `stopwords`: an iterable of words left out, compared in lower case (`{"The"}` also leaves out "the").
5. Apostrophes: a leading or trailing apostrophe is not part of the word (`'tis` is counted as `tis`, `dogs'` as
   `dogs`); one inside a word stays (`it's`). A word that is only apostrophes is ignored.
6. Tests for all of the above; README updated.

## Work split
- Part 1: requirements 1 to 3 (counting, order, `top`), with tests.
- Part 2: requirements 4 to 6.
