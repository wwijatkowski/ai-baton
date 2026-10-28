from .catalog import product

BUNDLES = {
    'STARTER': ('Starter pack', {'MUG': 1, 'TEE': 1}, 3299),
    'TRAVEL': ('Travel set', {'CAP': 1, 'BAG': 1}, 2099),
}


def apply_bundles(items):
    rest = {sku.upper(): qty for sku, qty in items.items() if qty}
    bundles = {}
    for code in sorted(BUNDLES):
        components = BUNDLES[code][1]
        times = min(rest.get(sku, 0) // qty for sku, qty in components.items())
        if times:
            bundles[code] = times
            for sku, qty in components.items():
                rest[sku] -= qty * times
    return bundles, {sku: qty for sku, qty in rest.items() if qty}


def bundle_savings(code):
    name, components, price = BUNDLES[code]
    return sum(product(sku)[1] * qty for sku, qty in components.items()) - price
