-- stock: the owner's stock, made by `db add stock --from-sheet` from fernhill-stock.xlsx, sheet Stock.
-- The owner's own columns first, then the house columns every list has.
CREATE TABLE IF NOT EXISTS stock (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  item TEXT NOT NULL,
  kind TEXT,
  on_hand INTEGER,
  reorder_at INTEGER,
  supplier TEXT,
  unit_cost_cents INTEGER,
  last_counted TEXT,
  status TEXT NOT NULL DEFAULT 'stocked',
  notes TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at TEXT
);
