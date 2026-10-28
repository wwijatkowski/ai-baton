from .bundles import BUNDLES, apply_bundles
from .catalog import money, product

VAT_PERCENT = 23


def vat(net_cents):
    """VAT in cents, rounded half up."""
    return (net_cents * VAT_PERCENT + 50) // 100


def render(cart, bundles=True):
    if bundles:
        found, rest = apply_bundles(cart.items)
        lines = [(code, BUNDLES[code][0], n, BUNDLES[code][2], BUNDLES[code][2] * n) for code, n in sorted(found.items())]
        lines += [(sku, product(sku)[0], qty, product(sku)[1], product(sku)[1] * qty) for sku, qty in sorted(rest.items())]
    else:
        lines = cart.lines()
    rows = [f'{qty} x {name} ({sku}) @ {money(unit)} = {money(total)}' for sku, name, qty, unit, total in lines]
    subtotal = sum(line[4] for line in lines)
    tax = vat(subtotal)
    rows += [f'Subtotal: {money(subtotal)}', f'VAT {VAT_PERCENT}%: {money(tax)}', f'Total: {money(subtotal + tax)}']
    return '\n'.join(rows)
