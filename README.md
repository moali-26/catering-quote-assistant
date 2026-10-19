# Catering Quote Assistant — Data Layer

**Status: Oct 18, 2026.** Data workstream is on track for the Monday deliverable. The repo now has **two real caterers**: a full primary dataset and a simplified Korean dataset. Keep the repo private because it contains real source names and provenance.

## What was done

- Built the data layer first, because the pricing engine and agent both depend on it.
- **Primary:** Stonefire Grill, Torrance, CA. Display alias **Sample Catering Co.** Full menu, prices, serving sizes, dietary tags, allergens, minimums, and lead times.
- **Second:** Gok Jee Foods, Koreatown, Los Angeles. Display alias **Koreatown Catering Co.** Simplified Korean menu with 91 items, set menus, and tray prices.
- Captured PDF and HTML proof for both sources.
- Added synthetic capacity calendars and validators for both datasets.

## Current datasets

| Caterer | Cuisine | Depth | Items | Variants | Notes |
| --- | --- | --- | --- | --- | --- |
| Stonefire Grill | American / BBQ | Full | 67 | 98 | Allergen table, full rules |
| Gok Jee Foods | Korean | Simplified | 91 | 91 | No allergen table, minimal rules |

### Primary dataset: Stonefire Grill

| Metric | Value |
| --- | --- |
| Price range | $1.99 – $255.00 |
| Vegan / vegetarian / gluten-sensitive | 5 / 15 / 9 |
| Allergens listed / none / unknown / depends on selection | 34 / 4 / 9 / 20 |

**Published rules:** pickup 10-guest minimum, delivery 20-guest + $400 minimum, full service 30-guest minimum, delivery 48-hour notice, full service one-week notice, boxed meals 10 per selection and 48 hours, Culver City 11.25% / Torrance 10.75% tax.

### Second dataset: Gok Jee Foods

| Metric | Value |
| --- | --- |
| Price range | $5.00 – $1,090.00 |
| Categories | 18 |
| Set menus | 5, 10, and 20 people |
| Vegetarian items | 2, explicitly labeled |
| Allergens | Unknown for every item |
| Estimated serving sizes | 35 piece-count or per-pound items |

**Published details:** tray prices, set-menu sizes and contents, $5 per 10 people utensil add-on, prices exclude tax.

## Key caveats

1. **GF means gluten-sensitive, not gluten-free.** The primary caterer says it has no gluten-free items.
2. **Gok Jee publishes no allergen table.** Every item is `unknown`; any allergy request must be flagged for caterer confirmation.
3. **Gok Jee dietary tags are minimal.** Only two items are explicitly vegetarian. Do not assume the rest.
4. **Package and boxed-meal allergens depend on selections.** They need caterer confirmation.
5. **Prices are snapshot-dated and location-specific.** Stonefire prices are Torrance-only; Gok Jee prices are from its online menu.
6. **Assumptions are documented.** See `data/assumptions.md` and `data/gokjee/assumptions.md`.

## How to use it

```powershell
python data/validate_dataset.py
python data/gokjee/validate_gokjee.py
python data/sample/validate_sample.py
```

Load `data/menu.json` and `data/rules.json` for the primary dataset. Load `data/gokjee/menu.json` and `data/gokjee/rules.json` for the Korean dataset. Use `meta.branding.display_name` in the UI, not `source.business_name`.

### Lightweight sample fixture

`data/sample/` is a fast test version of the primary dataset: 9 items, 15 variants, simplified rules, a 3-date capacity calendar, 5 inquiries, and one hand-checked expected quote. It uses the same item/variant IDs as the full dataset, so tests can switch between them. Use it for unit tests and demos; use the full dataset for the final eval.

## How we go from here

| When | Owner | Task |
| --- | --- | --- |
| Mon | Data | Freeze the menu/rules schema for both datasets |
| Mon night | Pricing | Build the deterministic engine against the primary dataset; add a caterer switch |
| Tue midday | Agent | Extraction schema, clarification logic, and menu-selection tool calls |
| Tue | Data | Draft 30–50 synthetic inquiries with answer keys |
| Wed night | UI + eval | Streamlit approve/edit step, eval run, results table, slides |

## Cuisine coverage

Current coverage is **American/BBQ + Korean**. That is enough variety for Thursday. Adding more cuisines means another transcription pass, another rule set, and more eval cases. Recommendation: freeze these two for the demo and add a third after Thursday if the group wants to keep building.

## Files

- `data/caterers.json` — index of both caterer datasets for the app
- `data/menu.json` — primary items, variants, dietary tags, allergens
- `data/rules.json` — primary minimums, lead times, tax, delivery, staffing
- `data/assumptions.md` — primary assumptions
- `data/source-log.md` — primary candidate and provenance notes
- `data/capacity.json` — primary synthetic availability
- `data/gokjee/menu.json` — Korean items, prices, set menus
- `data/gokjee/rules.json` — Korean minimums, tax, delivery
- `data/gokjee/assumptions.md` — Korean assumptions
- `data/gokjee/source-log.md` — Korean source and provenance
- `data/gokjee/capacity.json` — Korean synthetic availability
- `data/raw/` — PDF/HTML proof for both sources
- `data/sample/menu.json` — 9-item lightweight fixture
- `data/sample/rules.json` — simplified test rules
- `data/sample/capacity.json` — 3-date test calendar
- `data/sample/inquiries.json` — 5 test inquiries + expected quote
- `data/sample/validate_sample.py` — fixture validator
- `data/validate_dataset.py` — primary validator
- `data/gokjee/validate_gokjee.py` — Korean validator
- `DATA_STATUS.md` — longer status writeup
