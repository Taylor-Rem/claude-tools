// POST /api/bookings/<id> — a booking changed by text (B119, for Patch and
// B120's reminders): `db bookings confirm|move|cancel|remind` posts here, and
// the change runs exactly as the owner's /admin page runs it: the capacity
// checked in the statement that writes it, the customer book kept up, and the
// customer mailed through patchlamp.com the same way.
//
// Signed with the site's BOOKING_KEY (functions/_lib/bookings.js verifySigned:
// "api|" + the raw JSON body, `ts` within ten minutes), so only someone holding
// the toolbelt's relay secret can change a booking this way. The contract,
// with every answer, is in ~/projects/plans/49-the-customer-side.md
// § Site endpoint (B119, for B120).
//
//   {"action": "confirm", "ts": …}                          requested -> confirmed, customer mailed
//   {"action": "move", "starts_at": "2026-10-14T15:00", "ts": …}  (or "slot": <id>) to an open time
//   {"action": "cancel", "ts": …}                           the place freed, customer mailed
//   {"action": "remind", "ts": …}                           a confirmed, future one: the reminder mail
//                                                           (not to someone marked "asked not to be contacted")
//
// 200 {ok: true, booking, customer_mailed, why?}; 401 a wrong or old
// signature; 404 no such booking; 409 it can't happen to this booking now
// (with the booking, and the open times for a move); 422 an unknown action;
// 503 the site has no BOOKING_KEY yet (db bookings setup).
import { localNow } from "../../_lib/core.js";
import { findCustomer } from "../../_lib/customers.js";
import {
  verifySigned, confirmBooking, cancelBooking, moveBooking, openSlotAt, openSlots, recordBooking, tellPatchlamp, TAKEN,
} from "../../_lib/bookings.js";

const ACTIONS = ["confirm", "move", "cancel", "remind"];
const json = (status, body) => Response.json(body, { status, headers: { "cache-control": "no-store" } });
const shown = (b, was) => b && ({ id: b.id, status: b.status, starts_at: String(b.starts_at).slice(0, 16), name: b.name,
  has_email: !!b.email, ...(was ? { was: String(was).slice(0, 16) } : {}) });

// The customer mail, awaited so the answer can say whether it went.
async function mail(env, request, kind, booking, opts) {
  if (!booking.email) return { customer_mailed: false, why: "no email on this booking: call or text them" };
  const sent = await tellPatchlamp(env, request, kind, booking, opts);
  if (sent === true) return { customer_mailed: true };
  return { customer_mailed: false, why: sent === null ? "mail isn't set up on this site (PATCHLAMP_SLUG, BOOKING_KEY)" : "patchlamp.com didn't take the mail; the booking is changed" };
}

export async function onRequestPost({ request, env, params }) {
  if (!env.BOOKING_KEY) return json(503, { ok: false, error: "this site has no BOOKING_KEY yet (db bookings setup, then site publish)" });
  const raw = await request.text();
  if (!(await verifySigned(env, request, raw))) return json(401, { ok: false, error: "not signed by this site's key, or too old" });
  const body = JSON.parse(raw);
  const id = parseInt(params.id, 10);
  const action = String(body.action || "");
  if (!ACTIONS.includes(action)) return json(422, { ok: false, error: `action is one of ${ACTIONS.join(", ")}` });
  const before = id ? await env.DB.prepare("SELECT * FROM bookings WHERE id = ?").bind(id).first() : null;
  if (!before) return json(404, { ok: false, error: `no booking ${params.id}` });

  if (action === "confirm") {
    const r = await confirmBooking(env, id);
    if (!r.ok) return json(409, { ok: false, error: `it's ${before.status}, so there's nothing to confirm`, booking: shown(before) });
    await recordBooking(env, r.booking);
    return json(200, { ok: true, booking: shown(r.booking), ...(await mail(env, request, "confirmed", r.booking, { by: "owner" })) });
  }

  if (action === "cancel") {
    const r = await cancelBooking(env, id);
    if (!r.ok) return json(409, { ok: false, error: `it's ${before.status} already`, booking: shown(before) });
    await recordBooking(env, r.booking);
    return json(200, { ok: true, booking: shown(r.booking), ...(await mail(env, request, "cancelled", r.booking, { by: "owner" })) });
  }

  if (action === "move") {
    if (!TAKEN.includes(`'${before.status}'`)) return json(409, { ok: false, error: `it's ${before.status}, so it can't be moved`, booking: shown(before) });
    const slot = body.slot ? parseInt(body.slot, 10) : (await openSlotAt(env, body.starts_at, before.slot_id))?.id;
    const open = async () => (await openSlots(env, before.slot_id)).slice(0, 20).map((s) => ({ slot: s.id, starts_at: s.starts_at, places: s.places, label: s.label }));
    if (!slot) {
      return json(409, { ok: false, error: `no open time at ${body.starts_at || "(none given)"}: open one first (a booking_slots row), or pick one of these`,
        booking: shown(before), open: await open() });
    }
    const moved = await moveBooking(env, id, slot);
    if (!moved.ok) return json(409, { ok: false, error: "that time was taken or closed just now", booking: shown(before), open: await open() });
    await recordBooking(env, moved.booking);
    return json(200, { ok: true, booking: shown(moved.booking, moved.was),
      ...(await mail(env, request, "moved", moved.booking, { by: "owner", was: moved.was })) });
  }

  // remind: a confirmed booking still ahead
  if (before.status !== "confirmed" || String(before.starts_at).slice(0, 16) <= localNow(env)) {
    return json(409, { ok: false, error: before.status !== "confirmed" ? `it's ${before.status}; only a confirmed booking gets a reminder` : "it's already past",
      booking: shown(before) });
  }
  // a reminder is something they didn't just ask for, so the customer book's
  // "asked not to be contacted" mark holds it back (the booking's own mails don't check it)
  let c = null;
  try { c = await findCustomer(env, { phone: before.phone, email: before.email }); } catch { c = null; }   // no book on this site
  if (c && c.contact === "stop") {
    return json(409, { ok: false, error: "they asked not to be contacted (the customer book), so no reminder", booking: shown(before) });
  }
  return json(200, { ok: true, booking: shown(before), ...(await mail(env, request, "reminder", before, { by: "owner" })) });
}
