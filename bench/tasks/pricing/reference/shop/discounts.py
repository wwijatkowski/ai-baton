import json
from datetime import date
from pathlib import Path

from .catalog import money


class DiscountError(ValueError):
    pass


class Discount:
    def __init__(self, code, kind, value, min_subtotal=0, expires=None):
        if not isinstance(code, str) or not code.strip():
            raise DiscountError('a discount code needs a name')
        if kind not in ('percent', 'fixed') or not isinstance(value, int) or isinstance(value, bool):
            raise DiscountError(f'invalid discount {code!r}')
        if (kind == 'percent' and not 1 <= value <= 100) or (kind == 'fixed' and value < 1):
            raise DiscountError(f'invalid discount value for {code!r}')
        if not isinstance(min_subtotal, int) or min_subtotal < 0:
            raise DiscountError(f'invalid minimum for {code!r}')
        try:
            expires = None if expires is None else date.fromisoformat(expires).isoformat()
        except (TypeError, ValueError):
            raise DiscountError(f'invalid expiry for {code!r}')
        self.code, self.kind, self.value = code.strip().upper(), kind, value
        self.min_subtotal, self.expires = min_subtotal, expires

    def amount(self, subtotal):
        if self.kind == 'percent':
            return (subtotal * self.value + 50) // 100
        return min(self.value, subtotal)


def load_codes(path):
    path = Path(path)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [Discount(c['code'], c['kind'], c['value'], c.get('min_subtotal', 0), c.get('expires'))
            for c in data.get('codes', [])]


def find(codes, code, subtotal, today):
    wanted = code.strip().upper()
    for discount in codes:
        if discount.code == wanted:
            if discount.expires and today.isoformat() > discount.expires:
                raise DiscountError(f"discount code '{wanted}' expired on {discount.expires}")
            if subtotal < discount.min_subtotal:
                raise DiscountError(f"discount code '{wanted}' needs a subtotal of at least {money(discount.min_subtotal)}")
            return discount
    raise DiscountError(f"unknown discount code '{wanted}'")
