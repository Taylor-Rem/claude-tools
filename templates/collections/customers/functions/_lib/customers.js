// The customer book's write side, for any Function on this site that meets a
// customer: a booking (B119), a quote form (B121), an accepted estimate
// (B123). `db customers …` does the same from the workspace (bin/db), with the
// same matching rules, so a record made either way is found the other way.
//
//   import { recordCustomer, addJob } from "../_lib/customers.js";
//   const c = await recordCustomer(env, { name, phone, email, source: "booking", seen: "2026-10-06" });
//   await addJob(env, { customer_id: c.id, date: "2026-10-06", what: "Weekly service", source: "booking", ref: String(bookingId) });
//
// Matching: the same phone (its last ten digits) or the same email (any case)
// is the same customer; a name alone never matches, so two John Smiths stay
// two people. A match fills in what the record was missing (never overwrites
// what the owner wrote) and moves last_seen forward, never back.
// Both functions return quietly when the book isn't on this site (no
// `customers` table), so a feeder can call them on every site.
import { localNow } from "./core.js";

const NOW = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')";

// "(801) 555-0134", "+1 801 555 0134", "8015550134" -> "8015550134"; "" when it isn't a phone.
export function phoneKey(phone) {
  const d = String(phone || "").replace(/\D/g, "");
  if (d.length < 7) return "";
  return d.length > 10 ? d.slice(-10) : d;
}

// How a phone is kept: 801-555-0134 for a US number, as given otherwise.
export function phoneShown(phone) {
  const raw = String(phone || "").trim();
  const d = raw.replace(/\D/g, "");
  const ten = d.length === 11 && d[0] === "1" ? d.slice(1) : d;
  return ten.length === 10 ? `${ten.slice(0, 3)}-${ten.slice(3, 6)}-${ten.slice(6)}` : raw || null;
}

export const emailKey = (email) => String(email || "").trim().toLowerCase();

const today = (env) => localNow(env).slice(0, 10);

