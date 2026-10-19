# Quote Module Review — October 19, 2026

## Result

Reviewed pricing, readiness, workflow transitions, SQLite storage, and the existing test suite. Added regression tests before applying fixes: they reproduced three issues (six failures including subcases). After the fixes, all 65 tests pass. This is a local component review, not a production-security certification or a browser end-to-end test.

## Fixed findings

1. **Unrecognized customer allergens could be approved after acknowledging a warning.** For example, `nuts` does not match the normalized `peanut` or `tree_nuts` names, so exact conflict matching could miss it. Unknown customer allergen names now block approval until clarified and normalized in a revised request. Unknown menu allergen information remains an owner-review flag under the existing data policy; this does not certify food safety.
2. **Invalid minimum-guest configuration was accepted.** Negative, boolean, and fractional minimums could participate in the comparison. Minimum guest count now requires a positive integer, matching supported fixture rules.
3. **Nested rule-assumption objects could remain linked to source data in memory.** The snapshot now deep-copies assumptions so a subsequent source edit cannot change an existing returned quote. Current fixtures mostly use strings, but the public function had allowed nested JSON values.

## Component responsibilities and reviewed behavior

| Component | Responsibility | Evidence |
| --- | --- | --- |
| `pricing.py` | Trusted menu IDs and explicit unit quantities → itemized cents, fees, tax | Sample total $749.04, rounding, menu availability, forged selection price ignored, unsupported inputs rejected |
| `checks.py` | Missing inputs, event notice, capacity snapshot, allergen flags | Missing/blocked/review separation, timezone boundaries, known conflicts, new unknown-name blocker |
| `workflow.py` | Draft → owner approval → customer response; revisions retain history | Actor checks, stale revisions, current-data recheck before approval, revision reset, no input mutation |
| `storage.py` | Durable local records, participant-filtered reads, atomic saves | Fresh store instances, account isolation, competing writes, preserved history, duplicate protection |

Customer acceptance is an expression of agreement, not a capacity reservation or payment. Approval is a human review step, not automatic allergy/portion certification.

## Open integration requirements

- Authentication is not implemented here. A trusted server must derive actor IDs and business membership, authorize access, and run the workflow function before saving. `save` checks participant access, not the full action-specific approval policy. Never expose raw record saving or accept browser-supplied actor IDs.
- SQLite is an optional local adapter. Production persistence needs a durable supported disk or the team's hosted database. Actual logout/login, server restart, and browser permissions tests remain pending.
- Only explicit quantities and the supported pickup/delivery rules are implemented. Portion sufficiency, dietary suitability, and final supported menu selection require team review. Passing sample tests does not establish support for every rule/item in the larger datasets.
- Menu/calendar snapshots can change independently of approval. Atomic quote revision checking prevents lost quote updates, but it is not an atomic menu-version check or booking reservation.
- The workflow creates drafts but has no distinct submitted status. For the minimum flow, the application should persist an owner-visible quote when the customer submits; keep earlier conversational drafting separate. Do not populate the owner inbox with every incomplete chat turn accidentally.
- The application must translate QuoteError/QuoteConflict/QuoteNotFound into useful messages. Model-generated prices, distances, and tax locations must not become trusted facts without appropriate validation/confirmation.
- Tests are unit/component tests using sample fixtures, not the held-out AI evaluation or full UI tests.

## Next integration order

1. Agree with D on authenticated account IDs, business membership, database adapter, and when customer submission creates a saved quote.
2. Wrap create/get/list/approve/revise/respond in authenticated server actions; load current menus and records on the server.
3. Connect customer My Quotes and owner inbox; display outer workflow/readiness status and errors.
4. Test two customers and an owner through the browser, including logout/login, cross-account access attempts, stale edits, menu changes, and accepted/declined results.
