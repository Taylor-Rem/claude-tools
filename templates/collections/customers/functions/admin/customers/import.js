// /admin/customers/import — a CSV of customers into the book: upload the
// file (or paste it), and each row is matched by phone or email to someone
// already there (filling in what their record was missing) or added. The
// header words are the ones in ../../_lib/customers.js HEADERS; a column none
// of them names goes into the notes. Same rules as `db customers import`.
import { page, esc } from "../../_lib/core.js";
import { recordCustomer, parseCsv, mapHeader, customerFromRow } from "../../_lib/customers.js";

const MAX_ROWS = 5000;

const form = `<form class="edit" method="post" enctype="multipart/form-data">
    <label>The file (.csv) <input type="file" name="file" accept=".csv,text/csv"></label>
    <label>Or paste it <textarea name="text" rows="8" placeholder="Name,Phone,Email,Address,Last visit"></textarea></label>
    <button type="submit">Import</button>
  </form>`;

export async function onRequestGet({ env, data }) {
  return page(env, "Import customers", `<p><a href="/admin/customers">← Customers</a></p>
    <h1>Import customers</h1>
    <p>A spreadsheet saved as CSV, with a header row: name (or first and last), phone, email, address,
    notes, tags, and the last visit if you have it. Someone already in your book (the same phone or
    email) is updated, not added twice. Excel: File → Save As → CSV.</p>${form}`, { session: data.session });
}

export async function onRequestPost({ request, env, data }) {
  const fd = await request.formData();
  const file = fd.get("file");
  let text = file && typeof file === "object" && file.size ? await file.text() : String(fd.get("text") || "");
  const rows = parseCsv(text);
  const back = `<p><a href="/admin/customers/import">Try again</a> · <a href="/admin/customers">Customers</a></p>`;
  if (rows.length < 2) return page(env, "Nothing to import", `<h1>Nothing to import</h1><p>It needs a header row and at least one row under it.</p>${back}`, { status: 422, session: data.session });
  const head = mapHeader(rows[0]);
  if (!("name" in head.map || "first" in head.map || "phone" in head.map || "email" in head.map)) {
    return page(env, "No name column", `<h1>I couldn't find the names</h1><p>The header row needs a Name (or First and Last), Phone or Email column. It has: ${esc(rows[0].join(", "))}.</p>${back}`, { status: 422, session: data.session });
  }
  let added = 0, updated = 0, skipped = 0;
  for (const row of rows.slice(1, MAX_ROWS + 1)) {
    const c = customerFromRow(head, row);
    if (!c) { skipped++; continue; }
    const r = await recordCustomer(env, c);
    if (!r) { skipped++; continue; }
    r.created ? added++ : updated++;
  }
  const more = rows.length - 1 > MAX_ROWS ? ` The file had ${rows.length - 1} rows; the first ${MAX_ROWS} were read.` : "";
  return page(env, "Imported", `<p><a href="/admin/customers">← Customers</a></p>
    <h1>Imported</h1>
    <p>${added} added, ${updated} already in the book and updated${skipped ? `, ${skipped} skipped (no name, phone or email)` : ""}.${esc(more)}</p>
    ${head.extra.length ? `<p class="note">Kept in the notes: ${esc(head.extra.map(([l]) => l).join(", "))}.</p>` : ""}`, { session: data.session });
}