async function hasBook(env) {
  try {
    return !!(await env.DB.prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'customers'").first());
  } catch (_) {
    return false;
  }
}

// The customer with this phone or email (phone first), or null.
export async function findCustomer(env, { phone, email } = {}) {
  const key = phoneKey(phone), em = emailKey(email);
  if (key) {
    const r = await env.DB.prepare("SELECT * FROM customers WHERE phone_key = ? ORDER BY id LIMIT 1").bind(key).first();
    if (r) return r;
  }
  if (em) return env.DB.prepare("SELECT * FROM customers WHERE email = ? ORDER BY id LIMIT 1").bind(em).first();
  return null;
}

// Find-or-make the customer, and note that we saw them on `seen`
// (YYYY-MM-DD; default today; `seen: false` leaves last_seen alone, for an
// import with no date). -> { id, created } or null when the site has no book.
export async function recordCustomer(env, { name, phone, email, address, notes, tags, source, seen } = {}) {
  if (!(await hasBook(env))) return null;
  const nm = String(name || "").trim().slice(0, 200);
  const key = phoneKey(phone), em = emailKey(email) || null;
  const shown = key ? phoneShown(phone) : null;
  const day = seen === false ? null : /^\d{4}-\d{2}-\d{2}/.test(String(seen || "")) ? String(seen).slice(0, 10) : today(env);
  const opt = (v) => (v === undefined || v === null || String(v).trim() === "" ? null : String(v).trim().slice(0, 5000));
  const found = await findCustomer(env, { phone, email });
  if (found) {
    await env.DB.prepare(
      `UPDATE customers SET name = CASE WHEN name = '' THEN ? ELSE name END,
              phone = COALESCE(phone, ?), phone_key = COALESCE(phone_key, ?), email = COALESCE(email, ?),
              address = COALESCE(address, ?), notes = COALESCE(notes, ?), tags = COALESCE(tags, ?),
              last_seen = CASE WHEN ? IS NOT NULL AND (last_seen IS NULL OR last_seen < ?) THEN ? ELSE last_seen END,
              updated_at = ${NOW}
        WHERE id = ?`
    ).bind(nm || found.name, shown, key || null, em, opt(address), opt(notes), opt(tags), day, day, day, found.id).run();
    return { id: found.id, created: false };
  }
  if (!nm && !key && !em) return null;
  const r = await env.DB.prepare(
    "INSERT INTO customers (name, phone, phone_key, email, address, notes, tags, source, last_seen) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
  ).bind(nm || em || shown, shown, key || null, em, opt(address), opt(notes), opt(tags), source || null, day).run();
  return { id: r.meta.last_row_id, created: true };
}

// A job for a customer. With `source` and `ref` (the feeder's own id) it is
// written once: the same booking or invoice again updates that job instead of
// adding a second. A job marked done moves the customer's last_seen to its date.
// -> { id, created } or null when the site has no book.
export async function addJob(env, { customer_id, date, what, amount_cents, status, notes, source, ref } = {}) {
  if (!customer_id || !(await hasBook(env))) return null;
  const st = ["booked", "done", "cancelled"].includes(status) ? status : "booked";
  const day = /^\d{4}-\d{2}-\d{2}/.test(String(date || "")) ? String(date).slice(0, 10) : today(env);
  const cents = amount_cents === undefined || amount_cents === null || amount_cents === "" ? null : Math.round(Number(amount_cents));
  let id = null, created = false;
  const same = source && ref
    ? await env.DB.prepare("SELECT id FROM jobs WHERE source = ? AND ref = ? LIMIT 1").bind(source, String(ref)).first() : null;
  if (same) {
    id = same.id;
    await env.DB.prepare(
      `UPDATE jobs SET date = ?, what = COALESCE(?, what), amount_cents = COALESCE(?, amount_cents), status = ?, updated_at = ${NOW} WHERE id = ?`
    ).bind(day, what || null, cents, st, id).run();
  } else {
    const r = await env.DB.prepare(
      `INSERT INTO jobs (customer_id, customer_name, date, what, amount_cents, status, notes, source, ref)
       SELECT id, name, ?, ?, ?, ?, ?, ?, ? FROM customers WHERE id = ?`
    ).bind(day, String(what || "Job").slice(0, 300), cents, st, notes || null, source || null, ref ? String(ref) : null, customer_id).run();
    if (!r.meta.changes) return null;
    id = r.meta.last_row_id;
    created = true;
  }
  if (st === "done") {
    await env.DB.prepare(
      `UPDATE customers SET last_seen = ?, updated_at = ${NOW} WHERE id = ? AND (last_seen IS NULL OR last_seen < ?)`
    ).bind(day, customer_id, day).run();
  }
  return { id, created };
}

// A job marked done (on /admin, or by any feeder): its status, and the
// customer's last_seen moved forward to the job's date (today when it has none).
// -> the job's customer_id, or null when there's no such job.
export async function markDone(env, jobId) {
  const j = await env.DB.prepare("SELECT id, customer_id, date FROM jobs WHERE id = ?").bind(jobId).first();
  if (!j) return null;
  const day = j.date || today(env);
  await env.DB.prepare(`UPDATE jobs SET status = 'done', date = ?, updated_at = ${NOW} WHERE id = ?`).bind(day, j.id).run();
  await env.DB.prepare(
    `UPDATE customers SET last_seen = ?, updated_at = ${NOW} WHERE id = ? AND (last_seen IS NULL OR last_seen < ?)`
  ).bind(day, j.customer_id, day).run();
  return j.customer_id;
}

// ---------------------------------------------------------------- a CSV of customers
// The same header words `db customers import` reads (bin/db CUSTOMER_HEADERS):
// whatever the owner's spreadsheet calls a column, these find it. A column
// none of them names goes into the notes as "Header: value", so nothing is lost.
export const HEADERS = {
  name: ["name", "full name", "customer", "customer name", "client", "client name", "contact", "contact name"],
  first: ["first", "first name", "firstname", "given name"],
  last: ["last", "last name", "lastname", "surname", "family name"],
  phone: ["phone", "phone number", "mobile", "mobile phone", "cell", "cell phone", "tel", "telephone", "number"],
  email: ["email", "e-mail", "email address", "e-mail address", "mail"],
  address: ["address", "street", "street address", "service address", "address 1", "address line 1"],
  city: ["city", "town"],
  state: ["state", "province", "region"],
  zip: ["zip", "zip code", "zipcode", "postal code", "postcode"],
  notes: ["notes", "note", "comments", "comment", "details"],
  tags: ["tags", "tag", "labels", "label", "group", "groups", "type"],
  last_seen: ["last seen", "last visit", "last service", "last job", "last appointment", "last contact", "last done", "last serviced", "date"],
};

const norm = (h) => String(h || "").toLowerCase().replace(/[_\-.]+/g, " ").replace(/\s+/g, " ").trim();

// header row -> { field: index }, plus `extra`: [[label, index]] the notes take.
export function mapHeader(header) {
  const map = {}, extra = [];
  header.forEach((h, i) => {
    const n = norm(h);
    const field = Object.keys(HEADERS).find((f) => HEADERS[f].includes(n));
    if (field && !(field in map)) map[field] = i;
    else if (String(h || "").trim()) extra.push([String(h).trim(), i]);
  });
  return { map, extra };
}

// "3/14/2026", "2026-03-14", "03/14/26", "Mar 14, 2026" -> "2026-03-14"; "" when it isn't a date.
export function isoDate(v) {
  const s = String(v || "").trim();
  let m;
  if ((m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/))) return `${m[1]}-${m[2].padStart(2, "0")}-${m[3].padStart(2, "0")}`;
  if ((m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{2}|\d{4})$/))) {
    const y = m[3].length === 2 ? "20" + m[3] : m[3];
    return `${y}-${m[1].padStart(2, "0")}-${m[2].padStart(2, "0")}`;
  }
  const t = Date.parse(s);
  return s && /[a-z]/i.test(s) && !isNaN(t) ? new Date(t).toISOString().slice(0, 10) : "";
}

