# Acceptance tests for ISSUE.md; never shown to the agents.
import unittest

import textstats
from textstats import word_frequencies as wf


class HiddenFrequenciesTest(unittest.TestCase):
    def test_counting_and_order(self):
        self.assertEqual(wf('b a B c a b'), [('b', 3), ('a', 2), ('c', 1)])
        self.assertEqual(wf(''), [])

    def test_top(self):
        self.assertEqual(wf('a a b c', top=2), [('a', 2), ('b', 1)])
        self.assertEqual(wf('a a b', top=0), [])
        self.assertEqual(wf('a', top=5), [('a', 1)])
        with self.assertRaises(ValueError):
            wf('a', top=-1)

    def test_stopwords(self):
        self.assertEqual(wf('The cat and the hat', stopwords={'The', 'AND'}), [('cat', 1), ('hat', 1)])
        self.assertEqual(wf('a a b', stopwords=['a'], top=1), [('b', 1)])
        self.assertEqual(wf('a b', stopwords=iter(['b'])), [('a', 1)])

    def test_apostrophes(self):
        self.assertEqual(wf("'tis the dogs' toy, it's 'its' ''"), [('dogs', 1), ("it's", 1), ('its', 1), ('the', 1),
                                                                     ('tis', 1), ('toy', 1)])
        self.assertEqual(wf("'' ' a"), [('a', 1)])

    def test_existing_behavior(self):
        self.assertEqual(textstats.words("It's a test."), ["It's", 'a', 'test'])
        self.assertEqual(textstats.sentence_count('One. Two!'), 2)


if __name__ == '__main__':
    unittest.main()
