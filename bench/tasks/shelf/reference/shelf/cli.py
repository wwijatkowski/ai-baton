import argparse
import sys

from . import report
from .models import Item, TagError, normalize_tags
from .store import Store, StoreError


def main(argv=None):
    parser = argparse.ArgumentParser(prog='shelf')
    parser.add_argument('--file', default='shelf.json')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('add')
    p.add_argument('name')
    p.add_argument('--quantity', type=int, default=1)
    p.add_argument('--location', default='')
    p.add_argument('--tag', action='append', default=[])
    for name in ('tag', 'untag'):
        p = sub.add_parser(name)
        p.add_argument('name')
        p.add_argument('tags', nargs='+')
    p = sub.add_parser('remove')
    p.add_argument('name')
    p = sub.add_parser('list')
    p.add_argument('--tag', action='append', default=[])
    p = sub.add_parser('report')
    p.add_argument('--by', choices=('location', 'tag'), default='location')
    args = parser.parse_args(argv)
    store = Store(args.file)
    try:
        if args.command == 'add':
            store.add(Item(args.name, args.quantity, args.location, tags=args.tag))
        elif args.command in ('tag', 'untag'):
            items = store.load()
            item = store.find(items, args.name)
            change = set(normalize_tags(args.tags))
            item.tags = normalize_tags(set(item.tags) | change if args.command == 'tag' else set(item.tags) - change)
            store.save(items)
        elif args.command == 'remove':
            store.remove(args.name)
        elif args.command == 'list':
            wanted = set(normalize_tags(args.tag))
            for item in sorted(store.load(), key=lambda i: i.name.lower()):
                if wanted <= set(item.tags):
                    print(f'{item.name}\t{item.quantity}\t{item.location}\t{",".join(item.tags)}')
        elif args.command == 'report':
            print((report.by_tag if args.by == 'tag' else report.by_location)(store.load()))
    except (StoreError, TagError) as error:
        print(f'shelf: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
