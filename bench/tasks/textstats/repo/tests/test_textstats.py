import unittest

import textstats


class TextstatsTest(unittest.TestCase):
    def test_words_and_sentences(self):
        self.assertEqual(textstats.words("It's a test. Another one!"), ["It's", 'a', 'test', 'Another', 'one'])
        self.assertEqual(textstats.sentence_count('One. Two! Three?'), 3)
        self.assertEqual(textstats.average_word_length('ab abcd'), 3.0)
        self.assertEqual(textstats.average_word_length(''), 0.0)


if __name__ == '__main__':
    unittest.main()
