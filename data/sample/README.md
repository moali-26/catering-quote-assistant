# Sample Dataset (Lightweight Test Fixture)

A tiny, self-contained version of the primary dataset for fast unit tests and demos. It uses the same schema and item IDs as `data/menu.json`, so code can switch between the sample and the full dataset without changing.

## What's inside

| File | Contents |
| --- | --- |
| `menu.json` | 9 items, 15 variants, 6 categories |
| `rules.json` | Pickup, delivery, full service, delivery fee, tax, staffing |
| `capacity.json` | 3-date synthetic calendar |
| `inquiries.json` | 5 test inquiries + 1 hand-checked expected quote |

## What it exercises

- Per-person pricing (`pkg-pasta-duo`)
- Per-tray pricing with serving ranges (`salad-garden`, `side-garlic-mashed`)
- Per-platter pricing (`dessert-cookie-platter`)
- Multiple variants (`app-hummus`, `pan-breadsticks`)
- Listed allergens, `none` allergens, `unknown` allergens, and `depends_on_selection`
- Vegan, vegetarian, and gluten-sensitive tags
- Delivery minimums, delivery fee, tax, and full-service service charge
- Missing date, missing headcount, full capacity, and short lead time

## Run it

Use it exactly like the primary dataset:

```python
menu = json.load(open("data/sample/menu.json"))
rules = json.load(open("data/sample/rules.json"))
capacity = json.load(open("data/sample/capacity.json"))
```

Validate it:

```powershell
python data/sample/validate_sample.py
```

## Expected quote example

For `sample-inq-001` (40 guests, delivery, Culver City):

- 40 × Pasta Duo at $13.49 = $539.60
- 1 × full Garlic Mashed Potatoes = $83.69
- Food subtotal = $623.29
- Delivery = $50.00
- Tax at 11.25% = $75.75
- **Total = $749.04**
- Flag: Pasta Duo allergens depend on the pasta and salad selection.

That is under the $800 budget. It is one valid selection, not the only correct answer.

## Notes

- Prices and items are real, copied from the primary Stonefire dataset.
- Rules are simplified for testing; they are not the full production rules.
- Capacity is synthetic.
- Do not use this fixture for the final eval; use the full dataset for that.
