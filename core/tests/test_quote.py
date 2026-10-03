"""Quote matching: normalisation q1, verdicts, offsets, and agreement with peerpanel."""
import os
import unittest

from litcheck import quote
from tests import CHANGED_QUOTE, FIXTURES, TRUE_QUOTE


def paper_text():
    with open(os.path.join(FIXTURES, 'pmc-text-pmc10496602.1.body'), 'rb') as handle:
        return handle.read().decode('utf-8')


def peerpanel_norm(text):
    """peerpanel/src/peerpanel/agents/claims_verifier.py:138-140, re-implemented inline."""
    return ' '.join(text.split())


class NormaliseTests(unittest.TestCase):
    def test_version_is_pinned(self):
        self.assertEqual(quote.NORMALISATION_VERSION, 'q1')

    def test_rules(self):
        self.assertEqual(quote.normalise('‘a’ “b”'), '\'a\' "b"')
        for dash in '‐‑‒–—―−':
            self.assertEqual(quote.normalise('a%sb' % dash), 'a-b')
        self.assertEqual(quote.normalise('  a \n\t b c  '), 'a b c')
        self.assertEqual(quote.normalise('ﬁne'), 'fine')  # NFKC ligature
        self.assertEqual(quote.normalise('Case'), 'Case')
        self.assertEqual(quote.normalise('elas-\nticity'), 'elas- ticity')  # no de-hyphenation

    def test_contract_drift_against_peerpanel(self):
        """On inputs that differ only in whitespace, both rules give the same answer."""
        text = 'The  quick brown\nfox jumps over\tthe lazy dog near the river bank.'
        variants = ['quick brown fox jumps', 'quick  brown\nfox jumps', ' quick brown fox\tjumps ',
                    'brown fox\n\njumps over the', 'quick brown cat jumps', 'lazy dog near  the',
                    'Quick brown fox jumps']
        for q in variants:
            ours = quote.normalise(q) in quote.normalise(text)
            theirs = peerpanel_norm(q) in peerpanel_norm(text)
            self.assertEqual(ours, theirs, q)
            self.assertEqual(quote.normalise(q), peerpanel_norm(q))


class CheckTests(unittest.TestCase):
    def test_true_quote_found_with_offsets_and_paragraph(self):
        text = paper_text()
        result = quote.check(TRUE_QUOTE, text)
        self.assertEqual(result['verdict'], quote.FOUND)
        start, end = result['offsets']
        self.assertEqual(quote.normalise(text)[start:end], TRUE_QUOTE)
        paragraphs = [p for p in text.split('\n\n')]
        self.assertIn('Arteriosclerosis consists of', paragraphs[result['paragraph']])
        self.assertTrue(result['casefold_found'])
        self.assertEqual(result['normalisation'], 'q1')

    def test_one_word_changed_is_not_found(self):
        result = quote.check(CHANGED_QUOTE, paper_text())
        self.assertEqual(result['verdict'], quote.NOT_FOUND)
        self.assertIsNone(result['offsets'])
        self.assertFalse(result['casefold_found'])

    def test_rewrapped_and_curly_quote_still_found(self):
        text = 'He wrote: “the arterial wall\nis   stiff” in 2016, with one–two caveats.'
        self.assertEqual(quote.check('"the arterial wall is stiff" in 2016, with one-two',
                                     text)['verdict'], quote.FOUND)

    def test_case_differences_are_flagged_not_found(self):
        result = quote.check(TRUE_QUOTE.upper(), paper_text())
        self.assertEqual(result['verdict'], quote.NOT_FOUND)
        self.assertTrue(result['casefold_found'])

    def test_too_short(self):
        result = quote.check('large-artery', paper_text())
        self.assertEqual(result['verdict'], quote.TOO_SHORT)
        self.assertIsNone(result['casefold_found'])
        self.assertEqual(quote.check('x' * 19, 'x' * 40)['verdict'], quote.TOO_SHORT)
        self.assertEqual(quote.check('x' * 20, 'x' * 40)['verdict'], quote.FOUND)

    def test_paragraph_counts_blank_line_blocks(self):
        text = 'first block here\n\nsecond block with a long enough phrase\n \nthird one'
        result = quote.check('with a long enough phrase', text)
        self.assertEqual((result['verdict'], result['paragraph']), (quote.FOUND, 1))

    def test_paragraph_index_skips_empty_blocks(self):
        text = 'first block here\n\n\n\nsecond block with a long enough phrase'
        self.assertEqual(quote.check('with a long enough phrase', text)['paragraph'], 1)

    def test_not_checkable_shape(self):
        self.assertEqual(quote.not_checkable()['verdict'], quote.NOT_CHECKABLE)


if __name__ == '__main__':
    unittest.main()
