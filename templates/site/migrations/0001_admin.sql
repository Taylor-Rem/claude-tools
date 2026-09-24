-- The owner's sign-in for /admin (functions/admin/*). A link token is kept
-- only as its SHA-256, works once and for 15 minutes; a session is kept as
-- the SHA-256 of the id in the signed cookie, for 14 days or until sign-out.
CREATE TABLE IF NOT EXISTS admin_tokens (
  token_hash TEXT PRIMARY KEY,
  email      TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  used_at    INTEGER
);
CREATE INDEX IF NOT EXISTS admin_tokens_created ON admin_tokens (created_at);

CREATE TABLE IF NOT EXISTS admin_sessions (
  id_hash    TEXT PRIMARY KEY,
  email      TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
