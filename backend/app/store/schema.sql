-- Applied idempotently by migrations.py. Connection pragmas (WAL, foreign_keys, busy_timeout)
-- are set per connection in db.py: journal_mode cannot change inside a transaction, and
-- foreign_keys is per-connection state anyway.
-- {{EMBEDDING_DIM}} is substituted from config at migration time.

CREATE TABLE IF NOT EXISTS items (
  id              TEXT PRIMARY KEY,
  type            TEXT NOT NULL CHECK (type IN ('note','url')),
  title           TEXT,
  source_url      TEXT,
  normalized_url  TEXT,
  content_hash    TEXT,
  raw_content     TEXT,
  extracted_text  TEXT,
  status          TEXT NOT NULL CHECK (status IN ('pending','processing','ready','failed')),
  error_code      TEXT,
  error_message   TEXT,
  attempts        INTEGER NOT NULL DEFAULT 0,
  chunk_count     INTEGER NOT NULL DEFAULT 0,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_items_url  ON items(normalized_url) WHERE type = 'url';
CREATE UNIQUE INDEX IF NOT EXISTS ux_items_note ON items(content_hash)   WHERE type = 'note';
CREATE INDEX IF NOT EXISTS ix_items_created ON items(created_at DESC, id DESC);

CREATE TABLE IF NOT EXISTS chunks (
  id              INTEGER PRIMARY KEY,
  item_id         TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
  ordinal         INTEGER NOT NULL,
  section         TEXT,
  context_header  TEXT NOT NULL,
  text            TEXT NOT NULL,
  token_count     INTEGER NOT NULL,
  UNIQUE (item_id, ordinal)
);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  context_header, text, content='chunks', content_rowid='id', tokenize='porter unicode61'
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
  embedding float[{{EMBEDDING_DIM}}] distance_metric=cosine
);

-- Virtual tables don't cascade. External-content FTS5 'delete' must receive the exact old values.
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
  INSERT INTO chunks_fts(rowid, context_header, text) VALUES (new.id, new.context_header, new.text);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, context_header, text)
    VALUES ('delete', old.id, old.context_header, old.text);
  DELETE FROM chunks_vec WHERE rowid = old.id;
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
  INSERT INTO chunks_fts(chunks_fts, rowid, context_header, text)
    VALUES ('delete', old.id, old.context_header, old.text);
  INSERT INTO chunks_fts(rowid, context_header, text) VALUES (new.id, new.context_header, new.text);
END;
