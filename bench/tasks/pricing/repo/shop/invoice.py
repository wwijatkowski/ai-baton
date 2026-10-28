from .catalog import money

VAT_PERCENT = 23


def vat(net_cents):
    """VAT in cents, rounded half up."""
    return (net_cents * VAT_PERCENT + 50) // 100


def render(cart):
    rows = [f'{qty} x {name} ({sku}) @ {money(unit)} = {money(total)}' for sku, name, qty, unit, total in cart.lines()]
    subtotal = cart.subtotal()
    tax = vat(subtotal)
    rows += [f'Subtotal: {money(subtotal)}', f'VAT {VAT_PERCENT}%: {money(tax)}', f'Total: {money(subtotal + tax)}']
    return '\n'.join(rows)
