# AI Tool Handoff — B + C

## Ready to connect

`quote_engine.ai_tool.evaluate_catering_quote` is a read-only tool boundary around the existing Python pricing/readiness functions. It handles incomplete arguments, safe error responses, and optional budget comparison. It does **not** call an LLM, select menus, save quotes, approve, accept, charge, or reserve capacity. B connects it to the conversation/model service.

```sh
python3 -m examples.ai_tool_demo
python3 -m unittest discover -s tests -v
```

The offline demo uses sample data and a frozen October 18 clock. A real application must supply its current server clock and current menu/rules. No API key, DB, or model is needed for this demo.

## Registration and dispatch

`TOOL_DEFINITION` contains `name`, `description`, and a provider-neutral `input_schema`. B maps this schema to the chosen provider's tool registration format. This is not a ready-made model API request. Some providers' strict modes require schema changes for optional fields; preserve the distinction between unknown details and a confirmed empty allergen list.

```python
from quote_engine.ai_tool import TOOL_DEFINITION, evaluate_catering_quote

# B's orchestration service parses the model tool-call JSON into arguments.
# Handle invalid JSON before dispatch, and allowlist the exact tool name.
result = evaluate_catering_quote(
    arguments,
    menu=current_owner_menu,
    rules=current_owner_rules,
    capacity=current_capacity,
    now=server_now,
    tax_location=resolved_tax_location,
    delivery_miles=resolved_delivery_miles,
)
# Send result back as the matching tool-call result. Let the AI explain it.
```

B owns a menu lookup tool/context that provides real IDs and availability. This pricing tool does not discover or recommend menu items. Backend/auth code selects the correct business; no business/account IDs are accepted in the model arguments.

## Model input versus server context

| From confirmed customer conversation / menu lookup | From trusted server context only |
| --- | --- |
| `headcount`, `event_at` with timezone, `service_mode` | Current menu, prices, rules, capacity, server clock |
| Delivery `address` | Tax location matching that address (business location for pickup) |
| `allergens`: normalized names, or `[]` only when none confirmed | Delivery miles matching the current address |
| `selections`: item ID, variant ID, positive integer quantity | Authenticated identity and business mapping outside this tool |
| Optional `budget_usd`: total including fees/tax, string such as `"800.00"` | Approval, persistence, payment and booking handled elsewhere |

Partial input is allowed. Unknown values should be omitted, not invented. `allergens` must be explicitly collected before pricing through this tool. If the customer gives a per-person budget, clarify/normalize the total before using this total-budget field.

Do not ask the model to guess distance or tax jurisdiction. The app must resolve or explicitly verify these facts. No geocoding is implemented. If address changes, invalidate the old distance/tax context. In the fixed demo, use clearly labeled, preconfigured sample values. Unknown server context yields `needs_server_context`.

## Response contract

Every result includes `schema_version`, `status`, `error_code`, `missing_fields`, `questions`, `blocking_reasons`, `review_reasons`, `pricing`, `budget`, `saved: false`, and `can_auto_approve: false`.

| Status | What B should do |
| --- | --- |
| `needs_clarification` | Ask the returned questions, using conversation context to avoid repetition. No price is returned. |
| `needs_server_context` | Explain that delivery/tax verification is pending; do not guess or repeatedly ask the model to supply it. |
| `invalid_input` | Correct malformed tool arguments or clarify invalid customer details. Use the safe error code. |
| `cannot_evaluate` | Graceful failure; route to application diagnostics/owner review. Do not expose internal configuration or invent a total. |
| `blocked` | Explain the blocking reason, obtain changes, then call again. A calculated amount may still be present; it is not approval. |
| `needs_owner_review` | Explain the provisional total and review flags. Customer can proceed to the separate request-submission flow. |

Pricing values are integer cents. Format them as dollars, never reinterpret cents as dollars. Budget is optional: `{limit_cents, within_budget, over_budget_cents}`. Going over budget does not change the readiness status or automatically prevent a customer requesting the quote; B proposes alternatives or asks whether the customer wants to proceed. Compare using the returned budget fields rather than model arithmetic.

Example: total `74904` with budget `70000` returns `within_budget: false`, `over_budget_cents: 4904`. AI can say: “The draft is $749.04, which is $49.04 over your budget. Would you like to adjust the menu?” It must still mention relevant owner-review needs.

Unknown customer allergen names block approval until clarified. Unknown/selection-dependent menu allergens require owner review and must never be described as safe. Portion coverage and dietary suitability remain human review; this tool does not certify that a menu feeds everyone or meets every diet.

## Error handling and limits

Unexpected fields (including prices, menu objects, roles or IDs) are rejected. Known failures such as service minimums, unavailable items, delivery radius and invalid dates return stable codes. Other QuoteError failures return `invalid_request_or_configuration`; B/D should diagnose on the server without logging raw secrets/customer inquiries. Unexpected programming errors still need the application's normal exception boundary; do not suppress them silently.

The wrapper is pure and read-only. Quote persistence and approval endpoints must independently rerun workflow checks with current trusted data. Model text and menu descriptions are data, never permission to approve or access records.

## Verification / remaining work

89 local tests pass: 75 existing tests plus 14 tool-boundary tests. New cases cover budget comparison, missing fields, explicit allergy confirmation, forged context fields, malformed input, safe errors, allergy blockers and non-mutation. The sample demo runs offline. No live LLM tool-call evaluation or browser journey has been run. The separate Supabase integration test remains pending.

Next for B: register the tool, wire dispatch/result messages, connect real menu lookup, and run customer conversation scenarios. Next for D/C: resolve trusted delivery/tax context and connect the separate submit/approve/respond actions.


## Customer selections and notes

`evaluate_catering_quote` accepts optional `customer_notes` (plain text, maximum
2,000 characters). Send the complete current customer-confirmed package choices
and special requests on each evaluation, labeled by dish; preserve prior choices
unless changed and use `""` to clear them. Never invent choices. Allergies must
still be supplied in `allergens`, and notes do not alter pricing or checks.

The customer sees these notes in the draft before confirming submission. They
are stored inside each quote version's request and displayed on both customer
and owner quote pages, including after repricing and approval. Existing quotes
without notes still work. No database migration is required for the JSON payload.
Old chat-only choices are not automatically backfilled into submitted quotes.

Deployment smoke test: ask for Pasta Duo with Marinara, Macaroni & Cheese, and
garden salad; verify the draft notes, submit, and sign in as owner to see the
same notes. Change a choice before submitting and verify only the current choice
is sent. Local regression tests use a scripted model; verify actual model
extraction after deployment.
