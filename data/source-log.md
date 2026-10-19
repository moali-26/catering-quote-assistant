# Source Log

Captured 2026-10-18. This file records the real business source behind the anonymized demo brand.

## Selected: Stonefire Grill (Torrance, CA)

**Display name:** Sample Catering Co.

**Why it won:** it meets every data-quality criterion in the handoff. The Torrance catering menu publishes item prices, serving sizes, per-person package pricing, dietary markers, and a separate allergen table. The catering page and FAQ publish order minimums, lead time, and service inclusions.

**Location:** Torrance, CA. About 15 miles from the Culver City scenario, so delivery is plausible.

**Source URLs**

- Menu: https://www.stonefiregrill.com/location/torrance/ca/catering-menu/
- Catering services: https://www.stonefiregrill.com/catering/
- Catering FAQ: https://www.stonefiregrill.com/contact/faqs/?faq_cat=catering
- Allergens: https://www.stonefiregrill.com/allergen-info/
- Nutrition: https://www.stonefiregrill.com/nutritional-info/

**Proof saved**

- `data/raw/stonefire-torrance-catering-menu-2026-10-18.pdf` (full menu)
- `data/raw/stonefire-catering-faq-2026-10-18.pdf` (minimums, lead time, inclusions)
- `data/raw/stonefire-allergen-info-2026-10-18.pdf` (allergen table)
- Matching `.html` snapshots in `data/raw/`

**What is real:** item names, descriptions, prices, serving sizes, dietary markers, published minimums, published lead times, service inclusions, payment policy, allergen rows.

**What is assumed:** delivery fee, delivery radius, full-service service charge, staffing rate, pickup lead time, tax base. See `assumptions.md`.

**Known caveats**

- It is a small CA chain, not a one-location caterer. The handoff allows a chain fallback when local menus do not publish prices and serving sizes.
- The FAQ and catering page disagree on the delivery minimum: 20 guests vs $400. Both are enforced.
- GF means gluten-sensitive, not gluten-free.
- Package and boxed-meal allergens depend on selections.

## Rejected: Brent's Delicatessen (Northridge / Westlake Village, CA)

**URL:** https://brentsdeli.com/catering/

**Why rejected:** the catering page publishes serving sizes, tray sizes, and minimums, but almost no catering prices. Pricing is handled through the online ordering platform, so the public menu fails the "has prices" criterion.

**Still useful for:** realistic synthetic inquiry language (deli trays, minimum of 10, one-day notice).

## Rejected: Mendocino Farms (Los Angeles, CA)

**URL:** https://www.mendocinofarms.com/catering/

**Why rejected:** the catering page returned HTTP 403 during capture, so public prices and serving sizes could not be verified. Not selected.

## Rejected: ezCater / Zerocater aggregators

**Why rejected:** these are ordering platforms, not one caterer's published menu. Prices can vary by platform, location, and order size. Using them would weaken the "real business data" claim.

## Why one caterer instead of a multi-caterer database

The handoff's data plan is explicit: one caterer's public menu, with source URL and capture date. A multi-caterer database adds normalization work, makes the "real data" story harder to defend, and is out of scope before Thursday. The schema is multi-caterer-ready: add another item set with its own `meta.source` and `dataset_id`.

## Still to confirm with the caterer (non-blocking)

- Delivery fee and radius
- Full-service service charge and staffing rate
- Cancellation policy
- Whether delivery and service charges are taxable in their invoicing
