Hi! We want product bundles in the shop: some products sell together for less.

1. The bundles (fixed for now):
   - `STARTER`, "Starter pack": 1 MUG + 1 TEE for 32.99
   - `TRAVEL`, "Travel set": 1 CAP + 1 BAG for 20.99
   A bundle's saving is the sum of its products' prices minus the bundle price.

2. Part 1 (please do this now): a new module `shop/bundles.py` with `BUNDLES` (code -> name, components
   `{sku: qty}`, price in cents), `apply_bundles(items)` and `bundle_savings(code)` (cents). `apply_bundles` takes the
   cart's `{sku: qty}` and returns `(bundles, rest)`: `bundles` is `{code: how many}` and `rest` the items left over
   (no zero quantities). Bundles are applied in alphabetical order of their codes, each as many times as the items
   allow. With tests.

3. Part 2 (later, in another conversation): use bundles on the invoice and the command line.
   - `invoice` applies bundles by default. Bundle lines come first, sorted by code, like product lines:
     `1 x Starter pack (STARTER) @ 32.99 = 32.99`; then the remaining products as today. Subtotal, VAT and Total are
     computed from these lines as today.
   - `invoice --no-bundles` prints the invoice exactly as it is today, without bundles.
   - A new command `bundles` lists them, one line each, sorted by code:
     `STARTER  Starter pack: MUG + TEE  32.99 (save 4.50)` (components as SKUs joined with " + ", sorted).
   - README and tests updated.

Thanks!
