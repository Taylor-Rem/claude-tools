-- catalog: what the site sells (a menu is the same thing), and the hours it
-- is open for pickup. Prices are in cents: 1250 is $12.50.
CREATE TABLE IF NOT EXISTS products (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  description TEXT,
  category    TEXT,                      -- a menu section, a shelf: "Mains", "Candles"
  price_cents INTEGER NOT NULL DEFAULT 0,
  image       TEXT,                      -- a path under images/, optional
  status      TEXT NOT NULL DEFAULT 'on sale',   -- on sale | sold out | hidden
  sort        INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at  TEXT
);
CREATE INDEX IF NOT EXISTS products_shelf ON products (status, category, sort, id);

CREATE TABLE IF NOT EXISTS hours (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  weekday    INTEGER NOT NULL,           -- 0 = Sunday … 6 = Saturday
  opens      TEXT NOT NULL,              -- 11:00, the site's own clock
  closes     TEXT NOT NULL,              -- 21:00
  note       TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at TEXT
);
