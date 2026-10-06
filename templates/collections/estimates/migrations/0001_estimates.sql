-- estimates: what the owner quotes (`estimate new`, by text) and whether the
-- customer accepted it on /estimate/<token>. Money is in cents. `lines` is
-- JSON: [{"what": "3 windows", "cents": 30000}, …]. The token is the
-- unguessable part of the accept link; the number (E-0001) is what people say.
CREATE TABLE IF NOT EXISTS estimates (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  number         TEXT NOT NULL UNIQUE,
  token          TEXT NOT NULL UNIQUE,
  business       TEXT NOT NULL DEFAULT '',  -- the name on the estimate, as it was sent
  customer       TEXT NOT NULL,
  email          TEXT,
  phone          TEXT,
  customer_id    INTEGER,                   -- the customer book's id, when the site has one (B122)
  lines          TEXT NOT NULL,             -- JSON [{what, cents}]
  subtotal_cents INTEGER NOT NULL,
  tax_label      TEXT,                      -- "Sales tax 7.25%", or NULL for none
  tax_cents      INTEGER NOT NULL DEFAULT 0,
  total_cents    INTEGER NOT NULL,
  deposit_cents  INTEGER NOT NULL DEFAULT 0,
  valid_until    TEXT,                      -- YYYY-MM-DD, the last day it can be accepted
  terms          TEXT,                      -- the terms block, from facts.md, as it was sent
  note           TEXT,                      -- a line from the owner to the customer
  status         TEXT NOT NULL DEFAULT 'draft',   -- draft, sent, accepted, declined, void
  sent_at        TEXT,
  accepted_at    TEXT,
  accepted_name  TEXT,                      -- what the customer typed
  accepted_ip    TEXT,                      -- kept as evidence of the acceptance
  accepted_agent TEXT,
  invoice_id     TEXT,                      -- Stripe's invoice (or the deposit's payment link) once followed through
  invoice_url    TEXT,
  booking_id     INTEGER,
  owner_notes    TEXT,
  created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at     TEXT
);
CREATE INDEX IF NOT EXISTS estimates_status ON estimates (status, created_at);
