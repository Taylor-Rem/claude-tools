-- orders: one row per Stripe Checkout session, pickup only. Written as
-- `pending` when the customer is sent to Checkout; the Stripe webhook marks it
-- `paid`. The owner moves it on: ready, collected (or cancelled).
CREATE TABLE IF NOT EXISTS orders (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  stripe_session_id TEXT UNIQUE,
  name              TEXT,
  email             TEXT,
  phone             TEXT,
  items             TEXT NOT NULL DEFAULT '[]',   -- JSON: [{id, name, qty, price_cents}]
  summary           TEXT,                         -- "2 × Pho, 1 × Iced coffee"
  total_cents       INTEGER NOT NULL DEFAULT 0,
  note              TEXT,                         -- the customer's pickup note
  mode              TEXT,                         -- test | live (the Stripe key's mode)
  status            TEXT NOT NULL DEFAULT 'pending',
  owner_notes       TEXT,
  ip_hash           TEXT,
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at        TEXT
);
CREATE INDEX IF NOT EXISTS orders_status ON orders (status, id);
CREATE INDEX IF NOT EXISTS orders_ip ON orders (ip_hash, created_at);
