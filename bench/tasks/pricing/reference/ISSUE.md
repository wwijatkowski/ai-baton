# Discount codes

Customers can enter a discount code when the invoice is made.

## Requirements
1. A new module `shop/discounts.py` with `Discount(code, kind, value, min_subtotal=0, expires=None)`: `kind` is
   `percent` (`value` a whole number 1-100) or `fixed` (`value` in cents, at least 1); `min_subtotal` in cents;
   `expires` an ISO date (the code works through that day) or `None`. Codes are stored in upper case. Anything else
   raises `DiscountError`.
2. `load_codes(path)` reads `{"codes": [{"code": ..., "kind": ..., "value": ..., "min_subtotal": ..., "expires": ...}]}`
   (optional keys may be missing); a missing file means no codes.
3. `find(codes, code, subtotal, today)` returns the matching `Discount` (code compared without case) or raises
   `DiscountError` with exactly one of these messages:
   `unknown discount code 'X'`, `discount code 'X' expired on YYYY-MM-DD`,
   `discount code 'X' needs a subtotal of at least A.BB` (X as the user typed it upper-cased; A.BB as `money()` writes it).
4. `Discount.amount(subtotal)` in cents: percent rounded half up to a cent; fixed, but never more than the subtotal.
5. `invoice --code CODE [--codes FILE] [--today YYYY-MM-DD]` (`--codes` defaults to `codes.json`, `--today` to today)
   applies the code: after the `Subtotal:` line a line `Discount (CODE): -A.BB`; VAT is computed on the subtotal minus
   the discount; `Total:` is that net amount plus VAT.
6. A code that cannot be used is an error: `shop: <message from 3>`, exit code 1, no invoice printed.
7. Without `--code` the invoice is unchanged.
8. Tests for all of the above; README updated.

## Work split
- Part 1: requirements 1 to 4 (the discounts module), with tests.
- Part 2: requirements 5 to 8 (invoice and command line).
