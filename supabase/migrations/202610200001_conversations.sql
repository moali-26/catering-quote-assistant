-- Apply once, after 202610190001_quote_storage.sql (it creates catering_private).
-- Saves each customer's AI chat so a refresh or sign-out does not lose it.
-- Server-only like quotes: no browser grants or policies; Python checks the owner of every row.
-- Requires Postgres 15+ (Supabase default) for ON DELETE SET NULL (column).
BEGIN;
-- Lets a conversation reference a quote only when both belong to the same customer and owner.
ALTER TABLE catering_private.quotes
    ADD CONSTRAINT quotes_participants_key UNIQUE (quote_id, customer_id, owner_id);

CREATE TABLE catering_private.conversations (
    conversation_id uuid PRIMARY KEY,
    customer_id uuid NOT NULL,
    owner_id uuid NOT NULL,
    messages jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(messages) = 'array'),
    quote_id uuid,
    revision bigint NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT conversations_quote_same_participants
        FOREIGN KEY (quote_id, customer_id, owner_id)
        REFERENCES catering_private.quotes (quote_id, customer_id, owner_id)
        ON DELETE SET NULL (quote_id)
);
CREATE INDEX conversations_customer_updated
    ON catering_private.conversations (customer_id, updated_at DESC);
CREATE INDEX conversations_quote
    ON catering_private.conversations (quote_id) WHERE quote_id IS NOT NULL;
ALTER TABLE catering_private.conversations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON catering_private.conversations FROM PUBLIC, anon, authenticated;
COMMIT;
