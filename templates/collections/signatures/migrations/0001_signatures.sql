-- signatures: a document sent to one customer to read and sign by link
-- (`sign new`, ROADMAP B128). The text is kept whole as it was sent and is
-- the only copy: the page and the PDF render it each time (no HTML is stored,
-- so what is shown can't drift from what was hashed). The hash is sha256 of
-- `body` (UTF-8), checked when it is signed and again when the PDF is made.
CREATE TABLE IF NOT EXISTS signatures (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  token         TEXT NOT NULL UNIQUE,              -- the link: /sign/<token>, 32 random bytes
  title         TEXT NOT NULL,
  doc_file      TEXT,                              -- where it came from in the workspace (waivers/pool.md)
  body          TEXT NOT NULL,                     -- the document as written (Markdown)
  doc_sha256    TEXT NOT NULL,                     -- sha256 of body when it was sent
  for_name      TEXT NOT NULL,                     -- who it was sent to ("Smith")
  email         TEXT,
  phone         TEXT,
  customer_id   INTEGER,                           -- the customer book's id, when the site has one
  status        TEXT NOT NULL DEFAULT 'sent',      -- sent / signed / void
  signed_name   TEXT,                              -- the full name they typed
  signed_at     TEXT,                              -- UTC, 2026-10-05T22:31:07Z
  signed_ip     TEXT,
  signed_agent  TEXT,                              -- their browser, as it described itself
  signed_sha256 TEXT,                              -- sha256 of body at the moment of signing
  pdf           TEXT,                              -- the signed PDF in the workspace (sign show / sign pdf)
  filed_at      TEXT,
  notes         TEXT,
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS signatures_status ON signatures (status, id);
