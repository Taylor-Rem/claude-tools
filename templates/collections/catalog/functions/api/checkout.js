// POST /api/checkout — send a customer to Stripe Checkout for pickup.
//
// Body (JSON): {"items":[{"id":3,"qty":2}], "name", "email", "phone", "note"}.
// Prices come from the database, never from the page. The order is written
// as `pending` with the Checkout session's id; /api/stripe-webhook marks it
// `paid` when Stripe says so. Pickup only: no shipping, no stock counts.
//
// The Stripe key is the owner's own, a Pages secret (STRIPE_SECRET_KEY, set
// by `site checkout`); this file never sees it printed. Without one the
// answer is 503 {"checkout":"off"} and the page says checkout isn't on.
import { sha256, now } from "../_lib/core.js";
import { checkoutMode } from "./catalog.js";

const MAX_LINES = 30;
const MAX_QTY = 20;
const PER_TEN_MINUTES = 10;

function form(obj, prefix = "", out = new URLSearchParams()) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}[${k}]` : k;
    if (v === undefined || v === null) continue;
    if (typeof v === "object") form(v, key, out);
    else out.append(key, String(v));
  }
  return out;
}

const money = (c) => `$${(c / 100).toFixed(2)}`;

export async function onRequestPost({ request, env }) {
  const mode = checkoutMode(env);
  if (mode === "off") return Response.json({ ok: false, checkout: "off", error: "checkout is not switched on" }, { status: 503 });
  let body;
  try { body = await request.json(); } catch (_) { body = null; }
  const lines = Array.isArray(body?.items) ? body.items.slice(0, MAX_LINES) : [];
  const want = new Map();
  for (const l of lines) {
    const id = parseInt(l?.id, 10), qty = parseInt(l?.qty, 10);
    if (id > 0 && qty > 0) want.set(id, Math.min(MAX_QTY, (want.get(id) || 0) + qty));
  }
  if (!want.size) return Response.json({ ok: false, error: "nothing in the order" }, { status: 422 });
  const str = (v, n = 200) => (typeof v === "string" ? v.trim().slice(0, n) : "");
  const name = str(body.name), email = str(body.email), phone = str(body.phone, 40), note = str(body.note, 500);
  if (!name || !(email || phone)) return Response.json({ ok: false, error: "a name, and an email or phone" }, { status: 422 });

  const ip = request.headers.get("cf-connecting-ip") || "";
  const ipHash = ip ? await sha256(ip + (env.SESSION_SECRET || "")) : null;
  if (ipHash) {
    const since = new Date((now() - 600) * 1000).toISOString().slice(0, 19) + "Z";
    const r = await env.DB.prepare("SELECT COUNT(*) AS n FROM orders WHERE ip_hash = ? AND created_at > ?").bind(ipHash, since).first();
    if (r.n >= PER_TEN_MINUTES) return Response.json({ ok: false, error: "too many, try again later" }, { status: 429 });
  }

  const ids = [...want.keys()];
  const rows = (await env.DB.prepare(
    `SELECT id, name, price_cents FROM products WHERE status = 'on sale' AND id IN (${ids.map(() => "?").join(", ")})`
  ).bind(...ids).all()).results || [];
  if (rows.length !== ids.length) return Response.json({ ok: false, error: "something in the order isn't for sale any more" }, { status: 409 });
  const items = rows.map((r) => ({ id: r.id, name: r.name, qty: want.get(r.id), price_cents: r.price_cents }));
  const total = items.reduce((t, i) => t + i.qty * i.price_cents, 0);
  const summary = items.map((i) => `${i.qty} × ${i.name}`).join(", ");

  const origin = new URL(request.url).origin;
  const res = await fetch("https://api.stripe.com/v1/checkout/sessions", {
    method: "POST",
    headers: { authorization: `Bearer ${env.STRIPE_SECRET_KEY}`, "content-type": "application/x-www-form-urlencoded" },
    body: form({
      mode: "payment",
      success_url: `${origin}/?order=paid#shop`,
      cancel_url: `${origin}/?order=cancelled#shop`,
      customer_email: email || undefined,
      phone_number_collection: { enabled: "true" },
      metadata: { site: env.SITE_NAME || origin, pickup_name: name, summary: summary.slice(0, 450) },
      line_items: items.map((i) => ({ quantity: i.qty, price_data: { currency: "usd", unit_amount: i.price_cents, product_data: { name: i.name } } })),
    }),
  });
  const session = await res.json().catch(() => ({}));
  if (!res.ok || !session.url) {
    console.error(`checkout: Stripe answered ${res.status} ${session?.error?.message || ""}`);
    return Response.json({ ok: false, error: "checkout didn't open; please try again" }, { status: 502 });
  }
  await env.DB.prepare(
    "INSERT INTO orders (stripe_session_id, name, email, phone, items, summary, total_cents, note, mode, status, ip_hash) " +
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)"
  ).bind(session.id, name, email || null, phone || null, JSON.stringify(items), summary, total, note || null, mode, ipHash).run();
  return Response.json({ ok: true, url: session.url, total: money(total), mode });
}
