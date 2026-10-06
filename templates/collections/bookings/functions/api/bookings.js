// /api/bookings — the site's booking calendar.
//
//   GET  /api/bookings        the open times from now to 60 days out, with the
//                             places left in each: {"slots":[{id, starts_at,
//                             minutes, label, places}]}. Full slots are left out.
//   POST /api/bookings        a booking for one slot: slot, name, email and/or
//                             phone, notes, and the `website` honeypot. The
//                             capacity is checked in the same statement that
//                             writes the row, so two people can't take the
//                             last place. Afterwards the page reloads with
//                             ?sent=booking#book (or sent=full, sent=0).
//
// The owner opens times on /admin/slots (or Patch does, by text: a row in
// booking_slots). Each booking goes on to patchlamp.com, signed with
// BOOKING_KEY (functions/_lib/bookings.js): the owner is emailed, and the
// customer gets "requested" with the link to move or cancel it. It also goes
// into the customer book when the site has one (B122).
import { readBody, formFields, sha256, wantsJson, backTo, now, localNow } from "../_lib/core.js";
import { tellPatchlamp, recordBooking } from "../_lib/bookings.js";

const PER_TEN_MINUTES = 5;
const DAYS_AHEAD = 60;
const TAKEN = "('requested', 'confirmed')";      // the statuses that hold a place

export async function onRequestGet({ env }) {
  const rows = (await env.DB.prepare(
    `SELECT * FROM (
       SELECT s.id, s.starts_at, s.minutes, s.label,
              s.capacity - (SELECT COUNT(*) FROM bookings b WHERE b.slot_id = s.id AND b.status IN ${TAKEN}) AS places
         FROM booking_slots s
        WHERE s.status = 'open' AND s.starts_at > ? AND s.starts_at <= ?
     ) WHERE places > 0 ORDER BY starts_at LIMIT 300`
  ).bind(localNow(env), localNow(env, DAYS_AHEAD)).all()).results || [];
  return Response.json({ slots: rows }, { headers: { "cache-control": "no-store" } });
}

export async function onRequestPost({ request, env, waitUntil }) {
  const data = await readBody(request);
  const reply = (status, flag, extra = {}) =>
    wantsJson(request) ? Response.json({ ok: status < 400, ...extra }, { status }) : backTo(request, { sent: flag }, "book");

  if (String(data.website || "").trim()) return reply(200, "booking");      // the honeypot: pretend it worked
  const f = formFields(data, ["website"]);
  const slot = parseInt(f.slot || "", 10);
  if (!slot || !f.name || !(f.email || f.phone)) return reply(422, "0", { error: "a time, a name, and an email or phone" });

  const ip = request.headers.get("cf-connecting-ip") || "";
  const ipHash = ip ? await sha256(ip + (env.SESSION_SECRET || "")) : null;
  if (ipHash) {
    const since = new Date((now() - 600) * 1000).toISOString().slice(0, 19) + "Z";
    const r = await env.DB.prepare("SELECT COUNT(*) AS n FROM bookings WHERE ip_hash = ? AND created_at > ?").bind(ipHash, since).first();
    if (r.n >= PER_TEN_MINUTES) return reply(429, "0", { error: "too many, try again later" });
  }

  const res = await env.DB.prepare(
    `INSERT INTO bookings (slot_id, starts_at, name, email, phone, notes, ip_hash)
     SELECT s.id, s.starts_at, ?, ?, ?, ?, ?
       FROM booking_slots s
      WHERE s.id = ? AND s.status = 'open' AND s.starts_at > ?
        AND (SELECT COUNT(*) FROM bookings b WHERE b.slot_id = s.id AND b.status IN ${TAKEN}) < s.capacity`
  ).bind(f.name, f.email || null, f.phone || null, f.notes || null, ipHash, slot, localNow(env)).run();
  if (!res.meta.changes) return reply(409, "full", { error: "that time is taken or closed" });

  const id = res.meta.last_row_id;
  const row = await env.DB.prepare("SELECT * FROM bookings WHERE id = ?").bind(id).first();
  await recordBooking(env, row);
  const mail = tellPatchlamp(env, request, "requested", row);
  if (mail) waitUntil(mail);
  return reply(200, "booking", { id, starts_at: row.starts_at });
}
