# Acceptance tests for ISSUE.md part 2 (and existing behavior); never shown to the agents.
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from shop.cli import main

CODES = {'codes': [
    {'code': 'save10', 'kind': 'percent', 'value': 10},
    {'code': 'FIVE', 'kind': 'fixed', 'value': 500},
    {'code': 'BIG', 'kind': 'fixed', 'value': 10000},
    {'code': 'OLD', 'kind': 'percent', 'value': 20, 'expires': '2026-01-31'},
    {'code': 'MIN50', 'kind': 'percent', 'value': 5, 'min_subtotal': 5000},
]}
LINES = '1 x Tote bag (BAG) @ 8.99 = 8.99\n2 x Coffee mug (MUG) @ 12.50 = 25.00\nSubtotal: 33.99\n'


class HiddenCodesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.cart, self.codes = str(base / 'cart.json'), str(base / 'codes.json')
        Path(self.codes).write_text(json.dumps(CODES))
        self.cli('add', 'MUG', '--qty', '2')
        self.cli('add', 'BAG')

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--cart', self.cart, *args])
        return code, out.getvalue(), err.getvalue()

    def invoice(self, code, today='2026-01-15'):
        return self.cli('invoice', '--code', code, '--codes', self.codes, '--today', today)

    def test_percent_code(self):
        self.assertEqual(self.invoice('SAVE10')[:2], (0, LINES + 'Discount (SAVE10): -3.40\nVAT 23%: 7.04\nTotal: 37.63\n'))
        self.assertEqual(self.invoice('save10')[1], self.invoice('SAVE10')[1])

    def test_fixed_codes(self):
        self.assertEqual(self.invoice('FIVE')[1], LINES + 'Discount (FIVE): -5.00\nVAT 23%: 6.67\nTotal: 35.66\n')
        self.assertEqual(self.invoice('BIG')[1], LINES + 'Discount (BIG): -33.99\nVAT 23%: 0.00\nTotal: 0.00\n')

    def test_codes_that_cannot_be_used(self):
        self.assertEqual(self.invoice('OLD', '2026-01-31')[0], 0)
        for code, today, message in (
                ('OLD', '2026-02-01', "discount code 'OLD' expired on 2026-01-31"),
                ('min50', '2026-01-15', "discount code 'MIN50' needs a subtotal of at least 50.00"),
                ('nope', '2026-01-15', "unknown discount code 'NOPE'")):
            exit_code, out, err = self.invoice(code, today)
            self.assertEqual((exit_code, out, err.strip()), (1, '', f'shop: {message}'), code)

    def test_without_a_code_unchanged(self):
        self.assertEqual(self.cli('invoice')[1], LINES + 'VAT 23%: 7.82\nTotal: 41.81\n')


if __name__ == '__main__':
    unittest.main()
