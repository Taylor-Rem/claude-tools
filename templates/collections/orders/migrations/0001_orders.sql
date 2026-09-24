-- orders (scaffold): one row per paid Stripe Checkout session, pickup only.
CREATE TABLE IF NOT EXISTS orders (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  stripe_session_id TEXT UNIQUE,
  name              TEXT,
  email             TEXT,
  phone             TEXT,
  items             TEXT NOT NULL DEFAULT '[]',   -- JSON: [{variant_id, name, qty, price_cents}]
  total_cents       INTEGER NOT NULL DEFAULT 0,
  pickup_at         TEXT,
  status            TEXT NOT NULL DEFAULT 'paid',
  created_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at        TEXT
);
