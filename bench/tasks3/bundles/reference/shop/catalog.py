class CatalogError(KeyError):
    pass


PRODUCTS = {
    'MUG': ('Coffee mug', 1250),
    'TEE': ('T-shirt', 2499),
    'CAP': ('Cap', 1599),
    'BAG': ('Tote bag', 899),
}


def product(sku):
    try:
        return PRODUCTS[sku.upper()]
    except KeyError:
        raise CatalogError(f'unknown product {sku!r}')


def money(cents):
    sign = '-' if cents < 0 else ''
    cents = abs(cents)
    return f'{sign}{cents // 100}.{cents % 100:02d}'
