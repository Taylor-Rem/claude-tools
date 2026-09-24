# catalog — products, variants, pickup hours

**Status: scaffold — finish with B30's demo-store.** Only the table exists
(`migrations/0001_catalog.sql`); there is no Function, no admin view and no
form yet, so `db add catalog` refuses and nothing may be promised from it.
Until it is finished, a client asking for this gets the PLAYBOOK § Data
answer for things the layer can't do yet.

To finish: `functions/api/catalog.js` (the public menu/catalog as JSON), `functions/api/checkout.js` creating a Stripe Checkout session with the **client's own** Stripe key held as a Pages secret (`wrangler pages secret put STRIPE_SECRET_KEY`, set by `site` from a value Patch never prints), `functions/api/stripe-webhook.js` writing `orders`, pickup only — no shipping, no inventory in v1 (plan 12 § B29 item 5). Stripe test mode first (TAYLOR-TODO when B30 reaches it).
