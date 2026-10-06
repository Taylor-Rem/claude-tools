# ledger — receipts by photo

**Status: ready.** The texts it answers: a photo of a receipt (with or
without words), "what did I spend in September", "receipts for the truck",
"send me that Home Depot receipt", "that was $38.10 not $83.10", "send me
everything for my accountant".

One table, `ledger`: one row a receipt — `date` (on the receipt), `month`
(computed from the date, for the chooser), `vendor`, `amount_cents` (the
total paid, tax in; a refund is negative), `category` (the owner's word),
`note` (what it was for), `photo` (where the photo is kept), `source`.

**Not bookkeeping.** It is a record of what was spent, from the receipts
the owner sent. The categories are the owner's words, not categories a CPA
would sign; `/admin/ledger` says so in those words (patchlamp `CLAIMS.md`).
Patch never calls anything deductible.

What `db add ledger` puts in the repo:

| file | what it is |
|---|---|
| `migrations/NNNN_ledger.sql` | the table |
| `functions/_admin/ledger.js` | the list on `/admin/ledger`: newest first, month and category choosers, the total of what's shown |
| `functions/admin/ledger/index.js` | the same list with the "not bookkeeping advice" line, the last twelve months' totals, where the photos are, and an add form in dollars |

After `db add ledger`: commit, push, `site publish <name>`, open
`<live url>admin/ledger`, and tell the owner that's where the receipts are.

## Where the photos are

`receipts/<YYYY-MM>/<date>-<vendor>-<id>.<ext>` in the client's workspace,
copied there by `db ledger add --photo incoming/<file>`. Not `incoming/`
(emptied once a photo is used), not the relay's own archive (outside the
client's sandbox), and not the site (it is public, and a receipt is the
owner's business). The row's `photo` column holds that path; `db export`
writes `receipts.zip` beside `ledger.csv` with the same paths inside it, so
`site handover` carries both. The workspace is backed up nightly with the
rest of it; `clients/.gitignore` keeps `receipts/` out of the config repo.

## By text (run from the workspace; `--json` on add, ls, set)

- a receipt photo → read vendor, date and total (PLAYBOOK § Files, "A
  receipt"), then `db ledger add "Bluebird Pool Supply" 83.10 --date
  2026-10-02 --category supplies --note chlorine --photo incoming/<photo>`.
  It prints what it filed and the month so far. The same vendor, date and
  amount again is refused (exit 3) until `--force`; a date after today is
  refused (a misread year, usually).
- "what did I spend in September" → `db ledger ls --month september`
  (`2026-09`, `last`, `this`): the rows, the total, by category.
- "receipts for the truck" → `db ledger ls --search truck` (vendor, note,
  category); `--vendor`, `--category`, `--days 30`.
- a correction → `db ledger set ID --amount 38.10` (`--date`, `--vendor`,
  `--category`, `--note`, `--photo`); a mistake → `db ledger rm ID` (the
  photo goes with it).
- the accountant's file → `db ledger export` (or `db export` for every
  table): `exports/<date>/ledger.csv`, `.json` and `receipts.zip`.

## What it isn't

Bookkeeping, a tax category, a bank feed, a mileage log, or anything that
reads the owner's accounts. Nothing on the site's public pages reads the
table. The weekly report carries one line when there is a ledger: the
month's total so far (relay `weekly.py`).
