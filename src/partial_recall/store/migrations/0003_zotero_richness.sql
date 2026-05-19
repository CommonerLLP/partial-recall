-- 0003_zotero_richness.sql — Zotero library-location fields + collections
--
-- partial-recall v0.2.4. Models more of what Zotero stores so a
-- Claude session can answer questions like "where's the physical
-- copy of this book?" or "what's in my Caste Studies collection?"
--
-- Adds to items:
--   archive          — Zotero "Archive" field (e.g. "British Library")
--   archive_location — Zotero "Loc. in Archive" field
--   call_number      — Zotero "Call Number" field
--   library_catalog  — Zotero "Library Catalog" field
--
-- Adds collections + item_collections tables for membership.

ALTER TABLE items ADD COLUMN archive          TEXT;
ALTER TABLE items ADD COLUMN archive_location TEXT;
ALTER TABLE items ADD COLUMN call_number      TEXT;
ALTER TABLE items ADD COLUMN library_catalog  TEXT;

CREATE TABLE collections (
    owner           TEXT NOT NULL DEFAULT 'local',
    corpus          TEXT NOT NULL,
    collection_key  TEXT NOT NULL,
    name            TEXT NOT NULL,
    parent_key      TEXT,
    last_indexed_at TEXT NOT NULL,
    PRIMARY KEY (owner, corpus, collection_key)
);
CREATE INDEX idx_collections_corpus ON collections(owner, corpus);
CREATE INDEX idx_collections_parent ON collections(owner, corpus, parent_key);

CREATE TABLE item_collections (
    owner           TEXT NOT NULL DEFAULT 'local',
    corpus          TEXT NOT NULL,
    item_key        TEXT NOT NULL,
    collection_key  TEXT NOT NULL,
    PRIMARY KEY (owner, corpus, item_key, collection_key),
    FOREIGN KEY (owner, corpus, item_key)
        REFERENCES items(owner, corpus, item_key) ON DELETE CASCADE,
    FOREIGN KEY (owner, corpus, collection_key)
        REFERENCES collections(owner, corpus, collection_key) ON DELETE CASCADE
);
CREATE INDEX idx_item_collections_collection
    ON item_collections(owner, corpus, collection_key);

UPDATE schema_meta SET schema_version = 3;
