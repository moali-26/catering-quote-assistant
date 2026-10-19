# Data Status — Catering Quote Assistant

**Oct 18, 2026 · Data workstream**

## TL;DR

The data layer is ready for the pricing engine and agent work. One real caterer's menu and rules are transcribed, anonymized in the UI, and validated.

**Status: on track for the Monday data deliverable.** One open decision remains: whether to add more cuisines before Thursday.

## Snapshot

| Metric | Value |
| --- | --- |
| Menu items | 67 |
| Priced variants | 98 |
| Categories | 12 |
| Price range | $1.99 – $255.00 |
| Vegan items | 5 |
| Vegetarian items | 15 |
| Gluten-sensitive items | 9 |
| Allergens listed | 34 items |
| Allergens none listed | 4 items |
| Allergens unknown | 9 items |
| Allergens depend on selection | 20 items |
| Validation | Passing (`python data/validate_dataset.py`) |

## What is done

| File | What it is |
| --- | --- |
| `data/menu.json` | 67 items with prices, serving sizes, dietary tags, allergens, and source provenance |
| `data/rules.json` | Minimums, lead times, tax, delivery, staffing, package rules, assumptions |
| `data/assumptions.md` | Every invented value with a one-line reason |
| `data/source-log.md` | Candidate caterers, selected source, real vs. assumed data |
| `data/capacity.json` | Synthetic capacity calendar with open/full/closed dates |
| `data/raw/` | PDF and HTML proof snapshots of the menu, FAQ, and allergen table |
| `data/parse_allergens.py` | Rebuilds `allergens.json` from the saved allergen page |
| `data/validate_dataset.py` | Checks JSON structure, pricing fields, allergens, rules, and capacity |

## Source decision

**Selected:** Stonefire Grill, Torrance, CA. Displayed in the app as **Sample Catering Co.**

**Why:** it publishes everything the quote needs: item prices, serving sizes, per-person packages, vegan/vegetarian/gluten-sensitive markers, an allergen table, order minimums, and lead times. It is about 15 miles from the Culver City scenario, so delivery is plausible.

**Other candidates**

- **Brent's Deli** — real LA deli with serving sizes and minimums, but no public catering prices. Rejected.
- **Mendocino Farms** — catering page returned HTTP 403 during capture. Could not verify prices. Rejected.
- **ezCater / Zerocater** — ordering platforms, not one caterer's published menu. Rejected.

## What is real vs. assumed

| Data | Status |
| --- | --- |
| Item names, descriptions, prices, serving sizes | Real, captured 2026-10-18 |
| Dietary tags | Real (V, VT, GF) |
| Allergens | Real where the allergen table has a row |
| Order minimums and lead times | Real, published |
| Tax rates | Real (CDTFA, effective 2026-10-01) |
| Delivery fee and radius | Assumption |
| Full-service service charge and staffing | Assumption |
| Pickup lead time | Assumption |
| Capacity calendar | Synthetic |

## Rules captured

- Pickup: 10-guest minimum.
- Delivery: 20-guest minimum **and** $400 subtotal minimum.
- Full service: 30-guest minimum.
- Dine-in: 20-guest minimum.
- Delivery lead time: 48 hours.
- Full service: one week notice, final order 48 hours before the event.
- Boxed meals: minimum 10 per selection, 48 hours notice.
- Tax: Culver City 11.25%, Torrance 10.75%.
- Children under 10: two children count as one adult.

## Caveats the group must know

1. **GF means gluten-sensitive, not gluten-free.** The caterer says it has no gluten-free items. The code should never promise gluten-free.
2. **Package and boxed-meal allergens depend on selections.** They are marked `depends_on_selection` and need confirmation.
3. **Unknown allergens stay unknown.** Nine items have no matching allergen row; never treat them as allergen-free.
4. **Delivery fee, service charge, staffing, and pickup lead time are assumptions.** They are documented and easy to challenge.
5. **Prices are Torrance-only and snapshot-dated.** The source says pricing is valid for Torrance; prices can change.
6. **One caterer, not a multi-cuisine database.** See the decision below.

## Open decision: cuisine variety

**Current state:** one caterer. That follows the handoff's data plan and keeps the "real data" story clean.

**Your preference:** a few different cuisine genres. That is reasonable, but it changes scope. Here are the options.

### Option A — One primary caterer (recommended)

Keep Stonefire for the end-to-end quote and eval. Add cuisine variety later as a read-only "menu showcase" if time allows. Lowest risk, strongest provenance.

### Option B — Add 2–3 real caterers now

Add one menu per cuisine, each with its own `meta.source`, prices, allergens, and rules. The user or agent must choose a caterer first. This needs 2–3 more transcription passes and a caterer-selection step. Realistic cuisines to verify: Mexican, Italian, Mediterranean, Chinese, Indian.

**Cost:** several hours, more eval cases, more edge cases. **Risk:** medium.

### Option C — Synthetic cuisine variants

Change names or invent dishes to fake variety. **Not recommended.** It weakens the "is this fake data?" answer and creates work without real provenance.

**Recommendation:** Option A for Thursday; Option B after the demo if the group wants to keep building.

## Review in 10 minutes

1. Open `data/menu.json` and spot-check five prices against `data/raw/stonefire-torrance-catering-menu-2026-10-18.pdf`.
2. Open `data/rules.json` and confirm the minimums and lead times.
3. Read `data/assumptions.md`.
4. Run `python data/validate_dataset.py`.
5. Decide Option A, B, or C above.

## How to share this

- Share this file plus the `data/` folder.
- Or push the repo to GitHub and send the link.
- Or paste this file into Slack/Notion.
- A ready-to-send zip is at `Catering-Data-Package-2026-10-18.zip`.
