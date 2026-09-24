# bookings — times the owner opens, and the bookings people make for them

**Status: ready.** The texts it answers: "add a booking calendar", "let
people book a time", "add Tuesday 9am as a booking slot", "close Friday",
"who's booked this week?".

What `db add bookings` puts in the repo:

| file | what it is |
|---|---|
| `migrations/NNNN_bookings.sql` | `booking_slots` (the times: `starts_at` as a wall-clock time `2026-10-06T09:00`, `minutes`, `capacity`, `label`, `status` open/closed) and `bookings` (slot, name, email, phone, notes, status requested/confirmed/cancelled/done, the owner's notes) |
| `functions/api/bookings.js` | `GET /api/bookings`: the open times from now to 60 days out with places left (full ones left out). `POST /api/bookings`: a booking for one slot; the capacity is checked in the statement that writes it; a copy is emailed through patchlamp.com like a form |
| `functions/_admin/bookings.js` | `/admin/bookings`: the bookings, newest first; the owner confirms, cancels (frees the place) or marks done, and keeps notes |
| `functions/_admin/slots.js` | `/admin/slots`: the open times; the owner adds one (a date-time, minutes, places) or closes one |
| `booking.html` | not copied — the calendar + form to paste into a page (`db add` prints it) |

After `db add bookings`:

1. Put the calendar on the page (the block `db add` printed, inside a
   `<section>`). It reads `/api/bookings` as the page loads, so it needs no
   publish when times change.
2. Open the first times, from what the owner said, one row each
   (times are the site's own clock; `TIMEZONE` in `wrangler.toml`):
   `db exec "INSERT INTO booking_slots (starts_at, minutes, capacity) VALUES ('2026-10-06T09:00', 60, 1)"`.
   "Tuesday 9am" is the *next* Tuesday unless they say otherwise; say the
   date back to them. "Every Tuesday 9am for a month" is four rows.
3. Commit, push, `site publish <name>`.
4. Prove it: `curl -s <url>api/bookings` lists the time; tell the owner
   `/admin/bookings` is where bookings land and `/admin/slots` where they
   open or close times.

Everyday texts, no publish needed (the calendar reads the database live):

- open a time: the INSERT above; close one: `db exec "UPDATE booking_slots SET status = 'closed' WHERE id = 7"`
  (find it with `db query "SELECT id, starts_at, status FROM booking_slots ORDER BY starts_at"`)
- who's booked: `db query "SELECT starts_at, name, phone, status FROM bookings WHERE status IN ('requested','confirmed') ORDER BY starts_at"`
- confirm or cancel one: `db exec "UPDATE bookings SET status = 'confirmed' WHERE id = 3"`

Rules the Function keeps: a booking needs a time, a name and an email or
phone; five bookings per visitor per ten minutes; the honeypot; only an
open slot in the future with a place left can be booked (`requested` and
`confirmed` hold a place, `cancelled` and `done` don't). It takes requests;
it doesn't take payment, send reminders or sync a Google Calendar — say so
if asked (PLAYBOOK.md § Data).
