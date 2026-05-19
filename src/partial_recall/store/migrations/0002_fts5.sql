-- 0002_fts5.sql — full-text search (FTS5) over chunks.text_preview
--
-- partial-recall v0.2.4. Adds the chunks_fts virtual table and the
-- triggers that keep it in lock-step with chunks. Initial population
-- runs once at migration time.
--
-- Tokenizer choice: unicode61 with diacritic-folding so "rāj"
-- matches "raj". For CJK / South Asian script edge cases the
-- v0.3.0 chunker work will introduce a tokenizer-aware path; until
-- then unicode61 handles ~all our cases reasonably.
--
-- Note: FTS5 is built in to SQLite from ~3.9 onwards. CPython on
-- macOS / Ubuntu / Windows all ship FTS5 in their bundled SQLite.
-- If a user is on a stripped-down SQLite build this migration
-- raises at apply time; the next PR (doctor command extension)
-- will surface this as a named check.

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    text_preview,
    content='chunks',
    content_rowid='chunk_id',
    tokenize='unicode61 remove_diacritics 1'
);

-- Initial population from existing chunks
INSERT INTO chunks_fts(rowid, text_preview)
    SELECT chunk_id, text_preview FROM chunks WHERE text_preview IS NOT NULL;

-- Sync triggers: external-content FTS5 needs explicit propagation
CREATE TRIGGER chunks_fts_after_insert AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text_preview)
        VALUES (new.chunk_id, new.text_preview);
END;

CREATE TRIGGER chunks_fts_after_delete AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text_preview)
        VALUES ('delete', old.chunk_id, old.text_preview);
END;

CREATE TRIGGER chunks_fts_after_update AFTER UPDATE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text_preview)
        VALUES ('delete', old.chunk_id, old.text_preview);
    INSERT INTO chunks_fts(rowid, text_preview)
        VALUES (new.chunk_id, new.text_preview);
END;

UPDATE schema_meta SET schema_version = 2;
