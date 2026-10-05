# customers — the customer book

**Status: ready.** The texts it answers: "keep my customers", "who is
801-555-0134", "when did we last do the Smiths", "who haven't I seen in 90
days", "here's my customer list" (a spreadsheet), "done with the Smith job",
"Dana doesn't want texts any more".

Two tables: `customers` (name, phone, email, address, notes, tags,
`contact`, `last_seen`, where they came from) and `jobs` (the customer, a
date, what, `amount_cents`, status `booked` / `done` / `cancelled`). Each
customer is in the book once: the same phone (its last ten digits) or the
same email (any case) is the same person, whoever writes it. A name alone
never merges two records, because two John Smiths are two people.

What `db add customers` puts in the repo:

| file | what it is |
|---|---|
| `migrations/NNNN_customers.sql` | the two tables |
| `functions/_admin/customers.js`, `jobs.js` | `/admin/customers` (search by name, phone or email; Download CSV) and `/admin/jobs` (newest first, one tap marks done, the amounts added up) |
| `functions/admin/customers/[id].js` | one customer's page: their details, the jobs under them, add a job, mark one done, edit, "asked not to be contacted" |
| `functions/admin/customers/import.js` | **Import a CSV** on `/admin/customers` (upload or paste), the same matching as below |
| `functions/admin/customers/index.js`, `functions/admin/jobs/[id].js` | the shell's list and entry page with the import link, and a job marked done moving the customer's last seen |
| `functions/_lib/customers.js` | the write side every feeder calls (below) |

A site that kept customers as a named list on `records` (kind = customer)
gets its `/admin/customers` and `/admin/jobs` replaced by these; the old
rows stay in `records` until `db customers import --from-records` moves
them (a job titled "What — Customer Name" is linked to that customer).

After `db add customers`: commit, push, `site publish <name>`, open
`<live url>admin/customers`, and tell the owner that's where the book is.

## By text (run from the workspace; `--json` on each for a machine)

- "who is 801-555-0134" → `db customers find 801-555-0134` (any spelling of
  the number, the last seven digits, an email, or a name; "the Smiths"
  finds Smith).
- "when did we last do the Smiths" → `db customers show Smith`: the record
  and every job, newest first. Several match: it lists them; ask which.
- "who haven't I seen in 90 days" → `db customers lapsed` (`--days 60`).
  Anyone with a job booked from today on is left out; those with no visit
  on record are counted apart (`--unknown` lists them); anyone who asked not
  to be contacted is marked.
- a spreadsheet of customers → `db customers import incoming/<file>
  --dry-run`, say the mapping back ("Mobile is the phone, Last Visit the
  last time you saw them, Pool size goes in the notes"), then without
  `--dry-run`. CSV or Excel; their own headers (Name or First + Last, Phone
  / Mobile / Cell, Email, Address + City + State + Zip, Notes, Tags, Last
  visit / Last service / Date); a column it doesn't know goes into the notes
  as "Header: value". Someone already in the book is filled in, never
  overwritten; the newer visit wins. Running it twice adds nobody.
- "add Dana Ruiz, 801-555-0134" → `db customers add "Dana Ruiz" --phone
  801-555-0134` (`--seen today` when they did a job today).
- "Dana doesn't want texts" → `db customers set Dana --contact stop`. Tags:
  `--add-tag weekly`.
- "did the Smith pool today, $85" → `db jobs add Smith "Weekly service"
  --status done --amount 85`; "done with the Smith job" → `db jobs done
  Smith` (their one booked job) or `db jobs done 14`.
- the handover → `db customers export` (or `db export` for every table).

## For the feeders (bookings B119, quote forms B121, estimates B123, pay)

On the site, a Function that meets a customer calls the book:

```js
import { recordCustomer, addJob, markDone } from "../_lib/customers.js";
const c = await recordCustomer(env, { name, phone, email, address, source: "booking", seen: "2026-10-06" });
if (c) await addJob(env, { customer_id: c.id, date: "2026-10-06", what: "Weekly service", source: "booking", ref: String(id) });
```

- `recordCustomer(env, {name, phone, email, address, notes, tags, source, seen})`
  → `{id, created}`: finds the customer by phone, then email; fills in what
  the record lacked (never overwrites the owner's words); moves `last_seen`
  forward to `seen` (YYYY-MM-DD, default today; `seen: false` leaves it).
- `addJob(env, {customer_id, date, what, amount_cents, status, notes, source, ref})`
  → `{id, created}`. With `source` and `ref` (the feeder's own id) it is
  written once: the same booking again updates its job. `status: "done"`
  moves `last_seen` to the job's date.
- `markDone(env, jobId)` → the job done and `last_seen` moved.
- Each returns `null` and does nothing on a site without the book, so a
  feeder calls them on every site without checking.

From the workspace, the same through `db`: `db customers add … --seen
DATE --source booking --json`, `db jobs add CUSTOMER "what" --source pay
--ref in_123 --status done --amount 450 --json` (`--create` with `--name`
/ `--phone` / `--email` makes the customer when none matches), `db jobs
done JOB_ID --json`. The JSON shapes are at the top of the customer-book
block in `bin/db`.

## What it isn't

A login for the customers, a public page, a mailing list. Nothing in the
book is shown on the site; `/admin` is the owner's alone. Writing to a
customer is decided elsewhere (VISION 2026-10-05: only about something they
started, from the address they gave, `contact = stop` honoured), and a list
for a blast waits on B23. The handover is `db export`.
