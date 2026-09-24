-- submissions: what people send from a form on the site. The common fields
-- get columns; everything the form sent is also kept whole in `fields` (JSON).
CREATE TABLE IF NOT EXISTS submissions (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  form       TEXT NOT NULL DEFAULT 'contact',
  name       TEXT,
  email      TEXT,
  phone      TEXT,
  message    TEXT,
  fields     TEXT NOT NULL DEFAULT '{}',
  status     TEXT NOT NULL DEFAULT 'new',
  notes      TEXT,
  ip_hash    TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS submissions_form ON submissions (form, id);
CREATE INDEX IF NOT EXISTS submissions_ip ON submissions (ip_hash, created_at);
