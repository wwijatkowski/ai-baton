import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from shop import invoice
from shop.cart import Cart
from shop.catalog import money
from shop.cli import main


class ShopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cart = str(Path(self.tmp.name) / 'cart.json')

    def cli(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = main(['--cart', self.cart, *args])
        return code, out.getvalue()

    def test_money_and_vat(self):
        self.assertEqual((money(1250), money(5), money(-899)), ('12.50', '0.05', '-8.99'))
        self.assertEqual(invoice.vat(1000), 230)
        self.assertEqual(invoice.vat(2), 0)
        self.assertEqual(invoice.vat(3), 1)  # 0.69 rounds to 1

    def test_invoice(self):
        self.assertEqual(self.cli('add', 'mug', '--qty', '2')[0], 0)
        self.assertEqual(self.cli('add', 'BAG')[0], 0)
        self.assertEqual(self.cli('add', 'nope')[0], 1)
        self.assertEqual(self.cli('invoice')[1], '1 x Tote bag (BAG) @ 8.99 = 8.99\n2 x Coffee mug (MUG) @ 12.50 = 25.00\n'
                                                 'Subtotal: 33.99\nVAT 23%: 7.82\nTotal: 41.81\n')
        self.assertEqual(Cart(self.cart).subtotal(), 3399)


if __name__ == '__main__':
    unittest.main()
