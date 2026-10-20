# Quote Screens and Server Actions — D + C Handoff

## What is ready

`QuoteService` connects the existing workflow to either storage adapter. `quote_view` and `quote_card` produce JSON-safe data for detail screens and lists. These are framework-independent Python components, not rendered browser pages or HTTP endpoints.

The frontend can display event details, menu lines, quantities, unit/line prices, subtotal, delivery, tax, total, review/blocking reasons, quote history and action flags without recalculating money. Formatted dollar strings and integer cents are both provided.

## Wiring

```python
from quote_engine.service import QuoteService
from quote_engine.postgres_storage import PostgresQuoteStore

service = QuoteService(
    PostgresQuoteStore(),
    context_for=load_current_business_context,
    clock=utc_now,
)
```

D implements `load_current_business_context(owner_id, request)` using current business menu/rules/calendar and verified tax/delivery facts. Return `menu`, `rules`, optional `capacity`, `tax_location`, and `delivery_miles`. Never blindly copy distance/tax values from customer or model input. Invalidate address-derived context when the address changes. The service overwrites caller-supplied distance/tax values with this context.

D's server must verify Supabase Auth and determine account/business IDs first. Never take `actor_id`/`owner_id` from browser form fields or blindly forward request JSON as keyword arguments. The minimum schema supports one owner account per business. Users cannot self-assign owner privileges.

## Server action mapping

These are proposed routes for D to implement, not existing endpoints.

| UI action | Service method | Browser supplies | Server supplies |
| --- | --- | --- | --- |
| Submit request | `submit(request, actor_id=..., owner_id=...)` | Confirmed event/menu request | Verified customer ID, trusted business owner ID |
| My Quotes / owner inbox | `list_quotes(actor_id=..., workspace=..., limit=..., offset=...)` | Pagination | Auth ID, authorized workspace |
| Open quote | `detail(quote_id, actor_id=...)` | Quote ID | Auth ID |
| Approve | `approve(quote_id, actor_id=..., expected_revision=..., acknowledged_reviews=...)` | Quote ID, displayed revision, explicitly checked review codes | Auth ID, current context/clock |
| Revise | `revise(quote_id, request, actor_id=..., expected_revision=...)` | Edited request, displayed revision | Auth ID, current context/clock |
| Accept / Decline | `respond(quote_id, actor_id=..., expected_revision=..., decision=...)` | Quote ID, displayed revision, accept/decline | Auth ID, clock |

Submission requires confirmed allergens (empty list is allowed only after confirmation), complete required information, and no readiness blockers. It saves the first owner-visible draft. AI tool evaluation alone never saves a request. Revised incomplete drafts may remain visible with clarification needed; display missing fields and do not offer approval.

The customer-selected menu may still require owner review of portions/dietary/package choices. Do not automatically pre-check review acknowledgments. Server workflow rechecks readiness before approval.

## Buttons and states

| Current version | Customer | Owner |
| --- | --- | --- |
| Draft | View, revise | View, revise; approve only if readiness allows |
| Owner approved | View, revise, accept/decline before event | View, revise; awaiting customer response |
| Accepted or declined | View, start revised draft | View, start revised draft |

UI uses returned `actions` booleans. They are advisory snapshot-based display hints: current menu, capacity, notice or revision may change before click. Every action is checked again server-side. Approval also requires explicit review acknowledgments, even when its button can be shown. Past events disable acceptance/decline; revision is still available to request a new date. An accepted version remains in history after a revision; no real booking is automatically canceled.

## Error mapping for D

- `QuoteNotFound`: generic unavailable/not found; do not reveal another customer's record.
- `QuoteConflict` or a stale workflow revision: reload the latest quote, ask the user to review it, and do not silently resubmit.
- Other `QuoteError`: display a suitable clarification or action error. Do not send DB diagnostics to clients.
- `QuoteStorageUnavailable`: retry later message; do not claim the action saved. On a network timeout, reload before retrying because commit outcome may be unknown.
- Unexpected errors: app-level error boundary and safe diagnostics. Avoid logging complete inquiries or credentials.

## Integration with D

Done in the web app (`app/`, see [app.md](app.md)): HTTP/UI wiring, verified Auth, current-context resolution, the deployed Supabase migration, accessibility/loading/error states, and end-to-end tests through the app's pages.
