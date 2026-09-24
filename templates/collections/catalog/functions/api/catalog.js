// GET /api/catalog — what the site sells, as the page shows it: the products
// on sale or sold out (hidden ones left out), grouped by the page, the pickup
// hours, whether it's open now, and whether checkout is switched on.
//
//   {"products":[{id, name, description, category, price_cents, image, status}],
//    "hours":[{weekday, opens, closes, note}], "open_now": true,
//    "checkout": "off" | "test" | "live"}
//
// The page reads this as it loads, so a price or an item the owner (or Patch,
// by text) changes in the database is on the site at once — no publish.
import { localNow } from "../_lib/core.js";

export function checkoutMode(env) {
  const k = env.STRIPE_SECRET_KEY || "";
  return k.startsWith("sk_live_") || k.startsWith("rk_live_") ? "live" : k.startsWith("sk_test_") || k.startsWith("rk_test_") ? "test" : "off";
}

export function openNow(hours, env) {
  const now = localNow(env);                                  // 2026-10-06T09:30, the site's clock
  const [y, m, d] = now.slice(0, 10).split("-").map(Number);
  const weekday = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  const hm = now.slice(11, 16);
  return hours.some((h) => Number(h.weekday) === weekday && h.opens <= hm && hm < h.closes);
}

export async function onRequestGet({ env }) {
  const products = (await env.DB.prepare(
    "SELECT id, name, description, category, price_cents, image, status FROM products " +
    "WHERE status IN ('on sale', 'sold out') ORDER BY sort, category, id"
  ).all()).results || [];
  const hours = (await env.DB.prepare("SELECT weekday, opens, closes, note FROM hours ORDER BY weekday, opens").all()).results || [];
  return Response.json({ products, hours, open_now: openNow(hours, env), checkout: checkoutMode(env) },
    { headers: { "cache-control": "no-store" } });
}
