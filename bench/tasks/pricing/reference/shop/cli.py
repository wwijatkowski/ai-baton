import argparse
import sys
from datetime import date

from . import invoice
from .cart import Cart
from .catalog import CatalogError
from .discounts import find, load_codes


def main(argv=None):
    parser = argparse.ArgumentParser(prog='shop')
    parser.add_argument('--cart', default='cart.json')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('add')
    p.add_argument('sku')
    p.add_argument('--qty', type=int, default=1)
    p = sub.add_parser('remove')
    p.add_argument('sku')
    p = sub.add_parser('invoice')
    p.add_argument('--code')
    p.add_argument('--codes', default='codes.json')
    p.add_argument('--today', type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    cart = Cart(args.cart)
    try:
        if args.command == 'add':
            cart.add(args.sku, args.qty)
            cart.save()
        elif args.command == 'remove':
            cart.remove(args.sku)
            cart.save()
        elif args.command == 'invoice':
            discount = None
            if args.code:
                discount = find(load_codes(args.codes), args.code, cart.subtotal(), args.today or date.today())
            print(invoice.render(cart, discount))
    except (CatalogError, ValueError) as error:
        print(f'shop: {error.args[0] if error.args else error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
