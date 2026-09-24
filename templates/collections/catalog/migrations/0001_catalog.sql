-- catalog (scaffold): what the site sells, and when it is open for pickup.
CREATE TABLE IF NOT EXISTS products (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  description TEXT,
  category    TEXT,
  image       TEXT,                      -- a path under images/
  active      INTEGER NOT NULL DEFAULT 1,
  sort        INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at  TEXT
);
CREATE TABLE IF NOT EXISTS variants (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id  INTEGER NOT NULL REFERENCES products (id),
  name        TEXT NOT NULL DEFAULT 'Regular',
  price_cents INTEGER NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS hours (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  weekday INTEGER NOT NULL,              -- 0 = Sunday
  opens   TEXT NOT NULL,                 -- 11:00
  closes  TEXT NOT NULL                  -- 21:00
);
