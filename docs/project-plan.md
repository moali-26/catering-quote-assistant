# Catering Quote Assistant — Overall Project Plan

Updated October 19, 2026. Current team implementation plan; supersedes the scope, roles, and next steps in the October 18 handoff. This document records product decisions, not a verbatim course rubric. Verify submission details against the syllabus and Week 4 slides.

## Goal and scope

Build one hosted application that helps a small catering business turn customer inquiries into accurate, owner-reviewed quotes. AI handles conversation and menu suggestions; Python code handles prices, checks, and quote transitions.

Use one shared authentication system and login page for customers and owners. After login, show the appropriate workspace. Customers return through **My Quotes**, so closing a tab or signing out does not lose a submitted quote. Do not build a separate secret-link access system.

Start with one supported caterer and a manageable menu subset. Existing datasets remain source material; multiple datasets in the repo do not require a caterer marketplace. A owns simplifying and validating the active menu/rules. The sample fixture is for development, not the final evaluation dataset.

## End-to-end journey

1. Customer signs up or logs in, then starts an AI inquiry for the supported business.
2. AI captures event details, asks for missing information, and proposes available menu items with explicit quantities.
3. The pricing/checks module calculates a draft and flags issues. Customer submits the request; persist it with their account ID and the owning business.
4. Customer sees the request in **My Quotes** with a pending-review label and may close the page.
5. Owner logs in to their dashboard, reviews the inquiry and flags, and approves or revises the quote. A revision requires approval again.
6. Customer returns, logs in, and opens the saved quote. Only an owner-approved current version offers **Accept / Decline**.
7. Persist the response and display it to both parties. Acceptance records agreement with the quote; it does not automatically charge money or reserve capacity.
8. Owner can edit menu names, descriptions, prices, and availability. New requests use the current menu; saved quote versions retain their snapshots. Repricing requires an explicit revision.

Approval notifications are out of scope for the minimum build: customers check My Quotes. State this in the UI. A submitted quote must remain available across logout/login and application restarts, not just within browser session memory.

## Pages and permissions

| Page | Customer | Owner |
| --- | --- | --- |
| Shared signup/login | Customer account | Owner account provisioned through a controlled setup |
| AI inquiry | Start/update own request | Not required for minimum demo |
| My Quotes / quote detail | Own quotes, current status, history, accept/decline | No access to unrelated customer accounts |
| Owner quote dashboard | No access | Own business requests, review, revise, approve |
| Menu management | No edit access | Edit own business menu and availability |
| Software billing | Not required | Stripe test checkout for the software product |

The server must enforce access on every read/write, not just hide buttons. Public signup must not grant owner privileges based on a submitted role field. Derive customer and actor IDs from authenticated accounts; derive business ownership from trusted server records. A URL containing a quote ID is not authorization. No custom password storage is required: use the team's chosen authentication library/provider.

## Five-person responsibilities

| Person | Ownership | Immediate dependencies / handoff |
| --- | --- | --- |
| A — Data and menu | Simplify the active menu, validate units/rules/provenance, implement owner menu editing with D's storage interface | Give B/C supported menu and rule schema; ensure edits feed current server data |
| B — AI conversation | Extraction, clarification, current-menu lookup, item/quantity suggestions, conversation context and failure handling | Send validated request fields to C; use computed totals and flags in replies, never invent prices |
| C — Pricing and quote workflow | Deterministic calculations, readiness checks, quote versions, approval and response logic, calculation evidence | Existing pure functions need D's authenticated IDs and persistent storage; help integrate quote details/actions |
| D — Application and accounts | Shared auth, controlled roles, database, routing, customer chat/My Quotes, owner dashboard, deployment | Persist C's records and enforce permissions; connect B's conversation service; provide stable hosted URL |
| E — Payment, evaluation and submission | Owner Stripe test software checkout, held-out evaluation, end-to-end test evidence, submission assembly | Coordinate auth/billing connection with D; each person supplies their own writeup/slides/evidence |

D owns the app foundation, not every feature's implementation: A builds menu functionality, B the AI service, C quote logic/actions, E billing/evaluation. Agree on storage and service interfaces first to avoid duplicate implementations.

## Current implementation status

- Existing data: primary, Korean, and lightweight sample datasets; active final subset still needs team confirmation.
- Implemented locally: Python pricing, readiness checks, draft/revision/approval/customer-response functions and 50 passing unit tests. See [quote-engine.md](quote-engine.md).
- Not implemented by those functions: actual authentication, persistent database, AI conversation, browser screens, Stripe, or hosting.
- Current work is local; this document does not imply changes have been committed, pushed, or deployed.

## Build sequence and deadlines

All times are team-local (Los Angeles). Finish Wednesday October 21; Thursday October 22 AM is presentation only.

| Deadline | Deliverable | Dependencies |
| --- | --- | --- |
| Mon Oct 19 evening | A freezes supported subset; B/C agree on request and response fields; D sets up shared auth, trusted role mapping, and persistent quote/menu storage | Existing repo/data; current quote module |
| Tue Oct 20 noon | Customer login, owner login, saved My Quotes, owner inbox; initial AI-to-pricing connection | Monday interfaces; B service + C functions + D app |
| Tue Oct 20 evening | Complete inquiry → saved draft → owner approval → customer response; menu edits and owner Stripe test checkout | Shared accounts/storage; A/B/C/D/E components |
| Wed Oct 21 noon | Integration fixes and final-data evaluation; access-control and persistence checks pass | Full journey deployed on hosted URL |
| Wed Oct 21 evening | Freeze working demo; finish writeup, slides, README/setup, demo credentials, backup recording and submission links | Evidence from everyone; E assembles |
| Thu Oct 22 AM | Present the frozen build | No planned implementation work |

## Acceptance checks

- Customer A submits, closes the page, signs out, signs back in, and finds the same quote in My Quotes.
- Customer B cannot read or change Customer A's quote, including by directly changing a URL or request ID.
- Customer cannot approve a quote or edit the menu; an unrelated owner cannot access another business's quotes.
- Owner approval appears when the customer reloads/reopens their quote; only approved current versions allow a response.
- Accepted/declined responses persist across refresh, logout, and application restart and appear in the owner's dashboard.
- Revisions preserve history and clear prior approval for the new version; stale updates are rejected transactionally.
- Owner menu edits affect new quotes without silently changing historical totals; unavailable items are rejected or clarified.
- Missing details and blocking constraints prevent approval; AI explanations use actual computed results.
- Stripe is in test mode for owner software purchase, with server-verified payment state; it is separate from food quote acceptance.
- Final evaluation uses agreed data and held-out inquiries with expected answers; unit tests alone are not the final AI evaluation.

## Minimum-build exclusions

No guest secret links, automatic email/SMS notifications, multiple-caterer marketplace, live food payments, automatic reservation confirmation, or full-service staffing calculations. Use existing authentication infrastructure rather than building custom credential handling. Framework/provider choice remains a team integration decision; the Python quote module does not impose it.
