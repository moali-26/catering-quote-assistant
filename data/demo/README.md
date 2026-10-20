# Frozen Demo Menu (Part A)

The supported menu for the demo and final evaluation: **22 items, 37 variants, 8 categories**, taken from the full primary dataset (`data/menu.json`). Use this instead of `data/sample/` (development only) or the full 67-item menu.

```sh
python3 data/demo/build_demo.py      # regenerate from data/menu.json
python3 data/demo/validate_demo.py   # provenance + engine + coverage checks
python3 -m unittest tests.test_demo_dataset -v
```

## Files

| File | Contents |
| --- | --- |
| `menu.json` | 22-item subset. IDs, prices, serving sizes, dietary tags, allergens copied unchanged from `data/menu.json` |
| `rules.json` | Copied unchanged from `data/rules.json` |
| `capacity.json` | Copied unchanged from `data/capacity.json` (synthetic) |
| `build_demo.py` | Builds the three files; the item list lives in `DEMO_ITEM_IDS` |
| `validate_demo.py` | Fails if anything drifts from the source or breaks the quote engine |

## What's on the menu

| Category | Items |
| --- | --- |
| Appetizers | Hummus, Chicken Tenders, Fruit Platter |
| Catering Packages | The Pasta Duo, Classic Package |
| A La Carte Pans | Tri-Tip, Pulled Pork, Chicken Breast, Breadsticks |
| Pastas | Marinara, Mac & Cheese, Pesto |
| Salads | Garden, Caesar, Cobb |
| Sides | Garlic Mashed, Coleslaw, Roasted Vegetables, Cornbread |
| Desserts | Cookie Platter, Brownie |
| Beverages | Sodas & Water |

Chosen so the demo can show: real protein mains with serving sizes; at least 6 vegetarian-friendly and 2 vegan items; every allergen status (`listed`, `listed_none`, `unknown`, `depends_on_selection`); and a nut-allergy swap (Cookie Platter lists peanut and tree nuts, Brownie does not). All 9 `data/sample` items are included, so the sample inquiries still work.

Left out: boxed meals (extra per-selection rules), package add-ons and "add protein to any pan" (depend on other items), wraps and the other packages (overlap with chosen items).

## Decisions

- **Rules:** the full dataset's published values: delivery needs 20 guests **and** a $400 food subtotal; delivery fee $65 within 15 miles (assumption). The sample's $300 / $50 values are not used.
- **Capacity:** synthetic calendar. After the Oct 22 presentation: Oct 24 and Oct 31 are fully booked (conflict demo); Oct 30 and Nov 6 have room.
- **Display names:** "SFG Classic" is shown as "Classic Package"; `source_name` keeps the original for provenance. Item IDs still contain `sfg`; they are internal and never shown to customers.
- `meta.dataset_id` matches the full dataset, so the full capacity calendar applies. The engine refuses to mix this menu with `data/sample/rules.json`.

## Schema for B, C and D

| Field | Owner can edit? | Notes |
| --- | --- | --- |
| `items[].id`, `variants[].id` | **No** | Referenced by saved quotes, AI tool calls and tests |
| `items[].name`, `description` | Yes | Shown to customers and the AI |
| `variants[].price` | Yes | Positive USD number. New quotes use it; saved quotes keep their snapshot |
| `items[].available`, `variants[].available` | Yes | `false` hides it from `search_menu` and the engine rejects it |
| `variants[].pricing_unit` | **No** | `per_person`, `per_tray`, `per_platter`, `each` |
| `serves`, `serves_text` | Not in the minimum build | Used by the AI to choose quantities |
| `dietary_tags`, `allergens`, `allergen_status` | Not in the minimum build | Safety data; changes should be reviewed |
| `category` | No | Must match a `categories[].name` |

## Still to do (Part A)

- **Owner menu editing** is not built yet: needs a Supabase menu table (with D) and edit functions that enforce the table above. `tests/test_demo_dataset.py` already proves a price edit changes new quotes but not saved ones.
- **Final evaluation inquiries** based on this menu (with E). The 5 sample inquiries are development data.
- Once menu editing is live, the database becomes the source of truth; re-running `build_demo.py` overwrites `data/demo/*.json`.
