// POST /api/stripe-webhook — Stripe tells the site a Checkout was paid.
//
// The signature (Stripe-Signature: t=…,v1=…) is checked against the
// endpoint's secret (STRIPE_WEBHOOK_SECRET, a Pages secret set by `site
// checkout`), and events older than five minutes are refused. On
// checkout.session.completed with payment_status "paid" the pending order
// becomes `paid`, with the name, email and phone Stripe collected. Anything
// else is acknowledged and ignored.
const TOLERANCE = 300;
const enc = new TextEncoder();

async function hmacHex(secret, msg) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return [...new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(msg)))].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function same(a, b) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

export async function verify(payload, header, secret, at = Math.floor(Date.now() / 1000)) {
  const parts = Object.fromEntries((header || "").split(",").map((p) => p.split("=")).filter((p) => p.length === 2 && p[0] === "t"));
  const sigs = (header || "").split(",").filter((p) => p.startsWith("v1=")).map((p) => p.slice(3));
  const t = parseInt(parts.t, 10);
  if (!t || !sigs.length || Math.abs(at - t) > TOLERANCE) return false;
  const want = await hmacHex(secret, `${t}.${payload}`);
  return sigs.some((s) => same(s, want));
}

export async function onRequestPost({ request, env }) {
  if (!env.STRIPE_WEBHOOK_SECRET) return new Response("webhook not set up", { status: 503 });
  const payload = await request.text();
  if (!(await verify(payload, request.headers.get("stripe-signature"), env.STRIPE_WEBHOOK_SECRET))) {
    return new Response("bad signature", { status: 400 });
  }
  let event;
  try { event = JSON.parse(payload); } catch (_) { return new Response("bad json", { status: 400 }); }
  const s = event?.data?.object || {};
  if (event.type === "checkout.session.completed" && s.payment_status === "paid") {
    const c = s.customer_details || {};
    await env.DB.prepare(
      "UPDATE orders SET status = 'paid', email = COALESCE(?, email), phone = COALESCE(?, phone), total_cents = COALESCE(?, total_cents), " +
      "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE stripe_session_id = ? AND status = 'pending'"
    ).bind(c.email || null, c.phone || null, s.amount_total ?? null, s.id).run();
  }
  return Response.json({ received: true });
}
