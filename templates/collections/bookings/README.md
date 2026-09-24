# bookings — slots and booking requests

**Status: scaffold — finish with B30's demo-service ("add Tuesday 9am as a booking slot").** Only the table exists
(`migrations/0001_bookings.sql`); there is no Function, no admin view and no
form yet, so `db add bookings` refuses and nothing may be promised from it.
Until it is finished, a client asking for this gets the PLAYBOOK § Data
answer for things the layer can't do yet.

To finish: `functions/api/bookings.js` (GET open slots, POST a request against one, capacity checked in one statement), `functions/_admin/bookings.js` and a slots view, a calendar partial for the site, and a CLAIMS row per sentence.
