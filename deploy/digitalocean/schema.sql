-- Qualified presentation corpus (binary + manifest metadata)
CREATE TABLE IF NOT EXISTS qualified_files (
    id BIGSERIAL PRIMARY KEY,
    filename TEXT NOT NULL UNIQUE,
    batch_id TEXT NOT NULL,
    file_type TEXT NOT NULL,
    content BYTEA NOT NULL,
    content_hash TEXT NOT NULL,
    source_url TEXT NOT NULL,
    manifest JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_qualified_files_batch_id ON qualified_files (batch_id);
CREATE INDEX IF NOT EXISTS idx_qualified_files_content_hash ON qualified_files (content_hash);
CREATE INDEX IF NOT EXISTS idx_qualified_files_source_url ON qualified_files (source_url);

-- O(1) exact-duplicate index
CREATE TABLE IF NOT EXISTS dedupe_hashes (
    content_hash TEXT PRIMARY KEY,
    filename TEXT NOT NULL
);
