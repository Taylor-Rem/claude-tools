-- records: the generic list. `kind` separates lists that share the table
-- (customer, job, supplier); `data` holds any extra fields as JSON.
CREATE TABLE IF NOT EXISTS records (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  kind       TEXT NOT NULL DEFAULT 'record',
  title      TEXT NOT NULL,
  status     TEXT NOT NULL DEFAULT 'open',
  notes      TEXT,
  data       TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS records_kind ON records (kind, id);
