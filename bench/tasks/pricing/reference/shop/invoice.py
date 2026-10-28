from .catalog import money

VAT_PERCENT = 23


def vat(net_cents):
    """VAT in cents, rounded half up."""
    return (net_cents * VAT_PERCENT + 50) // 100


def render(cart, discount=None):
    rows = [f'{qty} x {name} ({sku}) @ {money(unit)} = {money(total)}' for sku, name, qty, unit, total in cart.lines()]
    subtotal = cart.subtotal()
    rows.append(f'Subtotal: {money(subtotal)}')
    net = subtotal
    if discount is not None:
        off = discount.amount(subtotal)
        rows.append(f'Discount ({discount.code}): -{money(off)}')
        net -= off
    tax = vat(net)
    rows += [f'VAT {VAT_PERCENT}%: {money(tax)}', f'Total: {money(net + tax)}']
    return '\n'.join(rows)
