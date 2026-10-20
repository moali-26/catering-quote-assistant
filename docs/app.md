# Web App (D) — Foundation

Status (Oct 19, 2026): **PR 1 of 4.** The FastAPI app runs locally and is ready to deploy on Render. It serves the public home page, a sign-in page shell, a health check and branded error pages. Sign-in, quote screens and chat are not connected yet.

## What is in this PR

| Path | Purpose |
| --- | --- |
| `app/main.py` | FastAPI app factory: routes, static files, security headers, error pages |
| `app/catalog.py` | Read-only business/menu data for public pages; the home page example is priced by `quote_engine.calculate_quote` |
| `app/config.py` | Settings from environment variables (`APP_ENV`, `APP_DATASET`) |
| `app/templates/` | Jinja2 pages: `base`, `index`, `login` (inactive), `error` |
| `app/static/` | One stylesheet and the favicon; no build step |
| `render.yaml` | Render blueprint: build, start, health check, env var names |
| `requirements.txt` / `requirements-dev.txt` | Deployed dependencies / plus test client |
| `supabase/migrations/202610200001_conversations.sql` | Saved chat history table, server-only like quotes; a linked quote must belong to the same customer and owner |
| `tests/test_app.py` | Page, health, 404, header and static-file tests |

## Run locally

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload          # http://127.0.0.1:8000
python -m unittest discover -s tests   # 138 tests; app tests skip without FastAPI installed
```

Python 3.12 is used on Render (`PYTHON_VERSION` in `render.yaml`). The core tests still run on the system Python without web dependencies.

## Design notes

- **One service, no frontend build.** Pages are server-rendered with Jinja2; later PRs add HTMX for chat and buttons. Teammates' Python modules are called directly.
- **Displayed money always comes from data.** Menu prices come from the menu file; the example ticket total ($749.04) is calculated by C's pricing engine from the sample fixture, so it changes if the data changes.
- **Branding uses `display_name` only.** Item names and descriptions pass through `catalog.make_scrubber`, which applies `meta.branding.item_aliases` and removes any remaining source name; tests check both datasets.
- **No dead ends before launch.** `accounts_open` (template global in `app/main.py`) is `False` until sign-in ships, so the home page links to the menu and steps instead of the inactive sign-in form.
- **Visual system:** pine ink on a linen background, herb green for actions, tomato only for status stamps, mustard as a highlighter. Type: Bricolage Grotesque (display), Figtree (body), IBM Plex Mono (ticket and prices). The quote is presented as a kitchen order ticket; later quote screens reuse it.
- **Production hardening:** API docs are off when `APP_ENV=production`; pages, error pages and static files carry `nosniff`, `DENY` framing and `same-origin` referrer headers; unhandled errors show a generic page and are logged server-side; error pages still render if the business data fails to load. `GET` and `HEAD` both work on pages and `/healthz` for uptime checks.

## Deploy on Render (D)

1. Render → New → Blueprint → select this repository. Render reads `render.yaml`.
2. Fill the secret env vars it asks for. Leave any not yet available empty; this PR only needs `APP_ENV` and `APP_DATASET`, which the blueprint sets.
3. Health check: `GET /healthz` returns `{"status": "ok"}`.
4. The free plan sleeps when idle; open the URL a minute before a demo.

## Database

Apply migrations in order in the Supabase SQL editor: `202610190001_quote_storage.sql`, then `202610200001_conversations.sql`. Both create server-only tables with RLS enabled and no browser grants.

Verified on a local PostgreSQL 16: both migrations apply cleanly, the composite foreign key rejects a conversation linked to another customer's quote, and C's live integration test (`tests/integration`) passes against them.

## Next PRs

2. Shared sign-up/sign-in with Supabase Auth, server-verified identity, owner role from server config; quote server actions.
3. My Quotes, quote detail, owner inbox and approval screens.
4. Customer chat connected to `ai_service.Conversation`, saved per customer.
