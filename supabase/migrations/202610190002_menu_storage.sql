-- Owner-editable menus (Part A). Apply AFTER 202610190001_quote_storage.sql,
-- which creates the catering_private schema. Server-only, like quotes:
-- the browser calls authenticated Python endpoints; no client grants or policies.
-- NOT yet applied to a Supabase project.
BEGIN;
CREATE TABLE catering_private.menus (
    owner_id uuid PRIMARY KEY,               -- the business owner's Supabase Auth UUID
    revision bigint NOT NULL CHECK (revision >= 1),
    payload jsonb NOT NULL,                  -- {owner_id, revision, menu, updated_at, updated_by, change_log}
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT menu_envelope CHECK ((
        jsonb_typeof(payload) = 'object'
        AND payload ?& ARRAY['owner_id', 'revision', 'menu']
        AND payload->>'owner_id' = owner_id::text
        AND payload->>'revision' = revision::text
        AND jsonb_typeof(payload->'menu') = 'object'
        AND jsonb_typeof(payload->'menu'->'items') = 'array'
    ) IS TRUE)
);
ALTER TABLE catering_private.menus ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON catering_private.menus FROM PUBLIC, anon, authenticated;
COMMIT;
