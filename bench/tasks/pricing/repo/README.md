# shop

A small cart and invoice tool: `python -m shop.cli add MUG --qty 2`, `remove MUG`, `invoice`. The cart lives in
`cart.json` (`--cart`). Prices in cents; VAT 23%, rounded half up. Tests: `python -m unittest discover -s tests`.
