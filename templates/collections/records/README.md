# records — the generic list

**Status: ready.** The texts it answers: "I want to see my customers", "keep
a list of the jobs we've got on", "somewhere I can note who's paid".

One table, `records` (`kind`, `title`, `status`, `notes`, `data` as JSON),
shown and edited on `/admin/records`. There is no public form: the owner
adds and edits entries on `/admin`, and Patch can by text:

    db exec "INSERT INTO records (kind, title, notes) VALUES ('customer', 'Dana Ruiz', 'weekly service, Tuesdays')"
    db query "SELECT id, title, status FROM records WHERE kind = 'customer' ORDER BY id DESC"

**A named list** (what the owner will actually ask for): copy
`functions/_admin/records.js` to `functions/_admin/customers.js`, set
`title: "Customers"`, `singular: "customer"`, `filter: { kind: "customer" }`,
and add `import customers from "./customers.js";` plus `customers` to the
object in `functions/_admin/collections.js`. The list shows only that kind,
and entries added there get it. Commit, push, `site publish`.

What it isn't: a login for the owner's *customers*, a calendar, or anything
public. Those are other collections (or not built yet — see PLAYBOOK § Data).
