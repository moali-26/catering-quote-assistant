-- Owner software plan payments (Stripe test mode). Apply after 202610190001_quote_storage.sql
-- (it creates catering_private). Server-only like quotes: no browser grants or policies.
-- A row is written only after Stripe confirms payment (success-page verify or signed webhook).
BEGIN;
CREATE TABLE catering_private.owner_billing (
    owner_id uuid PRIMARY KEY,               -- the owner's Supabase Auth UUID
    paid boolean NOT NULL DEFAULT false,
    session_id text,                         -- Stripe Checkout Session id (cs_test_...)
    amount_total_cents bigint,
    currency text,
    paid_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE catering_private.owner_billing ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON catering_private.owner_billing FROM PUBLIC, anon, authenticated;
COMMIT;
