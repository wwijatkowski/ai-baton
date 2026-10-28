import argparse
import sys

from . import report
from .models import Item
from .store import Store, StoreError


def main(argv=None):
    parser = argparse.ArgumentParser(prog='shelf')
    parser.add_argument('--file', default='shelf.json')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('add')
    p.add_argument('name')
    p.add_argument('--quantity', type=int, default=1)
    p.add_argument('--location', default='')
    p = sub.add_parser('remove')
    p.add_argument('name')
    sub.add_parser('list')
    sub.add_parser('report')
    args = parser.parse_args(argv)
    store = Store(args.file)
    try:
        if args.command == 'add':
            store.add(Item(args.name, args.quantity, args.location))
        elif args.command == 'remove':
            store.remove(args.name)
        elif args.command == 'list':
            for item in sorted(store.load(), key=lambda i: i.name.lower()):
                print(f'{item.name}\t{item.quantity}\t{item.location}')
        elif args.command == 'report':
            print(report.by_location(store.load()))
    except StoreError as error:
        print(f'shelf: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
