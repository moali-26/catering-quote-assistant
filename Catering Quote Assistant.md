# Catering Quote Assistant — Handoff

> **Historical handoff (October 18).** The [Overall Project Plan](docs/project-plan.md), updated October 19, supersedes the scope, roles, schedule, and stack assumptions below. Shared customer/owner login, persistent My Quotes, owner menu updates, and owner Stripe test software checkout are now in the plan. The original text is preserved as background.

Oct 18, 2026 · @Mo

## TL;DR

We're building an assistant that turns a messy catering inquiry into an itemized, caterer-approved quote, priced from one real caterer's published menu. It is due Thursday, Oct 22. The most urgent task is picking that caterer and transcribing their menu and pricing rules, because every other workstream depends on that data.

To get past "just an LLM wrapper," the LLM handles language (understanding the request, choosing menu items, writing the email). All math and rule checks run in deterministic code, and an eval set measures accuracy.

## The user: a small caterer

Our user is the owner or office manager of a small catering business: one location, mostly office lunches and private events. The end customer only sends an inquiry and receives a quote.

The problem: inquiries arrive as free text, like "lunch for \~40 next Friday, a few vegetarians, one nut allergy, around $800, Culver City office." Turning that into a quote means re-reading the menu, working out portions, applying minimums and delivery fees, and checking allergens and lead time. It's slow, repetitive, and easy to get wrong.

Our product does that work. The caterer reviews and approves the quote before anything goes out.

## How it works

Each step is marked LLM or code. The "not a wrapper" argument depends on the code steps.

1. **Intake (LLM):** extract the inquiry into a fixed schema: headcount, date and time, address, dietary needs and allergens, budget, service style, event type. Missing fields are flagged, not guessed.
2. **Clarify or proceed (code + LLM):** if a critical field is missing (date, headcount, or address), draft follow-up questions and stop. Otherwise continue.
3. **Menu selection (LLM with tools):** query the menu database, filtering by dietary tag and checking cost per person, and pick items that fit the budget and constraints.
4. **Pricing engine (code):** quantities from serving sizes, order minimums, delivery fee, staffing, tax, and service charge. No arithmetic is done by the LLM.
5. **Constraint checks (code):** lead time, capacity on that date, and allergen conflicts between selected items and the request.
6. **Output (LLM + code):** itemized quote plus email draft. The caterer approves or edits before sending.
7. **Eval (code):** 30–50 test inquiries with known correct answers. Score extraction accuracy, whether the quote total matches, and whether missing info correctly triggers a clarifying question.

## Data plan

The business data is real and the test inquiries are synthetic. That split is how we answer "is this fake data?"

| Data | Real or synthetic | Source |
| --- | --- | --- |
| Menu items, prices, serving sizes | Real | One caterer's public catering menu |
| Minimums, delivery fees, lead time, service charge | Real where published; documented assumption where not | Same caterer's site or order page |
| Sales tax | Real | Current LA-area rate, looked up and cited |
| Capacity calendar | Synthetic | We invent booked dates |
| Customer inquiries | Synthetic, with correct answers | Written by us, including messy and incomplete ones |

Every assumption goes in an `assumptions.md` file with a one-line reason, so we can defend each one in Q&A.

## Gathering real caterer details

Pick one caterer by Sunday night and finish transcribing by Monday night. Choose for data quality, not cuisine.

**How to pick the caterer.** It must meet all of these:

- Has a public catering menu with prices (web page or PDF), not "contact us for a quote"
- Lists serving sizes ("serves 10", per-person, half/full tray) so the quantity math has real inputs
- Covers at least a few dietary options (vegetarian, vegan, gluten-free) so the filters have something to work with
- Ideally publishes rules: order minimum, delivery fee or radius, lead time

A local LA caterer makes the better story. A chain's catering menu is a fine fallback if no local menu has prices and serving sizes. Collect 2–3 candidates, then choose.

**What to capture.** Put it in `menu.json` and `rules.json`, with the source URL and the date captured.

- [ ] Every item: name, category, price, pricing unit (per person, per tray, per dozen), serves N
- [ ] Dietary tags per item: vegetarian, vegan, gluten-free
- [ ] Allergens per item, where listed; mark unknown as unknown, not "none"
- [ ] Order minimum ($ or headcount)
- [ ] Delivery fee and radius (flat, by zip, or by distance)
- [ ] Lead time / order cutoff (e.g., 48 hours)
- [ ] Service charge or staffing fees, if offered
- [ ] Add-ons: utensils, setup, rentals
- [ ] Cancellation policy (nice to have)
- [ ] Screenshot or PDF of the source menu saved to the team folder as proof

**If rules aren't published.** Either email or call the caterer to ask (one short message, framed as a class project), or pick a reasonable value and log it in `assumptions.md`. Don't block on a reply.

## Roles

Put names in the Owner column on tonight's call. With 5 people, split Eval off from UI. With 3, merge Pricing into Data.

| Workstream | Owner | Owns | Done by |
| --- | --- | --- | --- |
| Data |  | Caterer pick, `menu.json`, `rules.json`, capacity calendar, 30–50 test inquiries with correct answers | Mon night |
| Agent core |  | Extraction schema, clarification logic, menu-selection tool calls, orchestration | Tue midday |
| Pricing + checks |  | Deterministic pricing engine, allergen/lead-time/capacity checks, quote output; unit-tested | Mon night |
| UI + eval |  | Streamlit app, eval script and results table, slides, backup demo video | Wed night |

## Next steps

Tonight's 30-minute call matters most: once the three schemas are agreed, everyone can build in parallel without waiting on each other.

**Sun (tonight)**

- [ ] 30-min call: assign owners and agree on the inquiry, menu item, and quote schemas
- [ ] Data owner: shortlist 2–3 caterers and pick one
- [ ] Create the repo and shared folder; add `assumptions.md`

**Mon**

- [ ] Menu and rules transcribed with source URL and date
- [ ] Pricing engine passing unit tests on hand-checked examples
- [ ] Extraction working on 5 sample inquiries
- [ ] Draft test inquiry set with correct answers

**Tue**

- [ ] End-to-end run on 5 inquiries, including one that should trigger a clarifying question
- [ ] Basic Streamlit UI with an approve/edit step

**Wed**

- [ ] Full eval run and results table
- [ ] Fix the worst failures
- [ ] Slides and backup demo video

**Thu**

- [ ] Present

## Out of scope

None of these get built before Thursday: multiple caterers, actually sending emails, payments, back-and-forth negotiation beyond one clarification round, user accounts, and any database beyond JSON or SQLite. Stack is Python, Streamlit, and one LLM API with tool calling.
