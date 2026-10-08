# bookings — times the owner opens, and the bookings people make for them

**Status: ready.** The texts it answers: "add a booking calendar", "let
people book a time", "add Tuesday 9am as a booking slot", "close Friday",
"who's booked this week?".

What `db add bookings` puts in the repo:

| file | what it is |
|---|---|
| `migrations/NNNN_bookings.sql` | `booking_slots` (the times: `starts_at` as a wall-clock time `2026-10-06T09:00`, `minutes`, `capacity`, `label`, `status` open/closed) and `bookings` (slot, name, email, phone, notes, status requested/confirmed/cancelled/done, the owner's notes) |
| `functions/api/bookings.js` | `GET /api/bookings`: the open times from now to 60 days out with places left (full ones left out). `POST /api/bookings`: a booking for one slot; the capacity is checked in the statement that writes it; patchlamp.com emails the owner, and the customer (when they left an email) gets "requested" with their manage link; the customer book gets the customer and a job |
| `functions/_admin/bookings.js` | `/admin/bookings`: the bookings, newest first; the owner confirms, cancels (frees the place) or marks done, and keeps notes |
| `functions/admin/bookings/[id].js` | one booking on `/admin`: confirming or cancelling emails the customer, "Move to another time" moves it and emails them the new time, and the customer book follows (done moves their last seen) |
| `functions/api/bookings/[id].js` | `POST /api/bookings/<id>`, signed with the site's `BOOKING_KEY`: what `db bookings confirm|move|cancel|remind` call, so a change by text runs the same capacity check and sends the same customer email as `/admin` (the contract: `~/projects/plans/49-the-customer-side.md` § Site endpoint) |
| `functions/book/manage.js` | `/book/manage?t=…`, the customer's link from every booking email: their booking, the other open times, Move and Cancel. The owner is emailed what they did. A wrong or old link is a plain page saying so |
| `functions/api/bookings.ics.js` | `/api/bookings.ics?key=…`, the owner's calendar feed: every confirmed booking, for Google Calendar, Apple Calendar or Outlook to subscribe to |
| `functions/_lib/bookings.js` | what those share: the signed manage link, the signed post to patchlamp.com, moving a booking, the customer book, the feed |
| `functions/_lib/customers.js` | the customer book's write side, shipped here too so a site without the book still builds (kept if the book is there) |
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
3. `db bookings setup`: the two keys the site needs as Pages secrets (the
   one that lets patchlamp.com mail the customer, and the calendar feed's).
4. Commit, push, `site publish <name>`.
5. Prove it: `curl -s <url>api/bookings` lists the time; tell the owner
   `/admin/bookings` is where bookings land and `/admin/slots` where they
   open or close times.
6. Their calendar: `db bookings feed` prints the subscribe address and the
   steps for Google Calendar, iPhone and Outlook. Send it to the owner
   only; anyone with the address can read the bookings.

A site made before 2026-10-05 (B119) has the old bookings Functions: `db
bookings upgrade` brings them up (the /admin views and the customer book's
own file are left alone, so is a file someone changed by hand unless
`--force`, and the old thanks line is reworded), then
commit, push, `db bookings setup`, `site publish <name>`. `db bookings
status` (or `db doctor`) says what's behind.

Everyday texts, no publish needed (the calendar reads the database live):

- open a time: the INSERT above; close one: `db exec "UPDATE booking_slots SET status = 'closed' WHERE id = 7"`
  (find it with `db query "SELECT id, starts_at, status FROM booking_slots ORDER BY starts_at"`)
- who's booked: `db query "SELECT starts_at, name, phone, status FROM bookings WHERE status IN ('requested','confirmed') ORDER BY starts_at"`
- confirm, cancel or move one: `db bookings confirm 12`, `db bookings
  cancel 12`, `db bookings move 12 "2026-10-14T15:00"` (find the id with
  the query above, adding `id`). The site does the change itself, the way
  `/admin/bookings/<id>` does: a move only to an open time with a place
  left, and the customer emailed. It prints whether the email went; if it
  says the customer is not emailed (no address on the booking, or the mail
  failed), tell the owner so they can call or text them. A move to a time
  that isn't open is refused with the open times listed: open the time
  first (the INSERT above) if the owner means it. The owner can do the
  same on `/admin/bookings/<id>`. A `db exec "UPDATE bookings …"` changes
  the row and mails nobody, so use it only when the owner says not to
  tell the customer.
- a reminder to one customer: `db bookings remind 12` (a confirmed
  booking still ahead; not to someone marked "asked not to be contacted"
  in the customer book). The relay's morning run (6am, `relay/bookings.py`,
  ROADMAP B120) sends one to every confirmed booking for the next day
  through this same verb and texts the owner the count.
- the day: `db bookings ls tuesday` (`tomorrow`, `10/14`, `--name Smith`
  to find an id, `--json`); times in bulk: `db bookings open --on tue
  --from 9 --to 12 --until november` (an open time is left, a closed one
  reopened).
- their calendar address again: `db bookings feed`; a leaked one: `db
  bookings feed --new`, then `site publish <name>` (the old one stops).

What the customer gets, by email, only at the address they typed into the
booking (VISION 2026-10-05: about something they started): "requested"
the moment they book, then "confirmed", "moved" or "cancelled" as the
owner changes it, each with the link to move or cancel it themselves. The
mails come from patchlamp.com in the business's name and a reply reaches
the owner. They say only the business, the time and the link, never what
the person typed, because the form is public and anyone can type someone
else's address; three "requested" copies an hour to one address is the
most it sends. These are mails about a booking the customer made, so a
customer marked "asked not to be contacted" in the book still gets them.
Anything sent to a customer that they didn't just ask for (a reminder or
a review ask) checks that mark first.

Rules the Function keeps: a booking needs a time, a name and an email or
phone; five bookings per visitor per ten minutes; the honeypot; only an
open slot in the future with a place left can be booked or moved to
(`requested` and `confirmed` hold a place, `cancelled` and `done` don't).
It doesn't take payment or send reminders on its own: `db bookings
remind` sends one, and the relay's morning run sends the next day's
(B120), and the calendar feed is one way: the owner's own
appointments don't close times on the site — say so if asked (PLAYBOOK.md
§ Data).
