# estimates — the quote a customer accepts online, then the invoice

**Status: ready.** The texts it answers: "estimate for Smith, 3 windows 2
doors, 450", "send the Lees a quote", "did Smith accept?". The tool is
`estimate` (claude-tools/bin/estimate); PLAYBOOK.md § Payments, Estimates
is the conversation.

What `db add estimates` puts in the repo:

| file | what it is |
|---|---|
| `migrations/NNNN_estimates.sql` | the `estimates` table: number (E-0001), the unguessable token, customer, the lines as JSON, subtotal/tax/total/deposit in cents, good-until day, terms, status (draft, sent, accepted, declined, void), who accepted it, when and from which IP, the invoice, job and booking it turned into, when it was followed through |
| `functions/estimate/[token].js` | `/estimate/<token>`: the estimate, and while it is `sent` and in date, a box for the customer's name and an Accept button. The acceptance is written once (the status changes in the same statement); the owner is emailed through patchlamp.com (form `estimate-accepted`, no customer address in it) |
| `functions/_admin/estimates.js` | how `/admin/estimates` lists them: number, customer, total, status, good until, accepted by; the owner marks one declined or void (sent and accepted are written by `estimate` and the customer, never by hand, so an acceptance can't be overwritten) and keeps notes |

After `db add estimates`: commit, push, `site publish <name>`. Then
`estimate new …` (a draft and its PDF), `estimate send N` on the owner's
word, `estimate sync` once one is accepted (the invoice or the deposit
link on their own Stripe through `pay`, the job in the customer book
when it has one; `estimate sync N --when …` books the agreed time when
the site has bookings). A deposit leaves the balance to the owner's own
invoice, and the deposit's Payment Link can be paid more than once, so it
goes to that customer only.

What the page doesn't do: take a payment (the invoice or deposit link
comes after, from the owner's Stripe), take a drawn signature (a typed
name is the acceptance), or email the customer (the owner sends the link
until Patchlamp has a customer mail path). Draft, void and unknown tokens
all get the same "not found" page.
