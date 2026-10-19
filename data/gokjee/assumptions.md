# Assumptions — Gok Jee Foods (Korean)

This is the simplified second dataset. Every non-published value is listed here with a reason.

## Source and branding

- **Real source:** Gok Jee Foods, 170 S Western Ave # A, Los Angeles, CA 90004. Korean catering.
- **Display alias:** Koreatown Catering Co. The real name stays in `menu.json`, `rules.json`, and `source-log.md` for provenance.
- **Prices captured 2026-10-18** from the online catering menu. They can change.
- **Set menus include** plate, napkin, and chopsticks. Prices exclude tax.

## Rules

- **Minimum order: 5 guests.** The smallest published set menu serves 5. A la carte trays usually serve 10. Reason: no separate minimum is published.
- **Lead time: 48 hours.** Not published. Reason: the quote needs a deterministic cutoff, and 48 hours is typical for tray catering.
- **Delivery fee: $50 flat within 15 miles, then $2.50 per mile up to 25 miles.** Not published. Reason: same simple LA model as the primary dataset.
- **Delivery radius: 25 miles from Koreatown.** Not published. Reason: covers Culver City and the core LA basin.
- **No service charge.** The menu is drop-off catering and publishes no service charge. Reason: do not add a fee the caterer does not charge.
- **Tax follows the delivery address:** Culver City 11.25%, Torrance 10.75%, effective 2026-10-01, CDTFA. Reason: California catering tax follows where the food is delivered.
- **Tax base: food + delivery. Gratuity excluded.** Reason: simple and conservative.

## Menu math

- **Per-person and per-tray prices:** `$180/10 people` is treated as one tray serving 10, not $180 per person.
- **Piece-count items:** assume 2-3 pieces per guest. Example: 25 dumplings serve 9-13.
- **Raw LA galbi:** 1 lb serves 3-4.
- **Soups:** `16oz x 10` is one tray serving 10.

## Dietary and allergens

- **Allergens are unknown for every item.** The caterer publishes no allergen table. Never treat unknown as none.
- **Any allergy request must be flagged for caterer confirmation.**
- **Dietary tags are minimal.** Only `Dumplings (Veg.)` and `Jobche` are tagged vegetarian because the source explicitly says veg. Everything else needs confirmation.
- **No gluten-free claims.** Soy sauce and wheat-based items are common in Korean catering.

## Demo data

- **Capacity calendar is synthetic.** Not the caterer's real availability.
- **Display name is anonymized.** For classroom use; the underlying menu and prices are real and cited.
