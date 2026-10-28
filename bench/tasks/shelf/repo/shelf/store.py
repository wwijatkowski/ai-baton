import json
from pathlib import Path

from .models import Item

FORMAT = 1


class StoreError(Exception):
    pass


class Store:
    """Items in a JSON file: {"format": 1, "items": [...]}. Names are unique, compared without case."""

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except ValueError as error:
            raise StoreError(f'{self.path} is not valid JSON: {error}')
        if data.get('format') != FORMAT:
            raise StoreError(f'{self.path}: unknown format {data.get("format")!r}')
        return [Item.from_dict(d) for d in data.get('items', [])]

    def save(self, items):
        self.path.write_text(json.dumps({'format': FORMAT, 'items': [i.to_dict() for i in items]}, indent=2) + '\n',
                             encoding='utf-8')

    def add(self, item):
        items = self.load()
        if any(i.name.lower() == item.name.lower() for i in items):
            raise StoreError(f'{item.name} is already on the shelf')
        items.append(item)
        self.save(items)

    def remove(self, name):
        items = self.load()
        kept = [i for i in items if i.name.lower() != name.lower()]
        if len(kept) == len(items):
            raise StoreError(f'{name} is not on the shelf')
        self.save(kept)
