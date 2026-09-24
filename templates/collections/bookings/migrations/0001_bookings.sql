-- bookings: the times the owner opens (booking_slots) and the requests people
-- make for them (bookings). A slot's time is a wall-clock time in the site's
-- own zone, written the way a person says it: 2026-10-06T09:00.
CREATE TABLE IF NOT EXISTS booking_slots (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  starts_at  TEXT NOT NULL,              -- local wall-clock time, YYYY-MM-DDTHH:MM
  minutes    INTEGER NOT NULL DEFAULT 60,
  capacity   INTEGER NOT NULL DEFAULT 1, -- how many bookings the slot takes
  label      TEXT,                       -- optional: "Spring opening", "Spa check"
  status     TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS booking_slots_starts ON booking_slots (status, starts_at);

CREATE TABLE IF NOT EXISTS bookings (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  slot_id    INTEGER NOT NULL REFERENCES booking_slots (id),
  starts_at  TEXT NOT NULL,              -- copied from the slot when booked
  name       TEXT NOT NULL,
  email      TEXT,
  phone      TEXT,
  notes      TEXT,                       -- what the customer wrote
  status     TEXT NOT NULL DEFAULT 'requested',
  owner_notes TEXT,                      -- only the owner sees these
  ip_hash    TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS bookings_slot ON bookings (slot_id, status);
CREATE INDEX IF NOT EXISTS bookings_ip ON bookings (ip_hash, created_at);
