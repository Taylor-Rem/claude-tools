// /admin/customers/<id> — one customer: their details, the jobs done for them
// (newest first, a tap marks one done), a form to add a job, and the edit
// form. It takes the place of the shell's generic entry page for this list
// only; every other list still uses functions/admin/[collection]/[id].js.
import { page, esc, when, money, readBody, redirect, localNow } from "../../_lib/core.js";
import { addJob, markDone, phoneKey, phoneShown, emailKey } from "../../_lib/customers.js";

const STATUSES = ["booked", "done", "cancelled"];
const NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')";

// "$450", "450.00", "1,200" -> cents; null when empty or not a number.
export function cents(v) {
  const s = String(v ?? "").replace(/[$,\s]/g, "");
  if (!s) return null;
  const n = Number(s);
  return isFinite(n) ? Math.round(n * 100) : null;
}

export async function onRequestGet({ env, params, data }) {
  const id = parseInt(params.id, 10);
  const c = id ? await env.DB.prepare("SELECT * FROM customers WHERE id = ?").bind(id).first() : null;
  if (!c) return page(env, "Not found", "<h1>Not found</h1><p><a href=\"/admin/customers\">← Customers</a></p>", { status: 404, session: data.session });
  const jobs = (await env.DB.prepare("SELECT * FROM jobs WHERE customer_id = ? ORDER BY date DESC, id DESC LIMIT 200").bind(id).all()).results || [];
  const row = (label, html) => (html ? `<dt>${esc(label)}</dt><dd>${html}</dd>` : "");
  const tel = c.phone ? `<a href="tel:${esc(String(c.phone).replace(/[^\d+]/g, ""))}">${esc(c.phone)}</a>` : "";
  const mail = c.email ? `<a href="mailto:${esc(c.email)}">${esc(c.email)}</a>` : "";
  const total = jobs.filter((j) => j.status === "done").reduce((a, j) => a + (Number(j.amount_cents) || 0), 0);
  const jobRows = jobs.map((j) => `<tr>
      <td data-label="Date">${esc(j.date || "")}</td>
      <td data-label="Job"><a href="/admin/jobs/${j.id}">${esc(j.what)}</a></td>
      <td data-label="Amount" class="num">${j.amount_cents === null ? "" : esc(money(j.amount_cents))}</td>
      <td data-label="Status"><span class="status">${esc(j.status)}</span></td>
      <td class="quick-cell">${j.status !== "done" ? `<form class="quick" method="post"><input type="hidden" name="action" value="done"><input type="hidden" name="job" value="${j.id}"><button type="submit">done</button></form>` : ""}</td>
    </tr>`).join("");
  const field = (name, label, type = "text") => `<label>${esc(label)} <input name="${name}" type="${type}" value="${esc(c[name] ?? "")}"></label>`;
  const body = `<p><a href="/admin/customers">← Customers</a></p>
    <h1>${esc(c.name)}</h1>
    <dl>
      ${row("Phone", tel)}${row("Email", mail)}${row("Address", esc(c.address || ""))}${row("Tags", esc(c.tags || ""))}
      ${row("Last seen", c.last_seen ? esc(c.last_seen) : "")}
      ${row("Contact", c.contact === "stop" ? "asked not to be contacted" : "")}
      ${row("Notes", esc(c.notes || "").replace(/\n/g, "<br>"))}
      ${row("Came from", esc(c.source || ""))}${row("Added", esc(when(c.created_at, env)))}
    </dl>
    <h2>Jobs</h2>
    ${jobs.length ? `<p class="totals">${jobs.length} job${jobs.length === 1 ? "" : "s"}${total ? ` · ${esc(money(total))} done` : ""}</p>
    <div class="table-wrap"><table class="list"><thead><tr><th scope="col">Date</th><th scope="col">Job</th><th scope="col" class="num">Amount</th><th scope="col">Status</th><th scope="col"><span class="note">Mark</span></th></tr></thead>
    <tbody>${jobRows}</tbody></table></div>` : "<p>No jobs yet.</p>"}
    <h2>Add a job</h2>
    <form class="edit" method="post"><input type="hidden" name="action" value="job">
      <label>Job <input name="what" required placeholder="Weekly service"></label>
      <label>Date <input name="date" type="date" value="${esc(localNow(env).slice(0, 10))}"></label>
      <label>Amount ($) <input name="amount" inputmode="decimal"></label>
      <label>Status <select name="status">${STATUSES.map((s) => `<option>${s}</option>`).join("")}</select></label>
      <button type="submit">Add</button>
    </form>
    <h2>Update</h2>
    <form class="edit" method="post"><input type="hidden" name="action" value="edit">
      ${field("name", "Name")}${field("phone", "Phone", "tel")}${field("email", "Email", "email")}${field("address", "Address")}${field("tags", "Tags")}
      <label>Notes <textarea name="notes">${esc(c.notes || "")}</textarea></label>
      <label>Contact <select name="contact"><option value="ok"${c.contact !== "stop" ? " selected" : ""}>ok</option><option value="stop"${c.contact === "stop" ? " selected" : ""}>stop (asked not to be contacted)</option></select></label>
      <button type="submit">Save</button>
    </form>`;
  return page(env, c.name, body, { session: data.session });
}

export async function onRequestPost({ request, env, params, data }) {
  const id = parseInt(params.id, 10);
  const c = id ? await env.DB.prepare("SELECT * FROM customers WHERE id = ?").bind(id).first() : null;
  if (!c) return page(env, "Not found", "<h1>Not found</h1>", { status: 404, session: data.session });
  const b = await readBody(request);
  const val = (k) => String(b[k] ?? "").trim().slice(0, 5000);
  if (b.action === "job") {
    if (!val("what")) return redirect(`/admin/customers/${id}`);
    await addJob(env, { customer_id: id, what: val("what"), date: val("date"), amount_cents: cents(b.amount),
      status: val("status"), source: "admin" });
  } else if (b.action === "done") {
    const job = parseInt(b.job, 10);
    const j = job ? await env.DB.prepare("SELECT * FROM jobs WHERE id = ? AND customer_id = ?").bind(job, id).first() : null;
    if (j) await markDone(env, j.id);
  } else if (b.action === "edit") {
    const name = val("name") || c.name;
    const key = phoneKey(val("phone"));
    await env.DB.prepare(
      `UPDATE customers SET name = ?, phone = ?, phone_key = ?, email = ?, address = ?, tags = ?, notes = ?, contact = ?, updated_at = ${NOW} WHERE id = ?`
    ).bind(name, key ? phoneShown(val("phone")) : (val("phone") || null), key || null, emailKey(val("email")) || null,
      val("address") || null, val("tags") || null, val("notes") || null, b.contact === "stop" ? "stop" : "ok", id).run();
    if (name !== c.name) await env.DB.prepare("UPDATE jobs SET customer_name = ? WHERE customer_id = ?").bind(name, id).run();
  }
  return redirect(`/admin/customers/${id}`);
}
