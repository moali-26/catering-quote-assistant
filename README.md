# Quote Kitchen — Catering Quote Assistant

## Web app

The web app is in `app/` (FastAPI, server-rendered pages, deployed on Render). Customers sign in, request a quote through the AI chat (OpenAI `gpt-5.5`) and accept or decline it in My Quotes. The owner reviews and approves quotes in the quote inbox, edits the menu, and subscribes to the Quote Kitchen Subscription Plan through Stripe (test mode). Run it with `uvicorn app.main:app --reload` after `pip install -r requirements-dev.txt`. Setup, design notes and deployment steps: [docs/app.md](docs/app.md).

## Current project plan

**Team handoff (October 19):** [Integration notes by teammate](docs/team-integration-notes.md). Deployment: **Supabase PostgreSQL + Auth**. Python quote logic stays shared, and SQLite remains local-only.

See [Overall Project Plan](docs/project-plan.md) for the October 19 scope, five-person responsibilities, deadlines, and acceptance checks. The app uses **one shared login for customers and owners**, with account-based **My Quotes** for returning customers. See [Quote Engine](docs/quote-engine.md) for implemented Python interfaces and tests. An optional [SQLite quote storage adapter](docs/quote-storage.md) is available for local development.

## Menu data

The app and final evaluation use the **22-item frozen demo menu** in `data/demo/`. Owner menu edits are stored in the configured database; this repository cleanup does not change those records.

| Location | Purpose | Why retained |
| --- | --- | --- |
| `data/demo/` | Supported app/evaluation seed, rules and synthetic capacity | Core customer-to-owner workflow |
| `data/sample/` | 9-item development fixture and example inquiries | Automated tests and offline demos |
| `data/menu.json`, `data/rules.json`, `data/capacity.json` | Full 67-item source dataset | Demo rebuilding, provenance validation and full-dataset tests |
| `data/raw/` | Stonefire source snapshots | Menu/rule/allergen provenance and parser inputs |
| `data/allergens.json`, `data/parse_allergens.py` | Source allergen data and parser | Retains the data preparation workflow |
| `data/caterers.json` | Retained source dataset index | Documents paths for the primary dataset |

The unused second-caterer dataset and its source snapshots have been removed. No active menu IDs, prices, rules, allergens or evaluation cases were changed.

Source: Stonefire Grill, Torrance, captured October 18, 2026. Quote Kitchen is the project brand; source attribution remains in the metadata. See [source log](data/source-log.md), [assumptions](data/assumptions.md) and [demo documentation](data/demo/README.md).

Important limitations: gluten-sensitive does not mean gluten-free; package allergens can depend on selections; unknown allergens require confirmation. Capacity is synthetic and prices are a dated source snapshot.

Validate the retained data:

```sh
python data/validate_dataset.py
python data/sample/validate_sample.py
python data/demo/validate_demo.py
python -m unittest discover -s tests
```

Do not rerun `data/demo/build_demo.py` to apply live owner edits: it regenerates checked-in seed files from the full source dataset.

## Quote integration handoff

- [AI tool interface and examples](docs/ai-tool-handoff.md)
- [Quote screen data and server actions](docs/quote-ui-handoff.md)
- [Offline demos and expected results](docs/quote-demo-checklist.md)
- [Supabase setup](docs/supabase-setup.md)
- [Owner menu editing](docs/menu-editing.md)
- [Quote Kitchen Subscription Plan (Stripe test mode)](docs/billing.md)
- [Evaluation](evaluation/README.md)

Run `python3 -m examples.quote_journey_demo` for the offline saved-quote journey.
