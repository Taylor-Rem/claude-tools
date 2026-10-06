// The bookings collection's shared side (B119): the manage link a customer
// gets, the signed mail to patchlamp.com, moving a booking, the customer book,
// and the calendar feed. api/bookings.js, book/manage.js, api/bookings.ics.js
// and admin/bookings/[id].js all use it.
//
// What it needs on the site (Pages secrets, set by `db bookings setup`):
//   env.BOOKING_KEY        signs the manage links and the posts to patchlamp.com.
//                          patchlamp.com derives the same key (App\Support\
//                          BookingSignature), so a signed post is known to come
//                          from here and may mail the customer. Without it the
//                          site still takes bookings and the owner is still
//                          mailed; the customer is not, and there's no manage link.
//   env.BOOKINGS_FEED_KEY  the calendar feed's key (/api/bookings.ics?key=…),
//                          also kept in the site registry (sites.json).
import { esc, localTime, localNow, now, page } from "./core.js";
import { recordCustomer, addJob } from "./customers.js";

export const TAKEN = "('requested', 'confirmed')";      // the statuses that hold a place
const enc = new TextEncoder();

function hex(buf) {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export async function hmacHex(key, msg) {
  const k = await crypto.subtle.importKey("raw", enc.encode(key), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return hex(await crypto.subtle.sign("HMAC", k, enc.encode(msg)));
}

export function sameString(a, b) {
  a = String(a || ""); b = String(b || "");
  if (!a || a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

// ---------------------------------------------------------------- the manage link

// A wall-clock time ("2026-10-06T09:00") as unix seconds, read as UTC. Close
// enough for an expiry measured in days; never used to show a time.
const roughUnix = (local) => Math.floor(Date.parse(String(local).slice(0, 16) + ":00Z") / 1000) || now();

// How long a link works: two days past the booking (so "I was late, can I
// move it" still opens), and never less than a week from when it's sent or
// more than 120 days.
export function manageExpiry(startsAt, from = now()) {
  return Math.min(Math.max(roughUnix(startsAt) + 2 * 86400, from + 7 * 86400), from + 120 * 86400);
}

// "<id>.<expires>.<sig>": the booking and until when, signed. It names one
// booking and nothing else; a move keeps the same booking id, so an older
// link still opens it.
export async function manageToken(env, id, startsAt) {
  if (!env.BOOKING_KEY) return null;
  const body = `${parseInt(id, 10)}.${manageExpiry(startsAt)}`;
  return `${body}.${(await hmacHex(env.BOOKING_KEY, "manage|" + body)).slice(0, 32)}`;
}

// The booking id a token names, or null when it's wrong or past its time.
export async function readManageToken(env, token) {
  const m = /^(\d{1,12})\.(\d{9,11})\.([0-9a-f]{32})$/.exec(String(token || ""));
  if (!m || !env.BOOKING_KEY) return null;
  const sig = (await hmacHex(env.BOOKING_KEY, `manage|${m[1]}.${m[2]}`)).slice(0, 32);
  if (!sameString(sig, m[3]) || parseInt(m[2], 10) < now()) return null;
  return parseInt(m[1], 10);
}

export async function manageUrl(env, origin, id, startsAt) {
  const t = await manageToken(env, id, startsAt);
  return t ? `${origin.replace(/\/$/, "")}/book/manage?t=${t}` : "";
}

// ---------------------------------------------------------------- the mail

// Tell patchlamp.com what happened to a booking, so the owner and the customer
// are mailed (FormsController::booking). kind: requested | confirmed | moved |
// cancelled | reminder; by: "owner" or "customer". `booking` is the row (name, email,
// phone, notes, starts_at, id); `was` the time before a move. Returns the
// fetch's promise, true when patchlamp.com took it (hand it to waitUntil, or
// await it to tell the person whether the mail went), or null when nothing
// was sent (no slug, mail off, or a change on a site without the key); never throws.
export async function tellPatchlamp(env, request, kind, booking, { by = "owner", was = null } = {}) {
  if (!env.PATCHLAMP_SLUG || env.FORWARD_EMAIL === "off") return null;
  const base = (env.PATCHLAMP_URL || "https://patchlamp.com").replace(/\/$/, "");
  const origin = env.MAIL_ORIGIN || new URL(request.url).origin;
  const fields = {
    time: localTime(String(booking.starts_at).slice(0, 16)), name: booking.name || "", email: booking.email || "",
    phone: booking.phone || "", notes: kind === "requested" ? booking.notes || "" : "",
  };
  const headers = { origin, referer: `${origin}/`, accept: "application/json", "content-type": "application/x-www-form-urlencoded" };
  if (env.BOOKING_KEY) {
    Object.assign(fields, { kind, by, ref: String(booking.id), ts: String(now()), was: was ? localTime(String(was).slice(0, 16)) : "",
      manage: kind === "cancelled" ? "" : await manageUrl(env, origin, booking.id, booking.starts_at) });
  } else if (kind !== "requested") {
    return null;                                            // unsigned, only the owner's copy of a new booking goes
  }
  for (const k of Object.keys(fields)) if (fields[k] === "") delete fields[k];
  const body = new URLSearchParams(fields).toString();
  if (env.BOOKING_KEY) headers["x-booking-signature"] = await hmacHex(env.BOOKING_KEY, body);
  return fetch(`${base}/f/${encodeURIComponent(env.PATCHLAMP_SLUG)}/booking`, { method: "POST", body, headers })
    .then((r) => { if (!r.ok) console.error(`booking mail: patchlamp.com answered ${r.status}`); return r.ok; })
    .catch((e) => { console.error(`booking mail: ${e}`); return false; });
}

// ---------------------------------------------------------------- moving one

// The open times a booking could move to: open, in the future, a place left
// (its own slot left out), from now to 60 days out.
export async function openSlots(env, exceptSlot = 0) {
  return (await env.DB.prepare(
    `SELECT * FROM (
       SELECT s.id, s.starts_at, s.minutes, s.label,
              s.capacity - (SELECT COUNT(*) FROM bookings b WHERE b.slot_id = s.id AND b.status IN ${TAKEN}) AS places
         FROM booking_slots s
        WHERE s.status = 'open' AND s.starts_at > ? AND s.starts_at <= ? AND s.id != ?
     ) WHERE places > 0 ORDER BY starts_at LIMIT 200`
  ).bind(localNow(env), localNow(env, 60), exceptSlot || 0).all()).results || [];
}

// Move a booking to another slot, the capacity checked in the statement that
// writes it (as a new booking is). -> { ok, was, booking } or { ok: false }.
export async function moveBooking(env, id, slotId) {
  const before = await env.DB.prepare("SELECT * FROM bookings WHERE id = ?").bind(id).first();
  if (!before || !["requested", "confirmed"].includes(before.status) || before.slot_id === slotId) return { ok: false };
  const res = await env.DB.prepare(
    `UPDATE bookings SET slot_id = ?, starts_at = (SELECT starts_at FROM booking_slots WHERE id = ?),
            updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
      WHERE id = ? AND status IN ${TAKEN}
        AND EXISTS (SELECT 1 FROM booking_slots s WHERE s.id = ? AND s.status = 'open' AND s.starts_at > ?
                      AND (SELECT COUNT(*) FROM bookings b WHERE b.slot_id = s.id AND b.status IN ${TAKEN}) < s.capacity)`
  ).bind(slotId, slotId, id, slotId, localNow(env)).run();
  if (!res.meta.changes) return { ok: false };
  const booking = await env.DB.prepare("SELECT * FROM bookings WHERE id = ?").bind(id).first();
  return { ok: true, was: before.starts_at, booking };
}

// Cancel one that still holds a place. -> { ok, booking } (ok false when it had
// already been cancelled or done, by someone else in the meantime).
export async function cancelBooking(env, id) {
  const res = await env.DB.prepare(
    `UPDATE bookings SET status = 'cancelled', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ? AND status IN ${TAKEN}`
  ).bind(id).run();
  const booking = await env.DB.prepare("SELECT * FROM bookings WHERE id = ?").bind(id).first();
  return { ok: !!res.meta.changes, booking };
}

// Confirm one that's only requested. -> { ok, booking }.
export async function confirmBooking(env, id) {
  const res = await env.DB.prepare(
    `UPDATE bookings SET status = 'confirmed', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ? AND status = 'requested'`
  ).bind(id).run();
  const booking = await env.DB.prepare("SELECT * FROM bookings WHERE id = ?").bind(id).first();
  return { ok: !!res.meta.changes, booking };
}

// The open slot that starts at this wall-clock time ("2026-10-14T15:00"; seconds
// ignored), its own booking's slot left out, or null.
export async function openSlotAt(env, startsAt, exceptSlot = 0) {
  const at = String(startsAt || "").replace(" ", "T").slice(0, 16);
  return (await openSlots(env, exceptSlot)).find((s) => String(s.starts_at).slice(0, 16) === at) || null;
}

// ---------------------------------------------------------------- the site endpoint (for Patch, by text)

// POST /api/bookings/<id> is signed like the posts to patchlamp.com, with a
// prefix so one can never stand for the other:
//   X-Booking-Signature: hex(HMAC-SHA256(BOOKING_KEY, "api|" + raw body))
// and the body's `ts` (unix seconds) within SIGNED_WINDOW of now. The contract
// is written down in ~/projects/plans/49-the-customer-side.md § Site endpoint.
export const SIGNED_WINDOW = 600;

export async function verifySigned(env, request, raw) {
  if (!env.BOOKING_KEY) return false;
  const given = String(request.headers.get("x-booking-signature") || "").toLowerCase();
  if (!sameString(given, await hmacHex(env.BOOKING_KEY, "api|" + raw))) return false;
  let ts = 0;
  try { ts = parseInt(JSON.parse(raw).ts, 10) || 0; } catch { return false; }
  return ts > 0 && Math.abs(now() - ts) <= SIGNED_WINDOW;
}

// ---------------------------------------------------------------- the customer book (B122)

const JOB = { requested: "booked", confirmed: "booked", cancelled: "cancelled", done: "done" };

// The booking into the customer book: the customer found or made (same phone
// or email is the same person), and one job per booking (source "booking",
// ref = the booking's id), its date and status kept up with the booking.
// A booking isn't a visit, so last_seen waits for the job to be marked done
// (addJob with status "done" moves it). Quiet on a site without the book;
// never stops a booking.
export async function recordBooking(env, booking) {
  try {
    const c = await recordCustomer(env, {
      name: booking.name, phone: booking.phone, email: booking.email, source: "booking", seen: false,
    });
    if (!c) return null;
    const slot = booking.slot_id
      ? await env.DB.prepare("SELECT label FROM booking_slots WHERE id = ?").bind(booking.slot_id).first() : null;
    return await addJob(env, {
      customer_id: c.id, date: String(booking.starts_at).slice(0, 10), what: (slot && slot.label) || "Booking",
      status: JOB[booking.status] || "booked", source: "booking", ref: String(booking.id),
    });
  } catch (e) {
    console.error(`customer book: ${e}`);
    return null;
  }
}

// ---------------------------------------------------------------- the calendar feed

// A wall-clock time in the site's zone as a UTC instant ("20261006T150000Z"),
// so every calendar app shows it right without a VTIMEZONE block.
export function utcStamp(local, tz = "America/Denver") {
  const [y, mo, d, h, mi] = String(local).split(/[-T:]/).map(Number);
  const guess = Date.UTC(y, mo - 1, d, h, mi);
  const offset = (t) => {
    const p = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone: tz, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).formatToParts(new Date(t)).map((x) => [x.type, x.value]));
    return Date.UTC(+p.year, p.month - 1, +p.day, +p.hour, +p.minute, +p.second) - t;
  };
  let t = guess - offset(guess);
  t = guess - offset(t);                                     // once more, for a time near a DST change
  return new Date(t).toISOString().replace(/[-:]/g, "").replace(/\.\d+/, "");
}

// RFC 5545 text: backslash, semicolon, comma and newlines escaped.
const icsText = (s) => String(s ?? "").replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");

// Lines longer than 75 octets folded (a space starts each continuation).
function fold(line) {
  const bytes = enc.encode(line);
  if (bytes.length <= 75) return line;
  const out = [];
  let cur = "", n = 0;
  for (const ch of line) {
    const w = enc.encode(ch).length;
    if (n + w > (out.length ? 74 : 75)) { out.push(cur); cur = ""; n = 0; }
    cur += ch; n += w;
  }
  out.push(cur);
  return out.join("\r\n ");
}

// The confirmed bookings from 30 days back to a year ahead, one VEVENT each.
// A cancelled one drops out of the feed, and the calendar removes it on its
// next refresh.
export async function calendar(env, origin) {
  const rows = (await env.DB.prepare(
    `SELECT b.id, b.starts_at, b.name, b.email, b.phone, b.notes, b.updated_at, b.created_at,
            COALESCE(s.minutes, 60) AS minutes, s.label
       FROM bookings b LEFT JOIN booking_slots s ON s.id = b.slot_id
      WHERE b.status = 'confirmed' AND b.starts_at >= ? AND b.starts_at <= ?
      ORDER BY b.starts_at LIMIT 2000`
  ).bind(localNow(env, -30), localNow(env, 366)).all()).results || [];
  const tz = env.TIMEZONE || "America/Denver";
  const host = new URL(origin).host;
  const site = env.SITE_NAME || host;
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+/, "");
  const lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Patchlamp//Bookings//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
    `X-WR-CALNAME:${icsText(site + " bookings")}`, "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"];
  for (const r of rows) {
    // a row written by hand may carry seconds ("2026-10-06T09:00:00"); one that
    // still can't be read is left out of the feed, never a broken feed
    const local = String(r.starts_at).slice(0, 16);
    const startMs = Date.parse(local + ":00Z");
    if (!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(local) || isNaN(startMs)) continue;
    const start = utcStamp(local, tz);
    const endLocal = new Date(startMs + (r.minutes || 60) * 60000).toISOString().slice(0, 16);
    const about = [r.phone && `Phone: ${r.phone}`, r.email && `Email: ${r.email}`, r.notes && `Notes: ${r.notes}`,
      `${origin.replace(/\/$/, "")}/admin/bookings/${r.id}`].filter(Boolean).join("\n");
    lines.push("BEGIN:VEVENT", `UID:booking-${r.id}@${host}`, `DTSTAMP:${stamp}`, `DTSTART:${start}`, `DTEND:${utcStamp(endLocal, tz)}`,
      `SUMMARY:${icsText(r.name + (r.label ? ` · ${r.label}` : ""))}`, `DESCRIPTION:${icsText(about)}`, "STATUS:CONFIRMED", "END:VEVENT");
  }
  lines.push("END:VCALENDAR");
  return lines.map(fold).join("\r\n") + "\r\n";
}

// ---------------------------------------------------------------- the customer's page

// The manage page's frame: the site's stylesheet, no index, no cache. A wrong
// or old link is a plain page saying so, never an error screen.
export async function customerPage(env, title, body) {
  const res = page(env, title, `<div class="booking-manage">${body}</div>`);
  // the shell's frame describes /admin; this page is the customer's
  const html = (await res.text()).replace(/<meta name="description"[^>]*>/, '<meta name="description" content="Your booking: move it or cancel it.">');
  return new Response(html, { status: res.status, headers: res.headers });
}

export function sorry(env, why) {
  const site = esc(env.SITE_NAME || "this business");
  return customerPage(env, "Your booking", `<h1>Your booking</h1>
    <p>${esc(why)}</p>
    <p>To change a booking, reply to your booking email and ${site} will sort it out, or <a href="/#book">book a time</a> again.</p>`);
}
