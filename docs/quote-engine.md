# Quote Engine and Integration Contract

## Completed starting point

Python standard library only; verified locally with Python 3.12. No UI framework, database, model SDK, or deployment stack imposed on the team. The module can be imported into a Python app or called behind a Python API if the frontend uses another language.

```sh
python3 data/sample/validate_sample.py
python3 -m unittest discover -s tests -v
python3 -m quote_engine
```

Run from the repository root. No package installation or virtual environment is necessary for this module; use the team's environment when broader app dependencies are chosen.

## Scope

This module contains pricing, readiness checks, and pure quote workflow functions. The calculator prices explicit variant quantities; readiness adds date/lead-time/capacity and allergen checks; workflow functions manage drafts, revisions, approval, and customer responses. It does not parse language, infer portions, certify dietary suitability, authenticate, or persist records. Calculator output remains `priced_draft`; the separate workflow status determines which actions are allowed.

Pickup and delivery are supported. Full service is rejected explicitly until staffing/charge semantics are agreed. Per-person, per-tray, per-platter and each values mean explicit units purchased, not inferred servings. A side dish and a meal can both be selected for the same guest; summing every line's quantity must not be used as a headcount validation rule.

## Application interface

```python
from quote_engine import calculate_quote, QuoteError

result = calculate_quote(menu, rules, {
    "headcount": 40,
    "service_mode": "delivery",
    "delivery_miles": 15,
    "tax_location": "Culver City",
    "selections": [
        {"item_id": "pkg-pasta-duo", "variant_id": "pkg-pasta-duo-pp", "quantity": 40},
        {"item_id": "side-garlic-mashed", "variant_id": "side-garlic-mashed-full", "quantity": 1}
    ]
})
```

- Caller supplies trusted current owner menu/rules from the server. Never accept a customer's complete menu/rules object as authoritative.
- Any selection-level price is ignored; variant ID must belong to the supplied item ID. Quantities are positive integers, excluding booleans.
- Output is JSON-serializable; monetary fields end in `_cents`. UI formats dollars by dividing by 100. `lines` contains copied price/name snapshots.
- Invalid/unsupported input raises `QuoteError`; The application translates it into clarification or review rather than inventing a number. Malformed server configuration is a setup error and should be logged safely.
- Explicit supported tax location and delivery miles are required. No automatic geocoding or default location guessing.
- Database/auth owners must enforce business/session isolation outside this pure calculator. Calling this function does not authorize a quote.

## Sample evidence and issues to align

The teammate's sample example produces food $623.29 + delivery $50.00 + tax $75.75 = **$749.04**. It preserves the unresolved package-allergen flag. This verifies arithmetic for that selection, not the five inquiry scenarios or allergy safety.

The sample and full rules are not interchangeable:

| Field | Sample | Full primary dataset |
|---|---|---|
| Delivery minimum subtotal | $300 | $400 |
| Flat delivery fee | $50 | $65 |
| Full-service settings key | `service_charge` | `staffing` |

Sample minimum subtotal is labeled `published` although it differs from the full data. Ask the data maintainer to clarify provenance; do not silently change their fixtures. Sample README says not to use it for final evaluation. Treat it as development input until the team approves the final data and evaluation set.

Relative dates in inquiry fixtures depend on an October 18 reference date. Later lead-time tests must use an injected clock and explicit timezone; do not reinterpret those examples using today's date.

`listed_none` does not guarantee allergen-free; `gluten_sensitive` is not gluten-free. Package choices, dietary tags, serving coverage, and known allergen conflicts still require the later checks layer.

## Quote lifecycle — implemented as pure functions

Use separate workflow status from pricing result:

- Draft → owner approved → customer accepted/declined.
- Only the authenticated owning business can approve; only the matching authenticated customer account can accept/decline.
- A revision creates a new draft and preserves the earlier version, including accepted records.
- Menu changes do not silently update stored quotes. Explicit revised pricing uses the current owner menu and returns to review.
- Customer acceptance does not itself mean payment or confirmed booking.

## Integration status

| Order | Task | Status |
|---|---|---|
| 1 | Review pricing contract with team | Done: the frozen `data/demo` menu and rules |
| 2 | Integrate implemented readiness checks and review their policy with the team | Done: used by the AI chat and on submit/approve |
| 3 | Connect implemented quote IDs, versions and transitions to persistence | Done: Supabase PostgreSQL (SQLite locally) |
| 4 | Build reusable quote detail/list components and action endpoints | Done: the web app (`app/`) |
| 5 | Run final-data and end-to-end evaluation | Done: [evaluation](../evaluation/README.md) |

The AI service supplies explicit variant quantities, not only guest count. The application wraps this module without adopting its local execution commands as the full app architecture.

## Readiness checks

