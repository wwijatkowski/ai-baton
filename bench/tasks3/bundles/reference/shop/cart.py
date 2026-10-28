import json
from pathlib import Path

from .catalog import product


class Cart:
    """{sku: quantity}, kept in a JSON file."""

    def __init__(self, path):
        self.path = Path(path)
        self.items = json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self):
        self.path.write_text(json.dumps(self.items, indent=2, sort_keys=True) + '\n')

    def add(self, sku, qty=1):
        product(sku)  # Unknown products are refused.
        if qty < 1:
            raise ValueError('quantity must be at least 1')
        self.items[sku.upper()] = self.items.get(sku.upper(), 0) + qty

    def remove(self, sku):
        self.items.pop(sku.upper(), None)

    def lines(self):
        """[(sku, name, qty, unit cents, line cents)] sorted by sku."""
        out = []
        for sku in sorted(self.items):
            name, price = product(sku)
            out.append((sku, name, self.items[sku], price, price * self.items[sku]))
        return out

    def subtotal(self):
        return sum(line[4] for line in self.lines())
