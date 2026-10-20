# Web App (D)

Status (Oct 20, 2026): **PR 3 of 3.** Customers can now request a quote through the AI chat: the assistant asks for missing details, prices from the menu through C's engine, and the customer sends the draft to the owner. Sign-in, My Quotes, the owner inbox and approval are from PR 2.

## Pages and actions

| Route | Who | What happens |
| --- | --- | --- |
| `/` | Everyone | Home page, menu, example ticket priced by the quote engine |
| `/login`, `/login?mode=signup` | Everyone | Sign in or create a customer account (Supabase Auth) |
| `POST /login`, `POST /signup`, `POST /logout` | Everyone | Sets or clears HTTP-only session cookies |
| `/chat` | Customers | The quote assistant: conversation on the left, live draft ticket on the right |
| `POST /chat/send` | Customers | One message to B's `Conversation`; returns the updated messages and draft (JSON for the page script, redirect without JavaScript) |
| `POST /chat/submit` | Customers | `QuoteService.submit` with the conversation's last evaluated request; links the quote to the conversation |
| `POST /chat/new` | Customers | Start a fresh request |
| `/quotes` | Customers | My Quotes: own requests only (`list_quotes(workspace="customer")`) |
| `/owner` | Owner | Quote inbox: needs review / approved and answered (`workspace="owner"`) |
| `/quotes/{id}` | The quote's customer or owner | Itemized ticket, event details, blockers, review checklist or accept/decline, history |
| `POST /quotes/{id}/approve` | Owner | `QuoteService.approve` with the displayed revision and ticked review codes |
| `POST /quotes/{id}/respond` | Customer | `QuoteService.respond` with `accept` or `decline` |
| `/healthz` | Monitoring | `{"status": "ok"}` |

Browser forms send only the quote ID, the revision they displayed and the chosen action. Prices, totals, status and permissions all come from `quote_view` / `QuoteService`, which recheck every action.

## Customer chat

- **Who does what:** the model reads the customer's words, asks questions and picks menu items; `quote_engine` prices them and checks rules; the price guard rejects any dollar amount the model invents. The draft panel shows code-computed amounts only.
- **Saved conversations:** each turn is saved in `catering_private.conversations` (SQLite locally) with a revision check, so a refresh or sign-out keeps the chat and a second tab can't overwrite it. On load, the last evaluated request is re-checked against the current menu and time to rebuild the draft.
- **Submit:** only when the latest evaluation says `needs_owner_review` (all details present, nothing blocking) and the customer ticks the box confirming the date, guests, address and allergies shown on the draft. The quote id is derived from the conversation id, so a double click, a second tab or a retry after a crash can never create two quotes. The customer's message is saved before the model answers and submit waits for the reply, so a draft that is being changed can't be sent. The server re-runs `QuoteService.submit`, which rechecks everything; the quote is routed to `OWNER_USER_IDS[0]`, never to a business named in the chat. After submitting, the next visit starts a new conversation.
- **Limits (cost control):** messages up to 1,200 characters; 15 customer messages per conversation; per customer 8 messages a minute, 40 a day and 6 new conversations a day; 400 replies a day for the whole site; one reply at a time. Each reply may call the model at most 5 times within 75 seconds (30 s per call, no retries), and older menu-tool results are shortened before being resent. Model or network failures show a polite fallback; nothing crashes. Also set a monthly spend limit in the provider console. The per-customer lock and the site-wide daily cap live in the web process, so they assume one worker (the `render.yaml` start command runs one); add a shared counter before scaling out.
- **Model choice:** `LLM_PROVIDER=anthropic` (default when `ANTHROPIC_API_KEY` is set, model from `ANTHROPIC_MODEL`) or `openai` (`OPENAI_API_KEY` + `OPENAI_MODEL`; set `OPENAI_REASONING_EFFORT=none` for models such as gpt-6-luna that refuse tools with reasoning on). `LLM_PROVIDER=scripted` is a local preview model that needs no key and is refused in production. With no model configured, the home page doesn't offer requests and `/chat` says the assistant is unavailable.
- **Dataset:** `APP_DATASET=demo` is A's frozen 22-item menu for the presentation (`render.yaml` now sets it).

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
AUTH_BACKEND=memory LLM_PROVIDER=scripted APP_DATASET=demo uvicorn app.main:app --reload
```

`AUTH_BACKEND=memory` is a local preview with no Supabase: it creates `owner@example.com` and `customer@example.com` (password `catering-demo`) and one submitted quote in `var/quotes.sqlite3`. It is refused when `APP_ENV=production`. Without `QUOTE_DATABASE_URL`, local runs use that SQLite file; production requires Postgres.

## Environment variables

| Name | Where | Notes |
| --- | --- | --- |
| `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` | Render | Enables sign-in. Publishable key only; never the secret key |
| `QUOTE_DATABASE_URL` | Render | Supabase session-pooler URI; server only |
| `OWNER_USER_IDS` | Render | Added to `render.yaml` in this PR. Render does not prompt for keys added after the blueprint was created, so add it in the dashboard |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` | Render | Claude for the chat (default provider) |
| `LLM_PROVIDER`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_REASONING_EFFORT` | Render | Optional: `LLM_PROVIDER=openai` to test with OpenAI |
| `APP_ENV`, `APP_DATASET` | `render.yaml` | `production`, `demo` |

## Design notes

- **One service, no frontend build.** Server-rendered Jinja2; teammates' Python modules are called directly. `app/quotes.py` wires `QuoteService` to Postgres (or local SQLite) and `ai_service`'s trusted `ServerContext`, and turns review/blocker codes into plain sentences.
- **Displayed money always comes from data or the engine.** The home ticket is priced by `calculate_quote`; quote screens show `quote_view` amounts.
- **Branding uses `display_name` only.** `catalog.make_scrubber` applies `meta.branding.item_aliases` and removes the source name; tests cover both datasets.
- **Visual system: a restaurant pass.** Customers are front of house (linen, herb green for actions, mustard highlighter); the owner is the kitchen (dark pine header, mustard "Kitchen" tag, set by `body.role-owner`). Status chips are amber (pending), green (ready/accepted) and grey (declined). Bricolage Grotesque, Figtree and IBM Plex Mono.
- **Signature: the order ticket.** Thermal paper with torn edges (CSS mask), barcode and an inked status stamp, used on the home page, the chat draft, quote pages and the owner inbox, where tickets awaiting review hang on a rail (a swipeable strip on phones). The chat draft "prints" again when its total changes (`chat.js`); the owner checklist counts checks done (`review.js`).
- **Quality floor:** no horizontal scroll from 320px to desktop, visible focus on light and dark areas, text contrast at least 4.5:1, and all animation off under `prefers-reduced-motion`.

## Database

Apply in order in the Supabase SQL editor: `202610190001_quote_storage.sql`, then `202610200001_conversations.sql`. Both are server-only (RLS on, no browser grants). Verified on PostgreSQL 16, including C's `tests/integration` live test.

## Next

Owner menu editing is implemented at `/owner/menu`, with current DB menu reads for chat, quotes and public prices. See [menu-editing.md](menu-editing.md) for rollout status. Customer revisions of a submitted quote through chat remain outside this change; owners can explicitly reprice a pending draft.
