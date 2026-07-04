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

-- URL catalog: links + metadata only (download later)
CREATE TABLE IF NOT EXISTS url_catalog (
    id BIGSERIAL PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    source_query TEXT DEFAULT '',
    category TEXT DEFAULT '',
    file_type TEXT DEFAULT '',
    mime_type TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    metadata JSONB NOT NULL DEFAULT '{}',
    worker_id INT DEFAULT 0,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_url_catalog_status ON url_catalog (status);
CREATE INDEX IF NOT EXISTS idx_url_catalog_source ON url_catalog (source);
CREATE INDEX IF NOT EXISTS idx_url_catalog_discovered_at ON url_catalog (discovered_at);
