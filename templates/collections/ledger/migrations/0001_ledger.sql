-- ledger: the owner's receipts (ROADMAP B124). One row a receipt: what the
-- photo (or a forwarded email) says, read by Patch and written with
-- `db ledger add`; /admin/ledger shows it with the month's total; `db export`
-- hands it over with the photos zipped. A record of what was spent, not
-- bookkeeping: the categories are the owner's words, not a CPA's.
CREATE TABLE IF NOT EXISTS ledger (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  date         TEXT NOT NULL,           -- YYYY-MM-DD, the date on the receipt
  month        TEXT GENERATED ALWAYS AS (substr(date, 1, 7)) VIRTUAL,  -- 2026-10, for the month chooser
  vendor       TEXT NOT NULL,           -- who was paid, as the receipt says it: Home Depot, Maverik
  amount_cents INTEGER NOT NULL,        -- the total paid, tax in: 4218 = $42.18; a refund is negative
  category     TEXT,                    -- the owner's word: fuel, supplies, equipment, vehicle, meals, other
  note         TEXT,                    -- what it was for: "truck: oil change", "chlorine for the Smiths"
  photo        TEXT,                    -- receipts/2026-10/<file> in the workspace, kept by Patch (not on the site)
  source       TEXT,                    -- text, email, admin, import
  created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at   TEXT
);
CREATE INDEX IF NOT EXISTS ledger_date ON ledger (date);
CREATE INDEX IF NOT EXISTS ledger_vendor ON ledger (vendor);
