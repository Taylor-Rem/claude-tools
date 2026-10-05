// /book/manage?t=<token> — the customer's own booking, from the link in each
// booking email (functions/_lib/bookings.js signs it). They can move it to
// another open time or cancel it; the owner is emailed the change, the row
// is updated, and the customer book follows.
//
// GET only shows the booking (mail scanners open links on their own, so
// opening the link must never change anything); the buttons POST. A wrong or
// expired link is a plain page that says so and how to reach the business.
import { esc, localTime, localNow, readBody, sameOrigin } from "../_lib/core.js";
import { readManageToken, openSlots, moveBooking, tellPatchlamp, recordBooking, customerPage, sorry, TAKEN } from "../_lib/bookings.js";

const STYLE = `<style>
  .booking-manage { max-width: 36rem; }
  .booking-manage form { display: grid; gap: .75rem; margin: 1.25rem 0; }
  .booking-manage fieldset { border: 0; padding: 0; margin: 0; display: grid; gap: .5rem; }
  .booking-manage .slot { display: flex; align-items: center; gap: .6rem; min-height: 44px; }
  .booking-manage .slot input { width: 1.25rem; height: 1.25rem; margin: 0; }
  .booking-manage .when { font-size: 1.2rem; font-weight: 600; }
  .booking-manage button.quiet { background: transparent; color: var(--accent, #333); border: 1px solid var(--accent, #333); }
</style>`;

async function load(env, url) {
  const id = await readManageToken(env, url.searchParams.get("t"));
  if (!id) return null;
  return env.DB.prepare("SELECT b.*, s.label FROM bookings b LEFT JOIN booking_slots s ON s.id = b.slot_id WHERE b.id = ?").bind(id).first();
}

function show(env, b, slots, t, note = "") {
  const site = esc(env.SITE_NAME || "us");
  const live = TAKEN.includes(`'${b.status}'`) && b.starts_at > localNow(env);
  const state = { requested: "requested — not confirmed yet", confirmed: "confirmed", cancelled: "cancelled", done: "done" }[b.status] || b.status;
  let body = `${STYLE}<h1>Your booking</h1>${note ? `<p><strong>${esc(note)}</strong></p>` : ""}
    <p class="when">${esc(localTime(b.starts_at))}${b.label ? ` · ${esc(b.label)}` : ""}</p>
    <p>With ${site}, for ${esc(b.name)}: ${esc(state)}.</p>`;
  if (!live) {
    body += `<p>This booking can't be changed here any more. Reply to your booking email to reach ${site}${b.status === "cancelled" ? `, or <a href="/#book">book another time</a>` : ""}.</p>`;
    return customerPage(env, "Your booking", body);
  }
  const hidden = `<input type="hidden" name="t" value="${esc(t)}">`;
  body += slots.length
    ? `<h2>Move it</h2><form method="post">${hidden}<input type="hidden" name="action" value="move">
        <fieldset><legend>Pick another time</legend>${slots.map((s) =>
          `<label class="slot"><input type="radio" name="slot" value="${s.id}" required> ${esc(localTime(s.starts_at))}${s.label ? ` · ${esc(s.label)}` : ""}</label>`).join("")}
        </fieldset><button type="submit">Move my booking</button></form>`
    : `<p>There are no other open times right now. Reply to your booking email to ask ${site} for one.</p>`;
  body += `<h2>Cancel it</h2><form method="post">${hidden}<input type="hidden" name="action" value="cancel">
      <button class="quiet" type="submit">Cancel my booking</button></form>`;
  return customerPage(env, "Your booking", body);
}

export async function onRequestGet({ request, env }) {
  const url = new URL(request.url);
  const b = await load(env, url);
  if (!b) return sorry(env, "This link isn't right, or it has run out.");
  return show(env, b, await openSlots(env, b.slot_id), url.searchParams.get("t"));
}

export async function onRequestPost({ request, env, waitUntil }) {
  if (!sameOrigin(request)) return sorry(env, "That came from another site, so nothing was changed.");
  const body = await readBody(request);
  const t = String(body.t || "");
  const url = new URL(request.url);
  url.searchParams.set("t", t);
  const b = await load(env, url);
  if (!b) return sorry(env, "This link isn't right, or it has run out, so nothing was changed.");
  if (!TAKEN.includes(`'${b.status}'`) || b.starts_at <= localNow(env)) {
    return show(env, b, [], t);
  }
  if (body.action === "cancel") {
    await env.DB.prepare(`UPDATE bookings SET status = 'cancelled', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ? AND status IN ${TAKEN}`).bind(b.id).run();
    const now = await env.DB.prepare("SELECT * FROM bookings WHERE id = ?").bind(b.id).first();
    await recordBooking(env, now);
    waitUntil(tellPatchlamp(env, request, "cancelled", now, { by: "customer" }));
    return show(env, now, [], t, "Cancelled. We've let them know.");
  }
  if (body.action === "move") {
    const moved = await moveBooking(env, b.id, parseInt(body.slot || "", 10));
    if (!moved.ok) return show(env, b, await openSlots(env, b.slot_id), t, "That time was just taken or closed. Please pick another.");
    await recordBooking(env, moved.booking);
    waitUntil(tellPatchlamp(env, request, "moved", moved.booking, { by: "customer", was: moved.was }));
    return show(env, moved.booking, await openSlots(env, moved.booking.slot_id), t, "Moved. We've let them know, and an email with the new time is on its way.");
  }
  return show(env, b, await openSlots(env, b.slot_id), t);
}
