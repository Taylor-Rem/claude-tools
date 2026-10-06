// /admin/bookings/<id> — the shell's entry page for a booking, and what the
// owner's changes set off (B119): confirming or cancelling emails the
// customer, "Move to" (below the details) takes another open time and emails
// them the new one, and the customer book follows each change. The list's
// one-tap buttons post here too.
import { onRequestGet as show, onRequestPost as save } from "../[collection]/[id].js";
import { esc, localTime, readBody, redirect } from "../../_lib/core.js";
import { openSlots, moveBooking, tellPatchlamp, recordBooking } from "../../_lib/bookings.js";

const at = (ctx) => ({ ...ctx, params: { ...ctx.params, collection: "bookings" } });

export async function onRequestGet(ctx) {
  const res = await show(at(ctx));
  const id = parseInt(ctx.params.id, 10);
  const b = res.status === 200 && id ? await ctx.env.DB.prepare("SELECT * FROM bookings WHERE id = ?").bind(id).first() : null;
  if (!b || !["requested", "confirmed"].includes(b.status)) return res;
  const slots = await openSlots(ctx.env, b.slot_id);
  const mailNote = b.email ? ` ${esc(b.name)} is emailed the new time.` : " They left no email, so call or text them the new time.";
  const move = slots.length
    ? `<h2>Move to another time</h2><form class="edit" method="post"><input type="hidden" name="action" value="move">
        <label>Open times<select name="slot" required>${slots.map((s) =>
          `<option value="${s.id}">${esc(localTime(s.starts_at))}${s.label ? ` · ${esc(s.label)}` : ""}</option>`).join("")}</select></label>
        <button type="submit">Move it</button><p class="note">${mailNote}</p></form>`
    : `<p class="note">No other open times to move it to (open one on <a href="/admin/slots">Open times</a>).</p>`;
  const note = b.email
    ? `<p class="note">Confirming or cancelling emails ${esc(b.email)}.</p>`
    : `<p class="note">No email on this booking: confirming or cancelling here doesn't reach them.</p>`;
  const html = (await res.text()).replace("</main>", `${note}${move}\n</main>`);
  return new Response(html, { status: res.status, headers: res.headers });
}

export async function onRequestPost(ctx) {
  const { env, request } = ctx;
  const id = parseInt(ctx.params.id, 10);
  const before = id ? await env.DB.prepare("SELECT * FROM bookings WHERE id = ?").bind(id).first() : null;
  const body = await readBody(request.clone()).catch(() => ({}));
  if (before && body.action === "move") {
    const moved = await moveBooking(env, id, parseInt(body.slot || "", 10));
    if (moved.ok) {
      await recordBooking(env, moved.booking);
      ctx.waitUntil(tellPatchlamp(env, request, "moved", moved.booking, { by: "owner", was: moved.was }));
    }
    return redirect(`/admin/bookings/${id}`);
  }
  const res = await save(at(ctx));
  const after = before ? await env.DB.prepare("SELECT * FROM bookings WHERE id = ?").bind(id).first() : null;
  if (before && after && after.status !== before.status) {
    await recordBooking(env, after);
    if (after.status === "confirmed" || after.status === "cancelled") {
      ctx.waitUntil(tellPatchlamp(env, request, after.status, after, { by: "owner" }));
    }
  }
  return res;
}
