-- partial-recall v0.0.1 initial schema
-- Schema version: 1

CREATE TABLE schema_meta (
    schema_version       INTEGER NOT NULL,
    created_at           TEXT    NOT NULL,
    application          TEXT    NOT NULL,
    application_version  TEXT    NOT NULL
);
INSERT INTO schema_meta (schema_version, created_at, application, application_version)
    VALUES (1, datetime('now'), 'partial-recall', '0.0.1');

CREATE TABLE embedding_runs (
    run_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    owner             TEXT    NOT NULL DEFAULT 'local',
    provider          TEXT    NOT NULL,
    model_name        TEXT    NOT NULL,
    model_version     TEXT,
    dimensions        INTEGER NOT NULL,
    quantization      TEXT    NOT NULL,
    normalized        INTEGER NOT NULL,
    distance_metric   TEXT    NOT NULL,
    chunker_name      TEXT    NOT NULL,
    chunker_version   TEXT    NOT NULL,
    started_at        TEXT    NOT NULL,
    completed_at      TEXT,
    item_count        INTEGER,
    chunk_count       INTEGER,
    is_active         INTEGER NOT NULL DEFAULT 0,
    notes             TEXT
);
CREATE INDEX idx_runs_active ON embedding_runs(is_active);
CREATE INDEX idx_runs_owner ON embedding_runs(owner);

CREATE TABLE items (
    owner             TEXT    NOT NULL DEFAULT 'local',
    item_key          TEXT    NOT NULL,
    corpus            TEXT    NOT NULL,
    corpus_ref        TEXT,
    item_type         TEXT    NOT NULL,
    title             TEXT,
    date              TEXT,
    creators_json     TEXT,
    abstract          TEXT,
    metadata_hash     TEXT    NOT NULL,
    last_indexed_at   TEXT    NOT NULL,
    PRIMARY KEY (owner, corpus, item_key)
);
CREATE INDEX idx_items_corpus ON items(corpus);
CREATE INDEX idx_items_type ON items(item_type);

CREATE TABLE chunks (
    chunk_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner             TEXT    NOT NULL DEFAULT 'local',
    corpus            TEXT    NOT NULL,
    item_key          TEXT    NOT NULL,
    source_type       TEXT    NOT NULL,
    source_ref        TEXT,
    chunk_index       INTEGER NOT NULL,
    char_offset_start INTEGER,
    char_offset_end   INTEGER,
    text_hash         TEXT    NOT NULL,
    text_preview      TEXT,
    chunker_version   TEXT    NOT NULL,
    detected_locale   TEXT,
    indexed_at        TEXT    NOT NULL,
    FOREIGN KEY (owner, corpus, item_key) REFERENCES items(owner, corpus, item_key) ON DELETE CASCADE,
    UNIQUE (owner, corpus, item_key, source_type, source_ref, chunk_index, chunker_version)
);
CREATE INDEX idx_chunks_item   ON chunks(owner, corpus, item_key);
CREATE INDEX idx_chunks_hash   ON chunks(text_hash);
CREATE INDEX idx_chunks_source ON chunks(source_type);
CREATE INDEX idx_chunks_locale ON chunks(detected_locale);

CREATE TABLE vectors (
    vector_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    owner       TEXT    NOT NULL DEFAULT 'local',
    chunk_id    INTEGER NOT NULL,
    run_id      INTEGER NOT NULL,
    vector      BLOB    NOT NULL,
    norm        REAL,
    indexed_at  TEXT    NOT NULL,
    FOREIGN KEY (chunk_id) REFERENCES chunks(chunk_id) ON DELETE CASCADE,
    FOREIGN KEY (run_id)   REFERENCES embedding_runs(run_id) ON DELETE CASCADE,
    UNIQUE (chunk_id, run_id)
);
CREATE INDEX idx_vectors_run   ON vectors(run_id);
CREATE INDEX idx_vectors_chunk ON vectors(chunk_id);

CREATE TABLE faiss_indexes (
    run_id        INTEGER PRIMARY KEY,
    faiss_path    TEXT    NOT NULL,
    index_type    TEXT    NOT NULL,
    built_at      TEXT    NOT NULL,
    vector_count  INTEGER NOT NULL,
    params_json   TEXT,
    FOREIGN KEY (run_id) REFERENCES embedding_runs(run_id) ON DELETE CASCADE
);

CREATE TABLE indexing_progress (
    run_id                INTEGER PRIMARY KEY,
    last_processed_key    TEXT,
    pending_chunk_ids     TEXT,
    failed_chunk_ids_json TEXT,
    updated_at            TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES embedding_runs(run_id) ON DELETE CASCADE
);
