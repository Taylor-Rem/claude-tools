// /admin/ledger — the shell's list (month and category choosers, the total
// on the totals line, Download CSV), with three things above it: what this
// page is and isn't (the sentence below is a public claim: patchlamp
// CLAIMS.md), the last twelve months' totals, and where the photos are. Below
// it, a form to add a receipt by hand, in dollars.
import { onRequestGet as list } from "../[collection]/index.js";
import { page, esc, money, readBody, redirect } from "../../_lib/core.js";

export const NOT_ADVICE = "This is a record of what you spent, from the receipts you sent Patch. " +
  "It is not bookkeeping advice, and the categories are your own words, not categories a CPA would sign. " +
  "Hand the export to whoever does your taxes and let them sort it.";

// "$1,200.50", "42.18", "-12" -> cents; null when it isn't an amount.
export function cents(v) {
  const s = String(v ?? "").replace(/[$,\s]/g, "");
  if (!/^-?\d+(\.\d{1,2})?$/.test(s)) return null;
  return Math.round(parseFloat(s) * 100);
}

async function months(env) {
  try {
    return (await env.DB.prepare(
      "SELECT month, COUNT(*) AS n, SUM(amount_cents) AS total FROM ledger GROUP BY month ORDER BY month DESC LIMIT 12").all()).results || [];
  } catch (_) {
    return [];
  }
}

function monthName(m) {
  const [y, mo] = String(m || "").split("-").map(Number);
  if (!y || !mo) return String(m || "");
  return new Date(Date.UTC(y, mo - 1, 1)).toLocaleString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
}

export async function onRequestGet(ctx) {
  const res = await list({ ...ctx, params: { ...ctx.params, collection: "ledger" } });
  if (res.status !== 200 || !(res.headers.get("content-type") || "").startsWith("text/html")) return res;
  const by = await months(ctx.env);
  const table = by.length ? `<h2>By month</h2>
    <div class="table-wrap"><table class="list"><thead><tr><th scope="col">Month</th><th scope="col" class="num">Receipts</th><th scope="col" class="num">Total</th></tr></thead><tbody>
    ${by.map((r) => `<tr><td data-label="Month"><a href="/admin/ledger?month=${esc(r.month)}">${esc(monthName(r.month))}</a></td><td data-label="Receipts" class="num">${r.n}</td><td data-label="Total" class="num">${esc(money(r.total))}</td></tr>`).join("")}
    </tbody></table></div>` : "";
  const intro = `<p class="note">${esc(NOT_ADVICE)}</p>
    <p class="note">The receipt photos stay with Patch, not on this website: text for one and Patch sends it back. An export (ask Patch for one any time; you get one if you leave) carries them all, zipped, beside this list.</p>`;
  const add = `<h2>Add a receipt</h2>
    <form class="edit" method="post" action="/admin/ledger">
      <label>Date <input name="date" type="date" required></label>
      <label>Vendor <input name="vendor" required></label>
      <label>Amount <input name="amount" inputmode="decimal" placeholder="42.18" required></label>
      <label>Category <input name="category" placeholder="fuel, supplies, equipment"></label>
      <label>What it was for <input name="note"></label>
      <button type="submit">Add</button>
    </form>`;
  let html = await res.text();
  html = html.replace("<h1>Ledger</h1>", `<h1>Ledger</h1>\n    ${intro}`)
    .replace("</main>", `${table}\n${add}\n</main>`);
  return new Response(html, { status: res.status, headers: res.headers });
}

export async function onRequestPost({ request, env, data }) {
  const b = await readBody(request);
  const v = (k) => String(b[k] ?? "").trim().slice(0, 500);
  const amount = cents(v("amount"));
  const date = /^\d{4}-\d{2}-\d{2}$/.test(v("date")) ? v("date") : "";
  if (!v("vendor") || amount === null || !date) {
    return page(env, "Missing", `<h1>A date, a vendor and an amount are needed</h1><p>The amount as dollars: 42.18.</p><p><a href="/admin/ledger">Back</a></p>`,
      { status: 422, session: data.session });
  }
  const r = await env.DB.prepare("INSERT INTO ledger (date, vendor, amount_cents, category, note, source) VALUES (?, ?, ?, ?, ?, 'admin')")
    .bind(date, v("vendor"), amount, v("category") || null, v("note") || null).run();
  return redirect(`/admin/ledger/${r.meta.last_row_id}`);
}
