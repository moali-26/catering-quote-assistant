# Owner Software Plan (Stripe test mode)

The business owner buys the Catering Quote Assistant through Stripe Checkout. **Test mode only**: live keys are refused, and no real money moves. This is separate from food quotes; customers never pay in this app, and accepting a quote never charges anything.

E built the Stripe module (`billing/`). This page covers how it's wired into the web app (`app/billing_app.py`, routes in `app/main.py`).

## How it works

```
Owner inbox ──► /owner/billing ──► POST /owner/billing/checkout ──► Stripe Checkout (test card)
                                                                        │
          ┌─────────────────────────────────────────────────────────────┤
          ▼                                                             ▼
/owner/billing/success?session_id=…                     POST /stripe/webhook (signed by Stripe)
  asks Stripe (verify_checkout)                           re-fetches the session (handle_webhook)
          └──────────────► record_paid(owner) ◄─────────────────────────┘
```

- **Paid only when Stripe says so.** The success page asks Stripe for the session; the webhook is signature-checked and re-fetches the session. Landing on the success URL proves nothing.
- **Bound to the signed-in owner.** `client_reference_id` comes from the server-verified Supabase user, and confirmation rejects another account's session or a mismatched session ID.
- **Webhook only records payments for configured owners** (`OWNER_USER_IDS`).
- **Idempotent.** The success page and webhook can both fire; the first confirmed payment is kept. A paid owner can't start a second checkout.
- **Security middleware:** `/stripe/webhook` is the only POST exempt from the Origin/Referer check and session lookup, because Stripe calls it server-to-server. Its signature is the check. Every other POST is still refused without an Origin/Referer in production.
- **Fails safe.** Missing or live keys turn checkout off with a page message; the rest of the site keeps working.

| Route | Who | What |
| --- | --- | --- |
| `GET /owner/billing` | Owner | Plan status; "Buy the software plan" button when not yet paid |
| `POST /owner/billing/checkout` | Owner | Creates a Checkout Session and redirects to Stripe |
| `GET /owner/billing/success` | Owner | Confirms with Stripe, records payment, redirects with a notice |
| `POST /stripe/webhook` | Stripe | Signed `checkout.session.completed` / `async_payment_succeeded` |

The owner inbox shows "Software plan: Active / Not purchased" linking to the billing page.

## Setup (D or E, about 10 minutes)

1. **Stripe dashboard, in Test mode** (toggle at the top right).
2. **Product catalog → Add product:** e.g. "Catering Quote Assistant — Owner plan", one-time price (e.g. $29.00). Copy the **price ID** (`price_...`).
3. **Developers → API keys:** copy the **secret key** (`sk_test_...`). Never the live key.
4. **Developers → Webhooks → Add endpoint:**
   - URL: `https://<your-render-app>.onrender.com/stripe/webhook`
   - Events: `checkout.session.completed`, `checkout.session.async_payment_succeeded`
   - Copy the **signing secret** (`whsec_...`).
5. **Render → Environment:** set `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID`, `STRIPE_WEBHOOK_SECRET` (they're in `render.yaml` with `sync: false`; add them in the dashboard if the blueprint already exists).
6. **Supabase SQL editor:** apply `supabase/migrations/202610200002_owner_billing.sql` (after `202610190001_quote_storage.sql`).
7. **Try it:** sign in as the owner → "Software plan" → Buy → card `4242 4242 4242 4242`, any future date, any CVC → back on the plan page it shows **Plan active**.

Local development: without `QUOTE_DATABASE_URL`, payments are stored in `var/billing.sqlite3`. To test the webhook locally, use the Stripe CLI: `stripe listen --forward-to localhost:8000/stripe/webhook` and use the `whsec_` it prints.

## Tests

`tests/test_app_billing.py` (16 tests, no network): customers and signed-out users can't reach billing; checkout uses the session's owner ID and the configured price; success records payment only after Stripe confirms, and refuses unpaid, foreign, mismatched or made-up sessions; webhook works in production without an Origin header while other origin-less posts are still refused; bad signatures are rejected; unknown accounts are ignored; double confirmation records once; unconfigured and live-key setups turn checkout off safely. E's `tests/test_billing.py` covers the Stripe module itself.

## Not done

- Live Stripe hasn't been exercised from the deployed app yet (needs steps 1–6).
- No subscriptions, refunds or invoices: a one-time test purchase is enough for the course requirement.
- Paid status is shown to the owner but doesn't lock any features.
