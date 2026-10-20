# Quote Demo and Evaluation Checklist

## Offline demonstrations available now

Run from repository root:

```sh
python3 -m examples.ai_tool_demo
python3 -m examples.quote_journey_demo
python3 -m unittest discover -s tests -v
```

Use the fixed sample clock **October 18, 2026, 12 PM Pacific** and event **October 23, 2026, 12 PM Pacific** for these fixtures. The real application must use actual current server time and future demo event dates; never freeze the deployed clock to force a quote to pass.

The journey demo uses a temporary SQLite DB and synthetic actors, explicitly acknowledges demo review flags, reopens storage, and records customer acceptance. This demonstrates local service/persistence behavior, not real Auth, model tool calling, Supabase or a browser.

## Expected results

| Scenario | Expected outcome | Local evidence |
| --- | --- | --- |
| 40 Pasta Duo portions + 1 full garlic mashed tray, sample delivery 15 miles, Culver City | Food $623.29 + delivery $50.00 + tax $75.75 = **$749.04**; owner review required | Pricing tests + both demo scripts |
| Same selection, total budget $700 | **$49.04 over budget**; ask whether to adjust menu | AI tool tests/demo |
| Customer gives only headcount | Questions for missing details, no invented price | AI tool tests/demo |
| Customer says `nuts` without normalized type | Blocked until clarified | Readiness/workflow/tool regression tests |
| Known peanut conflict with sample coleslaw | Blocked allergen conflict | Readiness/tool tests |
| Incomplete request is submitted | No owner-visible record saved | Service tests |
| Owner approves and customer reopens storage | Same quote, approval persists, response available | Service tests + journey demo |
| Customer attempts owner approval / unrelated account opens quote | Rejected; no unauthorized data returned | Service/workflow/storage tests |
| Two updates use the same revision | One succeeds, the other must reload | SQLite concurrency tests; live Postgres test still pending |
| Owner changes price before approval | Revision required; historical price preserved | Workflow/service tests |
| Customer revises approved quote | New draft, prior version preserved, no accept until approved again | Service tests |
| Event has passed | No accept/decline action | Service/workflow tests |

## Real app tests still required (B/D/E with C)

- Two real customer accounts and an owner account, including direct attempts to access another customer's quote.
- Customer submits through AI chat, signs out/closes the page, then logs back in and finds the quote in My Quotes.
- Owner edits the menu; AI sees the new menu, while old quote versions keep original totals.
- Owner reviews/approves; customer accepts or declines; both dashboards show the persisted result.
- Test stale revisions and storage failures through UI; do not show success when saving failed.
- Supabase SQL, Auth bindings, connection behavior and real database concurrency tests pass.
- Owner Stripe test software purchase and hosted URL work; separate from quote acceptance.
- Run held-out AI inquiries with answer keys and report actual results, including failures. Sample component tests are not the final AI evaluation.

## Current evidence

**101 local tests pass**: original logic/storage, Postgres contract mocks, AI tool wrapper, and 12 service/view integration cases. The live Postgres test remains skipped without a configured test DB. No live-model or browser evaluation result is claimed.
