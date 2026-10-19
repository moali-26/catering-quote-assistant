# Catering Quote Assistant — Data Layer

**Status: Oct 18, 2026.** Data workstream is on track for the Monday deliverable. This repo is private because it keeps the real source name and provenance notes for the demo.

## What was done

- Read the project handoff and built the data layer first, because the pricing engine and agent both depend on it.
- Selected **one real caterer**: Stonefire Grill, Torrance, CA. The app displays the alias **Sample Catering Co.**
- Transcribed the public catering menu and rules into structured JSON.
- Captured PDF and HTML proof of the menu, FAQ, and allergen table.
- Added a synthetic capacity calendar and a validator that checks the whole dataset.
- Wrote `DATA_STATUS.md` with the full status, caveats, and the cuisine-variety decision.

## Current dataset

| Item | Count |
| --- | --- |
| Menu items | 67 |
| Priced variants | 98 |
| Categories | 12 |
| Vegan / vegetarian / gluten-sensitive | 5 / 15 / 9 |
| Allergens listed / none listed / unknown / depends on selection | 34 / 4 / 9 / 20 |
| Price range | $1.99 – $255.00 |

**Published rules captured:** pickup 10-guest minimum, delivery 20-guest + $400 minimum, full service 30-guest minimum, delivery 48-hour notice, full service one-week notice, boxed meals 10 per selection and 48 hours, Culver City 11.25% / Torrance 10.75% tax.

**Assumptions:** delivery fee and radius, full-service service charge and staffing, pickup lead time, tax base. All are listed with reasons in `data/assumptions.md`.

## Key caveats

1. **GF means gluten-sensitive, not gluten-free.** The caterer says it has no gluten-free items.
2. **Package and boxed-meal allergens depend on selections.** They need caterer confirmation.
3. **Unknown allergens are not “none.”** Nine items have no matching allergen row.
4. **One caterer, not a multi-cuisine database.** See the open decision below.
5. **Prices are Torrance-only and captured 2026-10-18.** They can change.

## How to use it

```powershell
python data/validate_dataset.py
```

Load `data/menu.json` for items and prices, `data/rules.json` for minimums and fees, and `data/capacity.json` for availability. Use `branding.display_name` in the UI, not `source.business_name`.

## How we go from here

| When | Owner | Task |
| --- | --- | --- |
| Mon | Data | Freeze the menu/rules schema and decide the cuisine strategy |
| Mon night | Pricing | Build the deterministic engine against `menu.json` + `rules.json`; unit-test hand-checked examples |
| Tue midday | Agent | Extraction schema, clarification logic, and menu-selection tool calls |
| Tue | Data | Draft 30–50 synthetic inquiries with answer keys |
| Wed night | UI + eval | Streamlit approve/edit step, eval run, results table, slides |

## Open decision: cuisine variety

We currently support **one caterer**. The handoff asks for one real menu, and most local LA caterers do not publish prices. The schema is multi-caterer-ready, but adding cuisines means more transcription, more rules, and a “choose a caterer” step.

- **Option A (recommended):** keep one primary caterer for Thursday; add other cuisines as a read-only menu showcase after the demo.
- **Option B:** add 2 real caterers now (for example Mexican + Italian/Mediterranean), each with its own dataset and rules.
- **Option C:** synthetic cuisine variants. Not recommended; it weakens the real-data story.

## Files

- `data/menu.json` — items, variants, dietary tags, allergens
- `data/rules.json` — minimums, lead times, tax, delivery, staffing
- `data/assumptions.md` — every invented value and why
- `data/source-log.md` — candidate caterers and provenance
- `data/capacity.json` — synthetic availability calendar
- `data/raw/` — PDF/HTML proof snapshots
- `data/parse_allergens.py` — allergen-table parser
- `data/validate_dataset.py` — dataset validator
- `DATA_STATUS.md` — longer status writeup
