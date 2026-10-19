-- Apply once in the team's Supabase SQL editor (postgres migration role).
-- Quotes are server-only: the frontend calls authenticated Python endpoints.
-- This creates only quote storage, not Auth accounts, menus, or billing tables.
BEGIN;
CREATE SCHEMA catering_private;
REVOKE ALL ON SCHEMA catering_private FROM PUBLIC, anon, authenticated;

CREATE TABLE catering_private.quotes (
    quote_id uuid PRIMARY KEY,
    owner_id uuid NOT NULL,
    customer_id uuid NOT NULL,
    revision bigint NOT NULL CHECK (revision >= 1),
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT quote_envelope CHECK ((
        jsonb_typeof(payload) = 'object'
        AND payload ?& ARRAY['quote_id', 'owner_id', 'customer_id', 'revision', 'versions']
        AND payload->>'quote_id' = quote_id::text
        AND payload->>'owner_id' = owner_id::text
        AND payload->>'customer_id' = customer_id::text
        AND jsonb_typeof(payload->'revision') = 'number'
        AND payload->>'revision' = revision::text
        AND jsonb_typeof(payload->'versions') = 'array'
        AND jsonb_array_length(payload->'versions') > 0
    ) IS TRUE)
);
CREATE INDEX quotes_customer_created ON catering_private.quotes (customer_id, created_at DESC, quote_id DESC);
CREATE INDEX quotes_owner_created ON catering_private.quotes (owner_id, created_at DESC, quote_id DESC);
ALTER TABLE catering_private.quotes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON catering_private.quotes FROM PUBLIC, anon, authenticated;
-- No client policies/grants: browser Auth users cannot directly read/write quotes.
-- Python uses the server-only database connection; it must enforce actor access.
COMMIT;
