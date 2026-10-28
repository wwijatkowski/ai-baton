# Acceptance tests for bundles (part 2) and existing behavior; never shown to the agents.
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from shop.cli import main


class HiddenBundlesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cart = str(Path(self.tmp.name) / 'cart.json')

    def cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--cart', self.cart, *args])
        return code, out.getvalue()

    def fill(self, *items):
        for sku, qty in items:
            self.cli('add', sku, '--qty', str(qty))

    def test_invoice_with_bundles(self):
        self.fill(('MUG', 2), ('TEE', 1), ('CAP', 1), ('BAG', 1))
        # STARTER x1 (MUG+TEE), TRAVEL x1 (CAP+BAG), one MUG left.
        self.assertEqual(self.cli('invoice')[1],
                         '1 x Starter pack (STARTER) @ 32.99 = 32.99\n1 x Travel set (TRAVEL) @ 20.99 = 20.99\n'
                         '1 x Coffee mug (MUG) @ 12.50 = 12.50\nSubtotal: 66.48\nVAT 23%: 15.29\nTotal: 81.77\n')

    def test_several_of_one_bundle(self):
        self.fill(('MUG', 2), ('TEE', 3))
        self.assertEqual(self.cli('invoice')[1],
                         '2 x Starter pack (STARTER) @ 32.99 = 65.98\n1 x T-shirt (TEE) @ 24.99 = 24.99\n'
                         'Subtotal: 90.97\nVAT 23%: 20.92\nTotal: 111.89\n')

    def test_no_bundles_option_and_no_match(self):
        self.fill(('MUG', 1), ('TEE', 1))
        self.assertEqual(self.cli('invoice', '--no-bundles')[1],
                         '1 x Coffee mug (MUG) @ 12.50 = 12.50\n1 x T-shirt (TEE) @ 24.99 = 24.99\n'
                         'Subtotal: 37.49\nVAT 23%: 8.62\nTotal: 46.11\n')
        self.cli('remove', 'TEE')
        self.assertEqual(self.cli('invoice')[1], '1 x Coffee mug (MUG) @ 12.50 = 12.50\nSubtotal: 12.50\nVAT 23%: 2.88\nTotal: 15.38\n')

    def test_bundles_command(self):
        self.assertEqual(self.cli('bundles'), (0, 'STARTER  Starter pack: MUG + TEE  32.99 (save 4.50)\n'
                                                  'TRAVEL  Travel set: BAG + CAP  20.99 (save 3.99)\n'))

    def test_existing_behavior(self):
        self.assertEqual(self.cli('add', 'nope')[0], 1)
        self.fill(('BAG', 1))
        self.assertEqual(self.cli('invoice')[1], '1 x Tote bag (BAG) @ 8.99 = 8.99\nSubtotal: 8.99\nVAT 23%: 2.07\nTotal: 11.06\n')


if __name__ == '__main__':
    unittest.main()
