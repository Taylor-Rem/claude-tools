# records — the generic list

**Status: ready.** The texts it answers: "keep a list of our suppliers",
"somewhere I can note the parts on order" — a list kept by hand that isn't
customers. **Customers and the jobs done for them are the `customers`
collection** (the customer book, B122): found by phone or email, a last
visit, the jobs under each. A site that already keeps customers here moves
them with `db add customers` then `db customers import --from-records`.

One table, `records` (`kind`, `title`, `status`, `notes`, `data` as JSON),
shown and edited on `/admin/records`. There is no public form: the owner
adds and edits entries on `/admin`, and Patch can by text:

    db exec "INSERT INTO records (kind, title, notes) VALUES ('supplier', 'Pool Parts West', 'net 30')"
    db query "SELECT id, title, status FROM records WHERE kind = 'supplier' ORDER BY id DESC"

**A named list** (what the owner will actually ask for): copy
`functions/_admin/records.js` to `functions/_admin/suppliers.js`, set
`title: "Suppliers"`, `singular: "supplier"`, `filter: { kind: "supplier" }`,
and add `import suppliers from "./suppliers.js";` plus `suppliers` to the
object in `functions/_admin/collections.js`. The list shows only that kind,
and entries added there get it. Commit, push, `site publish`.

What it isn't: a login for the owner's *customers*, a calendar, or anything
public. Those are other collections (or not built yet — see PLAYBOOK § Data).
