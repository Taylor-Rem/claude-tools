-- bookings (scaffold): slots the owner opens, and requests against them.
CREATE TABLE IF NOT EXISTS booking_slots (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  starts_at  TEXT NOT NULL,              -- ISO local time, e.g. 2026-10-06T09:00
  minutes    INTEGER NOT NULL DEFAULT 60,
  capacity   INTEGER NOT NULL DEFAULT 1,
  label      TEXT,
  status     TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE TABLE IF NOT EXISTS bookings (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_id    INTEGER REFERENCES booking_slots (id),
  name       TEXT NOT NULL,
  email      TEXT,
  phone      TEXT,
  notes      TEXT,
  status     TEXT NOT NULL DEFAULT 'requested',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS bookings_slot ON bookings (slot_id);