`check_quote_readiness(menu, rules, request, now=aware_datetime, capacity=calendar)` wraps pricing with preflight checks. `now` must be supplied by the server; tests freeze it. Add `event_at` (ISO datetime with offset), `address` for delivery, and normalized `allergens` to the pricing request. Calendar lookup uses America/Los_Angeles; notice duration is elapsed time in UTC.

Outputs: `needs_clarification`, `blocked`, or `needs_owner_review`, with `missing_fields`, `blocking_reasons`, `review_reasons`, and optional `pricing`. A priced result can exist inside a blocked readiness result; the app must obey the **outer status**, not interpret the existence of a total as permission to proceed. The pricing object's pending checks remain conservative and are not an approval flag.

Checks cover required input, past dates, minimum notice, capacity snapshot limits, known allergen conflicts, and unknown/selection-dependent data flags. Missing calendar information requires review. Synthetic calendars always require owner confirmation. No bookings or capacity updates occur; a real reservation system needs transactional checks at booking time. Portion sufficiency and overall dietary suitability remain manual review. Full service remains unsupported.

## Review and verification

Reviewed initial arithmetic and error boundaries. Added controlled errors for malformed input/configuration and rejected non-USD configuration rather than silently labeling it USD. Tests exercise the sample $749.04 result, calculation/rounding, invalid quantities/prices, unsupported service, dataset mixing, date/timezone boundaries, capacity conflicts, allergens, and non-mutation.

This code is shared project functionality. Branch names are only Git organization and do not create separate submissions. Authentication, persistence and UI integration are not part of this module; the web app provides them. Workflow transitions are implemented and tested.


### Workflow integration contract

Import `create_quote`, `revise_quote`, `approve_quote`, and `respond_to_quote` from `quote_engine`. Each returns a new JSON-serializable record without modifying the input. Records contain a UUID, owner/customer IDs, a `revision` counter for every change, and a `versions` array for explicitly revised quotes. The last version is current.

- `create_quote(menu, rules, request, owner_id=..., customer_id=..., now=..., capacity=...)` calculates readiness and creates a draft. Incomplete requests may remain drafts.
- `revise_quote(record, menu, rules, request, actor_id=..., expected_revision=..., now=..., capacity=...)` lets either participant create a newly calculated draft. Previous versions, including accepted versions, remain intact. New drafts clear approval and response.
- `approve_quote(record, menu, rules, actor_id=..., expected_revision=..., now=..., acknowledged_reviews=[...], capacity=...)` requires the owner, a draft, no missing/blocking checks, and explicit acknowledgment of every current review code. It reruns readiness against current trusted data/time. Changed pricing requires a revision. Acknowledgment records human review; it does not prove allergy safety or portion sufficiency.
- `respond_to_quote(record, actor_id=..., expected_revision=..., now=..., decision="accept" or "decline")` requires the matching customer and a currently approved quote with a future event. It records intent, not a reservation or payment.

**Server integration requirements:** load records/menu/rules/calendar from trusted storage; resolve actor IDs from authenticated sessions, never request-body role/identity fields. Authorize record access before returning it. Resolve owner/customer binding at creation on the server. Supply the clock on the server. These pure functions do not authenticate users or validate arbitrary client-supplied records.

Persist each result using an atomic compare-and-swap on the old `revision`, in a database transaction. The in-memory revision guard alone cannot prevent simultaneous writes. Preserve version history when saving. Booking/capacity reservations and Stripe are separate integrations. A revision of an accepted quote does not cancel a real booking automatically.

Validation: 50 local unit tests cover pricing/readiness plus approval and response guards, ownership, stale revisions, repricing, history isolation, current capacity/notice checks, and JSON serialization. These are development tests, not the final held-out AI evaluation or an end-to-end browser test.


## Shared login and My Quotes decision (October 19)

See the [Overall Project Plan](project-plan.md). Customers and owners use the same authentication system with server-enforced roles. `customer_id` is the stable authenticated account ID, not a browser-session ID; customers return to My Quotes after closing the page or signing out. `owner_id` must identify the trusted owning account consistently; if the app uses separate business IDs, resolve membership server-side before invoking these functions.

D implements persistent account-filtered quote queries and authenticated action endpoints; C supplies these workflow functions and assists integration. Read access needs authorization as well as write access. Never trust a customer ID, owner ID, or role from the browser. Save returned records transactionally, preserving version history. No guest-link authentication is planned.


## Optional persistence adapter

See [Persistent Quotes](quote-storage.md) for the SQLite adapter, server-side action integration, and deployment limits. The adapter adds account-filtered reads and atomic saves of workflow results.


Review update (October 19): three edge cases fixed. See [review notes](review-notes.md) for findings, evidence, and remaining integration requirements. Unrecognized customer allergen names now block approval until clarified; unknown menu allergen information still requires owner review.