// One CSV row -> the fields recordCustomer takes, or null with no name, phone or email.
export function customerFromRow({ map, extra }, row) {
  const at = (f) => (f in map ? String(row[map[f]] ?? "").trim() : "");
  const name = at("name") || [at("first"), at("last")].filter(Boolean).join(" ");
  const place = [at("address"), at("city"), [at("state"), at("zip")].filter(Boolean).join(" ")].filter(Boolean).join(", ");
  const seenRaw = at("last_seen");
  const seen = isoDate(seenRaw);
  const more = extra.map(([label, i]) => [label, String(row[i] ?? "").trim()]).filter(([, v]) => v).map(([l, v]) => `${l}: ${v}`);
  if (seenRaw && !seen) more.push(`Last seen: ${seenRaw}`);
  const notes = [at("notes"), ...more].filter(Boolean).join("\n");
  if (!name && !phoneKey(at("phone")) && !at("email")) return null;
  return { name, phone: at("phone"), email: at("email"), address: place, notes, tags: at("tags"), seen: seen || false, source: "import" };
}

// RFC 4180 CSV -> rows of strings (quotes, doubled quotes, newlines in quotes).
export function parseCsv(text) {
  const rows = [];
  let row = [], cell = "", q = false;
  const s = String(text || "").replace(/^﻿/, "");
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (q) {
      if (ch === '"' && s[i + 1] === '"') { cell += '"'; i++; }
      else if (ch === '"') q = false;
      else cell += ch;
    } else if (ch === '"') q = true;
    else if (ch === ",") { row.push(cell); cell = ""; }
    else if (ch === "\n" || ch === "\r") {
      if (ch === "\r" && s[i + 1] === "\n") i++;
      row.push(cell); cell = "";
      if (row.some((c) => c.trim())) rows.push(row);
      row = [];
    } else cell += ch;
  }
  row.push(cell);
  if (row.some((c) => c.trim())) rows.push(row);
  return rows;
}
