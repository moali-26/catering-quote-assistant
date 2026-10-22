-- Owner archive (D). Apply after 202610190001_quote_storage.sql.
-- Which quotes the owner has archived, to hide them from the inbox. Quote records are not
-- changed. Server-only like quotes: no browser grants or policies. Deleting a quote removes
-- its archive row too.
BEGIN;
CREATE TABLE catering_private.quote_archive (
    owner_id uuid NOT NULL,
    quote_id uuid NOT NULL REFERENCES catering_private.quotes (quote_id) ON DELETE CASCADE,
    archived_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_id, quote_id)
);
ALTER TABLE catering_private.quote_archive ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON catering_private.quote_archive FROM PUBLIC, anon, authenticated;
COMMIT;
