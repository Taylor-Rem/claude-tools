# orders — paid Checkout sessions, for pickup

**Status: scaffold — finish with B30's demo-store, with catalog.** Only the table exists
(`migrations/0001_orders.sql`); there is no Function, no admin view and no
form yet, so `db add orders` refuses and nothing may be promised from it.
Until it is finished, a client asking for this gets the PLAYBOOK § Data
answer for things the layer can't do yet.

To finish: written by catalog's webhook Function; an admin view with statuses (paid, ready, collected, refunded — refunds stay Taylor's).
