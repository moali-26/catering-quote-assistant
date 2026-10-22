# Assumptions

Every non-published value used by the pricing engine or constraint checks. Each line names the reason so it can be defended in Q&A.

This file covers the **primary Stonefire dataset**.

## Data provenance

- **One real caterer is the primary source of truth.** Stonefire Grill's Torrance catering menu is real and captured 2026-10-18. The app displays the alias **Sample Catering Co.**; the real business name and source URLs stay in `menu.json` and `source-log.md` for provenance. Reason: the handoff requires one real menu, not a synthetic blend.
- **Prices are Torrance-only.** The source menu explicitly says "Menu pricing is valid for Torrance only." Reason: using another location's prices would be invented data.
- **Menu prices can change.** The dataset is a snapshot, not a live price feed. Reason: the source has no API and the project deadline is four days.

## Pricing rules

- **Delivery fee: $65 flat within 15 miles, then $2.50 per mile up to 25 miles.** The caterer does not publish a delivery fee. Reason: a quote needs a deterministic delivery line, and this is a simple LA-area model.
- **Delivery radius: 25 miles from Torrance.** The caterer does not publish a radius. Reason: 25 miles covers the core LA basin, including the Culver City scenario.
- **Delivery minimums: enforce both 20 guests and $400.** The FAQ says 20 guests; the catering page says $400 or more. Reason: both are published, so the safer quote honors both.
- **Full-service service charge: 18% of food subtotal.** Full-service pricing is quote-based. Reason: 18% is a common LA catering service charge and keeps the math deterministic.
- **Full-service staffing: $35 per attendant-hour, 3-hour minimum, 1 attendant per 30 guests, rounded up.** The caterer includes a team member for three hours but does not publish labor rates. Reason: needed for a full-service quote.
- **Pickup lead time: 24 hours.** Pickup lead time is not published. Delivery and full service lead times are published and used as-is.
- **Tax is based on the delivery address, not the caterer's city.** Culver City 11.25%, Torrance 10.75%, effective 2026-10-01, from the CDTFA table. Reason: California catering tax follows where the food is delivered or served.
- **Tax base: food subtotal + delivery fee + service charge + staffing fee. Gratuity excluded.** Mandatory charges are treated as taxable; gratuity is optional. Reason: conservative and easy to explain. Confirm with the caterer or a CPA for production use.
- **Rounding: half-up to cents.** Reason: quotes must reconcile to the cent across code and tests.
- **Children under 10: two children count as one adult.** Published in the catering FAQ.
- **Package side upgrades and extra sides are priced per person.** Reason: they appear in the per-person package section; the source does not state a separate unit.
- **Serving counts are estimated where the menu gives a piece count but no guest count.** Meatballs 2-3 per guest, tenders 2, breadsticks 2, cookies 2, shrimp 3, and a half-gallon beverage 8-10 cups. Reason: the pricing engine needs a servings input, and these items publish only a piece count.

## Dietary and allergen handling

- **GF means gluten-sensitive, not gluten-free.** The caterer states it does not have gluten-free items. Reason: treating GF as certified gluten-free would create a false safety claim.
- **Unknown allergens stay unknown.** Items without a matching allergen-table row are marked `unknown`, never `none`. Reason: the handoff explicitly requires this, and an unknown allergen is a safety issue.
- **Package and boxed-meal allergens depend on selections.** These items are marked `depends_on_selection` and must be confirmed by the caterer. Reason: the allergen table is per component, not per package.
- **Sesame and shellfish are added from item names where the table has no column.** The allergen table has no sesame or shellfish column, but the source names state sesame and shrimp. Reason: omitting them would understate risk.
- **Allergen checks are conservative.** A selected item with an unknown allergen that could match a guest allergy is flagged for caterer review, not silently approved.

## Demo data

- **The capacity calendar is synthetic.** Reason: the caterer does not publish availability; the handoff calls for invented booked dates.
- **Test inquiries are synthetic.** Reason: the handoff separates real business data from synthetic test cases.
- **Display name is anonymized.** Reason: classroom use. The underlying menu and prices remain real and cited.
