# Data Status — Catering Quote Assistant

> **Historical data status (October 18).** The web app and the evaluation use the frozen 22-item menu in `data/demo/` (see [data/demo/README.md](data/demo/README.md)). The original text is preserved as background.

**Oct 18, 2026 · Data workstream**

## TL;DR

The data layer is ready for the pricing engine and agent work. There are now **two real caterers**: a full primary dataset (American/BBQ) and a simplified second dataset (Korean). Both are anonymized in the UI and validated.

**Status: on track for the Monday data deliverable.** Cuisine coverage is now American/BBQ + Korean. Two is enough for Thursday; more can be added later.

## Snapshot

| Metric | Primary: Stonefire | Second: Gok Jee |
| --- | --- | --- |
| Cuisine | American / BBQ | Korean |
| Depth | Full | Simplified |
| Menu items | 67 | 91 |
| Priced variants | 98 | 91 |
| Categories | 12 | 18 |
| Price range | $1.99 – $255.00 | $5.00 – $1,090.00 |
| Vegan / vegetarian / gluten-sensitive | 5 / 15 / 9 | 0 / 2 / 0 |
| Allergens | 34 listed, 4 none, 9 unknown, 20 depends | All unknown |
| Validation | Passing | Passing |

## What is done

| File | What it is |
| --- | --- |
| `data/caterers.json` | Index of both caterer datasets for the app |
| `data/menu.json` | Primary 67 items with prices, serving sizes, dietary tags, allergens |
| `data/rules.json` | Primary minimums, lead times, tax, delivery, staffing, package rules |
| `data/assumptions.md` | Every primary assumption with a reason |
| `data/source-log.md` | Primary candidate caterers and provenance |
| `data/capacity.json` | Primary synthetic capacity calendar |
| `data/validate_dataset.py` | Primary dataset validator |
| `data/gokjee/menu.json` | Korean 91-item menu with tray prices and set menus |
| `data/gokjee/rules.json` | Korean minimums, tax, delivery, assumptions |
| `data/gokjee/assumptions.md` | Every Korean assumption with a reason |
| `data/gokjee/source-log.md` | Korean source and provenance |
| `data/gokjee/capacity.json` | Korean synthetic capacity calendar |
| `data/gokjee/validate_gokjee.py` | Korean dataset validator |
| `data/sample/` | Lightweight 9-item fixture with 5 test inquiries and a hand-checked quote |
| `data/raw/` | PDF and HTML proof for both sources |

## Sources

### Primary: Stonefire Grill, Torrance, CA

**Display name:** Sample Catering Co.

**Why:** publishes item prices, serving sizes, per-person packages, vegan/vegetarian/gluten-sensitive markers, an allergen table, minimums, and lead times. About 15 miles from Culver City.

**Rejected candidates**

- **Brent's Deli** — real LA deli with serving sizes and minimums, but no public catering prices.
- **Mendocino Farms** — catering page returned HTTP 403 during capture; prices could not be verified.
- **ezCater / Zerocater** — ordering platforms, not one caterer's published menu.

### Second: Gok Jee Foods, Koreatown, Los Angeles

**Display name:** Koreatown Catering Co.

**Why:** real Korean caterer with public tray prices, set menus for 5/10/20 people, and a downloadable PDF. Adds cuisine variety without changing the primary quote flow.

**Source access:** the site is HTTP-only and loads the menu through an AJAX endpoint. The saved `menuform` HTML is the parsing source; the rendered PDF is the visual proof.

## What is real vs. assumed

| Data | Primary | Second |
| --- | --- | --- |
| Item names, prices, serving sizes | Real, captured 2026-10-18 | Real, captured 2026-10-18 |
| Dietary tags | Real (V, VT, GF) | Only explicit veg. items |
| Allergens | Real where the table has a row | Unknown, no table published |
| Order minimums and lead times | Real, published | Assumed |
| Tax rates | Real (CDTFA, effective 2026-10-01) | Same rates, by delivery address |
| Delivery fee and radius | Assumption | Assumption |
| Service charge and staffing | Assumption | None / assumed |
| Capacity calendar | Synthetic | Synthetic |

## Rules captured

### Primary

- Pickup: 10-guest minimum.
- Delivery: 20-guest minimum **and** $400 subtotal minimum.
- Full service: 30-guest minimum.
- Dine-in: 20-guest minimum.
- Delivery lead time: 48 hours.
- Full service: one week notice, final order 48 hours before the event.
- Boxed meals: minimum 10 per selection, 48 hours notice.
- Tax: Culver City 11.25%, Torrance 10.75%.
- Children under 10: two children count as one adult.

### Second

- Set menus: 5, 10, and 20 people.
- Minimum: 5 guests (assumption based on the smallest set menu).
- Lead time: 48 hours (assumption).
- Delivery fee: $50 flat within 15 miles, then $2.50/mile to 25 miles (assumption).
- No service charge.
- Utensils: $5 per 10 people (published).
- Tax: same delivery-address rates as the primary dataset.

## Caveats the group must know

1. **GF means gluten-sensitive, not gluten-free.** The primary caterer says it has no gluten-free items.
2. **Gok Jee publishes no allergen table.** Every item is unknown; any allergy request must be flagged for caterer confirmation.
3. **Gok Jee dietary tags are minimal.** Only two items are explicitly vegetarian.
4. **Package and boxed-meal allergens depend on selections.** They need confirmation.
5. **Unknown allergens are not “none.”** Nine primary items and all Korean items are unknown.
6. **Assumptions are documented.** See both `assumptions.md` files.
7. **Prices are snapshot-dated.** They can change.

## Cuisine coverage

**Current:** American/BBQ + Korean. That is enough variety for Thursday.

**Recommendation:** freeze these two for the demo. Adding a third cuisine means another transcription pass, another rule set, and more eval cases. If the group wants more, add it after Thursday.

Possible next cuisines: Mexican, Italian, Mediterranean, Chinese, Indian. Chains are more likely to publish prices and serving sizes; local one-location caterers often hide them.

## Review in 10 minutes

1. Spot-check five Stonefire prices against `data/raw/stonefire-torrance-catering-menu-2026-10-18.pdf`.
2. Spot-check five Gok Jee prices against `data/raw/gokjee-catering-menu-list-2026-10-18.pdf`.
3. Read both `assumptions.md` files.
4. Run:
   ```powershell
   python data/validate_dataset.py
   python data/gokjee/validate_gokjee.py
   python data/sample/validate_sample.py
   ```
5. Confirm the two-dataset decision.

## How to share this

- Share the private GitHub repo: https://github.com/moali-26/catering-quote-assistant
- Or share this file plus the `data/` folder.
- Or use the zip at `Catering-Data-Package-2026-10-18.zip`.
