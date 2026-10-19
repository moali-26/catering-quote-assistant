# Source Log — Gok Jee Foods (Korean)

Captured 2026-10-18. This is the second, simplified caterer dataset.

## Selected: Gok Jee Foods

**Display name:** Koreatown Catering Co.

**Why it was added:** it is a real Korean caterer in Koreatown with public prices, serving sizes, set menus, and a downloadable PDF. It adds a second cuisine without changing the primary Stonefire quote flow.

**Address:** 170 S Western Ave # A, Los Angeles, CA 90004

**Phone:** 213-480-1800

**Source URLs**

- Catering menu list: http://www.gokjee.com/menulist.jsp?_pageid=P_E3MtzJaRCarlf1X8IAu0g
- Menu data endpoint: http://www.gokjee.com/menuform.jsp
- 2026 set-menu PDF: http://www.gokjee.com/2026-catering-set-menu_list.pdf

**Proof saved**

- `data/raw/gokjee-catering-menu-list-2026-10-18.pdf` (rendered menu)
- `data/raw/gokjee-catering-menu-list-2026-10-18.html` (page shell)
- `data/raw/gokjee-menuform-2026-10-18.html` (menu rows used for parsing)
- `data/raw/gokjee-2026-catering-set-menu-2026-10-18.pdf` (original set-menu PDF)

## What is real

- Item names (English and Korean), categories, prices, and price units.
- Set-menu servings: 5, 10, or 20 people.
- Set-menu contents for A, B, and C.
- Utensil add-on: $5 per 10 people.
- The PDF's "+ tax" note.

## What is assumed

- 5-guest minimum, 48-hour lead time.
- Delivery fee and radius.
- No service charge.
- Tax base and delivery-address rates.
- Piece-count serving estimates.
- Every allergen is unknown.
- Capacity is synthetic.

See `assumptions.md` for the one-line reason for each.

## Why this dataset is simpler

- No published allergen table, so allergens are uniformly `unknown` and every allergy request is flagged for review.
- Fewer rules: pickup and delivery only, no full service.
- One variant per item, so the pricing engine can treat each row as one tray.
- The menu has 91 unique items after removing the Korean duplicate set-menu rows.

## Note on access

The site is HTTP-only and the menu is loaded through an AJAX endpoint. The saved `menuform` HTML is the reliable parsing source; the rendered PDF is the visual proof.
