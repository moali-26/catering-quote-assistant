# Web App (D)

Status (Oct 20, 2026): **PR 2 of 3.** Shared sign-in for customers and owners, My Quotes, quote detail, owner inbox and approval are working on top of C's `QuoteService`. The customer chat that creates new requests is the next PR; until then the home page invites people to create an account but does not offer "Start a quote request".

## Pages and actions

| Route | Who | What happens |
| --- | --- | --- |
| `/` | Everyone | Home page, menu, example ticket priced by the quote engine |
| `/login`, `/login?mode=signup` | Everyone | Sign in or create a customer account (Supabase Auth) |
| `POST /login`, `POST /signup`, `POST /logout` | Everyone | Sets or clears HTTP-only session cookies |
| `/quotes` | Customers | My Quotes: own requests only (`list_quotes(workspace="customer")`) |
| `/owner` | Owner | Quote inbox: needs review / approved and answered (`workspace="owner"`) |
| `/quotes/{id}` | The quote's customer or owner | Itemized ticket, event details, blockers, review checklist or accept/decline, history |
| `POST /quotes/{id}/approve` | Owner | `QuoteService.approve` with the displayed revision and ticked review codes |
| `POST /quotes/{id}/respond` | Customer | `QuoteService.respond` with `accept` or `decline` |
| `/healthz` | Monitoring | `{"status": "ok"}` |

Browser forms send only the quote ID, the revision they displayed and the chosen action. Prices, totals, status and permissions all come from `quote_view` / `QuoteService`, which recheck every action.

## Accounts and roles

- **Identity:** every request's user comes from Supabase verifying the access token (`GET /auth/v1/user`), cached for 60 seconds. Expired access tokens are refreshed with the refresh token. IDs or roles in form fields are ignored.
- **Owner role:** decided on the server by `OWNER_USER_IDS` (Supabase user IDs). Sign-up always creates a customer. The first ID is the business that customer requests are routed to.
- **Sessions:** `cqa_access` / `cqa_refresh` cookies, `HttpOnly`, `SameSite=Lax`, `Secure` in production. Static files and `/healthz` never touch them. Sign out revokes the session in Supabase (global sign-out) even if only the refresh cookie is left, then clears the cookies.
- **Cross-site protection:** form posts whose `Origin`/`Referer` (scheme and host) is another site get a 403; in production a post with neither header is refused too. This relies on `--proxy-headers` in `render.yaml`'s start command (so the app sees `https`); keep it there.
- **Messages after actions** ("Quote approved", "You're signed out") travel in a one-time `cqa_notice` cookie, so a link can't fake them.
- **Responsiveness:** Supabase calls run in a thread pool with a 5-second timeout, so a slow auth service doesn't freeze other requests or the health check.
- **Privacy:** another account's quote returns the same 404 as a missing one. Signed-in pages are `Cache-Control: no-store`.
- **Failures:** if Supabase Auth or the database is unreachable (or `QUOTE_DATABASE_URL` is missing in production), quote pages show a "temporarily unavailable" message instead of crashing, and nothing claims to have saved. The rest of the site keeps working.

### Supabase Auth settings the app expects

- **Confirm email: off** (Authentication → Sign In / Providers → Email). New projects have it on; the built-in mailer is heavily rate-limited and the app has no email-confirmation callback, so a demo sign-up would stall. If it is left on, sign-up shows "Check your inbox to confirm your email".
- **Site URL:** set to the Render URL (Authentication → URL Configuration) so any Supabase email links point at the app, not `localhost:3000`.
- **Rate limits:** Supabase limits sign-ins and token refreshes per IP, and every request comes from Render's single server IP. Check Authentication → Rate Limits before a class demo. A rate-limited refresh shows a retry page and keeps the session; it does not sign people out.

### Make the owner account (once, after deploy)

1. On the live site, create an account with the owner's email.
2. Supabase → Authentication → Users → copy that user's **UID**.
3. Render → the service → Environment → add `OWNER_USER_IDS` = that UID → Save (Render redeploys).
4. Sign in as the owner: you land on the quote inbox.

## Run locally

```sh
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m unittest discover -s tests            # app tests skip without FastAPI installed
AUTH_BACKEND=memory uvicorn app.main:app --reload
```

`AUTH_BACKEND=memory` is a local preview with no Supabase: it creates `owner@example.com` and `customer@example.com` (password `catering-demo`) and one submitted quote in `var/quotes.sqlite3`. It is refused when `APP_ENV=production`. Without `QUOTE_DATABASE_URL`, local runs use that SQLite file; production requires Postgres.

## Environment variables

| Name | Where | Notes |
| --- | --- | --- |
| `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | Render | Enables sign-in. Publishable key only; never the secret key |
| `QUOTE_DATABASE_URL` | Render | Supabase session-pooler URI; server only |
| `OWNER_USER_IDS` | Render | Added to `render.yaml` in this PR. Render does not prompt for keys added after the blueprint was created, so add it in the dashboard |
| `ANTHROPIC_API_KEY` | Render | Used by the chat PR |
| `APP_ENV`, `APP_DATASET` | `render.yaml` | `production`, `sample` |

## Design notes

- **One service, no frontend build.** Server-rendered Jinja2; teammates' Python modules are called directly. `app/quotes.py` wires `QuoteService` to Postgres (or local SQLite) and `ai_service`'s trusted `ServerContext`, and turns review/blocker codes into plain sentences.
- **Displayed money always comes from data or the engine.** The home ticket is priced by `calculate_quote`; quote screens show `quote_view` amounts.
- **Branding uses `display_name` only.** `catalog.make_scrubber` applies `meta.branding.item_aliases` and removes the source name; tests cover both datasets.
- **Visual system:** pine ink on linen, herb green for actions, mustard highlighter; status chips are amber (pending), green (ready/accepted) and grey (declined). Bricolage Grotesque, Figtree and IBM Plex Mono. The quote is a kitchen order ticket with a status stamp.

## Database

Apply in order in the Supabase SQL editor: `202610190001_quote_storage.sql`, then `202610200001_conversations.sql`. Both are server-only (RLS on, no browser grants). Verified on PostgreSQL 16, including C's `tests/integration` live test.

## Next PR

Customer chat (`ai_service.Conversation`) saved per customer in `catering_private.conversations`, submit to `QuoteService.submit` with `business_owner_id`, and customer revisions; then `requests_open` turns on the home page "Start a quote request" button.
