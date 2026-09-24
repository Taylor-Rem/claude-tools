# subscribers — a local copy of the newsletter list

**Status: scaffold — finish with whoever first needs the list inside the site.** Only the table exists
(`migrations/0001_subscribers.sql`); there is no Function, no admin view and no
form yet, so `db add subscribers` refuses and nothing may be promised from it.
Until it is finished, a client asking for this gets the PLAYBOOK § Data
answer for things the layer can't do yet.

The list itself lives on patchlamp.com (`newsletter subscribers`); a copy here is only for a site that must query it. Nothing needs it today.
