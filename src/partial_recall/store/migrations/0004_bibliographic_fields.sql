-- 0004_bibliographic_fields.sql — the fields that identify a volume
--
-- partial-recall v0.4.x, closes #41.
--
-- The Zotero adapter already read these from SQLite and dropped them.
-- For a multi-volume set every volume shares one title, one date, and
-- one set of creators, so search returned N identical results and a
-- caller had to open the PDFs to learn which volume a hit came from.
--
-- Adds to items:
--   volume            — Zotero "Volume" field
--   edition           — Zotero "Edition" field
--   series            — Zotero "Series" field
--   series_number     — Zotero "Series Number" field
--   number_of_volumes — Zotero "# of Volumes" field
--   publisher         — Zotero "Publisher" field
--   place             — Zotero "Place" field
--
-- Existing rows get NULL and pick the values up on the next index run.

ALTER TABLE items ADD COLUMN volume            TEXT;
ALTER TABLE items ADD COLUMN edition           TEXT;
ALTER TABLE items ADD COLUMN series            TEXT;
ALTER TABLE items ADD COLUMN series_number     TEXT;
ALTER TABLE items ADD COLUMN number_of_volumes TEXT;
ALTER TABLE items ADD COLUMN publisher         TEXT;
ALTER TABLE items ADD COLUMN place             TEXT;

UPDATE schema_meta SET schema_version = 4;
