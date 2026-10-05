-- customers: the customer book (ROADMAP B122). One row a customer, found
-- again by phone or email, and the jobs done for them. `db customers …` and
-- `db jobs …` write it; /admin/customers shows it; `db export` hands it over.
CREATE TABLE IF NOT EXISTS customers (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  phone      TEXT,                       -- as shown: 801-555-0134 for a US number
  phone_key  TEXT,                       -- the last ten digits, how a phone is matched
  email      TEXT,                       -- lower case
  address    TEXT,
  notes      TEXT,                       -- the owner's: gate code, pool size, the dog
  tags       TEXT,                       -- comma separated: weekly, spa, commercial
  contact    TEXT NOT NULL DEFAULT 'ok', -- 'ok', or 'stop' once they asked not to be contacted
  source     TEXT,                       -- where the record came from: import, admin, text, booking, form, estimate, pay
  last_seen  TEXT,                       -- YYYY-MM-DD, the last booking or job done
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS customers_phone ON customers (phone_key);
CREATE INDEX IF NOT EXISTS customers_email ON customers (email);
CREATE INDEX IF NOT EXISTS customers_seen ON customers (last_seen);

CREATE TABLE IF NOT EXISTS jobs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id   INTEGER NOT NULL REFERENCES customers (id),
  customer_name TEXT,                    -- copied from the customer so the jobs list reads by name
  date          TEXT,                    -- YYYY-MM-DD, when it was (or will be) done
  what          TEXT NOT NULL,
  amount_cents  INTEGER,                 -- 45000 = $450.00
  status        TEXT NOT NULL DEFAULT 'booked',  -- booked, done, cancelled
  notes         TEXT,
  source        TEXT,                    -- text, admin, booking, estimate, pay, import
  ref           TEXT,                    -- the feeder's own id: a booking id, an invoice id
  created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at    TEXT
);
CREATE INDEX IF NOT EXISTS jobs_customer ON jobs (customer_id, date);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs (status, date);
