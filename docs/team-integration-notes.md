# Team Integration Notes

Updated October 19, 2026 — handoff from the pricing/workflow workstream.

## Decisions to share

- **Python:** Pricing, readiness checks, and quote workflow are implemented in Python. B and D should reuse these functions rather than duplicate the calculations. This does not require a Python frontend; if the app uses JavaScript, connect through a Python backend/API. Hosting that backend still needs to be arranged with D.
- **Supabase:** Our selected direction is **Supabase PostgreSQL + Supabase Auth** for shared data and login. D owns project setup and auth; C will adapt quote storage to the agreed schema. Supabase integration is not implemented yet. SQLite was built only for local development/testing and is not the planned deployed database.
- **One login system:** Customers return to **My Quotes**; owners use their dashboard. Roles and record access must be enforced on the server/database. No guest quote-link system is needed.

## Why these choices / references

- **Python:** The quote functions are already implemented and tested in Python, so reusing them avoids rewriting the same calculations. AI handles conversation and chooses when to call these tools; code provides repeatable prices and checks. See the [Python interfaces and examples](quote-engine.md).
- **Supabase:** I checked the Week 4 example architecture and the official free-plan details. Week 4 **PDF page 22** shows **Supabase — Database · Auth**; it is an example, not a mandatory provider. Supabase combines the two services we need, and the free plan currently includes a 500 MB PostgreSQL database and authentication. This looks suitable for our small capstone demo, subject to usage limits. See [official pricing](https://supabase.com/pricing). Free projects may pause after one week of inactivity, so check the app before the presentation. The course reference is *Copy of module4-slides.pptx.pdf* in the shared Week 4 materials.
- **Shared customer/owner login:** Signup/login is already a Week 4 requirement (PDF page 5). Reusing one authentication system lets customers return to saved quotes without managing secret links. Requiring both roles to log in is our product choice, not a separately stated course requirement. See [user flow and permissions](project-plan.md).
- **SQLite was temporary:** It let us test saving, reopening, and concurrent updates locally without waiting for a shared cloud setup. It is not the planned deployed database. Keep the tested behavior when adapting to Supabase; see the [storage contract and limitations](quote-storage.md).
- **Start with a small menu:** A fixed supported subset makes data checks, AI tool calls, and expected quote totals easier to verify before expanding. The existing sample is a development fixture; final evaluation should use the agreed final data. See [review findings and remaining gaps](review-notes.md).

## Notes by teammate

| Person | What to know / next action |
| --- | --- |
| **A — Data & menu** | Freeze one small supported menu/rules set. Preserve item/variant IDs, pricing units, and availability fields. Owner menu edits should update the data B/C read from Supabase. Sample data is for development; final evaluation needs agreed data and answer keys. |
| **B — AI conversation** | Customer still interacts through AI chat. AI extracts details, asks questions, selects menu items/quantities, and calls the Python pricing/readiness functions. Use returned totals and flags in replies; do not calculate prices in the prompt. Agree with C on input fields and tool-call responses. Unrecognized customer allergen names must be clarified before approval. |
| **C — Pricing & workflow** | Core Python functions and local persistence are ready for integration. Adapt storage to Supabase with D, keeping account filtering, version history, and atomic revision checks. Keep calculations and state transitions in the existing shared module. |
| **D — App, auth & deployment** | Use Supabase for DB + Auth. Share the table/schema plan and authenticated user/business ID mapping with A/C. Connect My Quotes and owner inbox, and arrange how the app calls the Python module. Customers see only their own quotes; owners only their business's records. Keep privileged credentials server-side. |
| **E — Payment, evaluation & submission** | Stripe test checkout is for the owner's software purchase, not the customer's food order. Current 65 tests cover components, not final AI/browser evaluation. Include logout/login persistence, cross-account access, menu updates, and the full approval/response journey in testing. |

## Current progress and remaining work

**Implemented:** deterministic pricing; missing-info, notice, capacity and allergen checks; draft → owner approval → customer accept/decline; revised quote history; optional local SQLite storage. **65 tests pass**, and sample data validation passes. Core logic was merged in the first PR; storage and review fixes are currently local follow-up work.

**Still to connect:** AI tool calling, Supabase tables/Auth, authenticated server actions, customer/owner screens, Stripe and deployment. Choosing Supabase does not automatically implement these integrations.

**Flow:** Customer logs in → chats with AI → submits request → saved quote appears in My Quotes and owner inbox → owner approves → customer returns and accepts/declines. Save owner-visible quotes on submission; do not expose every incomplete chat draft to the owner. Changes create a new draft requiring approval. Acceptance is not a payment or automatic capacity reservation.

## First items to align

1. **D + C:** Supabase schema, account/business IDs, atomic quote-update operation, and Python hosting/call interface.
2. **A + B + C:** Active menu/rules schema and AI request fields (event, headcount, service mode, address/distance, tax location, allergens, item/variant IDs and quantities).
3. **Everyone:** One working end-to-end journey before expanding scope. Finish implementation and testing Wednesday; Thursday is presentation.

Details: [Overall plan](project-plan.md) · [Python interfaces](quote-engine.md) · [Storage contract](quote-storage.md) · [Review findings](review-notes.md)
