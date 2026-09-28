-- routes: a service business's stops, one row per stop per day, in order.
-- Built by text from "keep my pool routes: stops per day, done or skipped"
-- (PLAYBOOK § Web tools, the worked example). `day` is a date on the site's
-- own clock (2026-09-29); `stop` is the order within the day.
CREATE TABLE IF NOT EXISTS routes (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  day        TEXT NOT NULL,
  stop       INTEGER NOT NULL DEFAULT 1,
  customer   TEXT NOT NULL,
  job        TEXT,
  area       TEXT,
  status     TEXT NOT NULL DEFAULT 'to do',
  notes      TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS routes_day ON routes (day, stop);
