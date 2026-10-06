// /estimate/<token> — the page a customer opens from the estimate's link (or
// its QR code) to read it and accept it.
//
//   GET   the estimate: the business, the lines, tax, total, deposit, the
//         date it is good until, the terms, and (while it can be accepted) a
//         box for their name and an Accept button.
//   POST  name=… (and the `website` honeypot): the acceptance. Written only
//         while the estimate is `sent` and not past its good-until day, in the
//         statement that changes the status, so it is accepted once. The name
//         as typed, the time and the IP address are kept as the record of it.
//         The owner is emailed through patchlamp.com like a form (form
//         `estimate-accepted`, no customer email in it, so nothing answers
//         the customer automatically); `estimate sync` (Patch, by text) does
//         the rest: the invoice or deposit link on the owner's Stripe, the
//         booking request, the customer book.
//
// The token is 32 random characters made by `estimate new`; there is no list
// of estimates anywhere public. Unknown token, a draft or a void estimate:
// the same "not found" page, so the page tells a stranger nothing.
import { esc, readBody, sameOrigin, localNow } from "../_lib/core.js";

const TOKEN = /^[A-Za-z0-9_-]{24,64}$/;
const NAME_MAX = 120;

const money = (c) => "$" + (Number(c || 0) / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const day = (d) => {
  const t = new Date(String(d || "") + "T12:00:00Z");
  return isNaN(t) ? String(d || "") : new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "long", day: "numeric", year: "numeric" }).format(t);
};

function shell(title, body, status = 200) {
  return new Response(`<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<meta name="referrer" content="same-origin">
<title>${esc(title)}</title><link rel="stylesheet" href="/css/style.css">
<style>
.est{max-width:42rem;margin:2rem auto;padding:0 1.25rem;font-family:var(--font-body,system-ui,sans-serif);color:var(--ink,#1d1d1f)}
.est h1{font-family:var(--font-display,inherit);margin:.2rem 0 1rem;line-height:1.15}
.est .kicker{color:var(--accent,#1d1d1f);text-transform:uppercase;letter-spacing:.12em;font-size:.8rem;font-weight:600}
.est table{width:100%;border-collapse:collapse;margin:1rem 0}
.est td{padding:.5rem 0;border-bottom:1px solid var(--bg-line,#ddd);vertical-align:top}
.est td.amt{text-align:right;white-space:nowrap;padding-left:1rem}
.est tr.total td{font-weight:700;border-bottom:none;font-size:1.1rem}
.est .muted{color:var(--ink-dim,#6b6b70)}
.est .terms{white-space:pre-line;font-size:.95rem}
.est form{margin:1.5rem 0;padding:1rem;border:1px solid var(--bg-line,#ddd);border-radius:.6rem}
.est input[type=text]{width:100%;font:inherit;padding:.6rem;margin:.4rem 0 .8rem;border:1px solid #bbb;border-radius:.4rem;box-sizing:border-box}
.est button{font:inherit;font-weight:600;padding:.65rem 1.4rem;border:0;border-radius:.4rem;background:var(--accent,#1d1d1f);color:#fff;cursor:pointer}
.est .hp{position:absolute;left:-9999px}
.est .done{padding:1rem;border-radius:.6rem;background:#eef7ee}
</style></head><body><main class="est">${body}</main></body></html>`,
    { status, headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex" } });
}

const notFound = () => shell("Estimate not found", `<h1>Estimate not found</h1>
<p class="muted">This link doesn't open an estimate. It may have been withdrawn; the business that sent it can send it again.</p>`, 404);

async function find(env, token) {
  if (!TOKEN.test(token || "")) return null;
  const row = await env.DB.prepare("SELECT * FROM estimates WHERE token = ?").bind(token).first();
  return row && ["sent", "accepted", "declined"].includes(row.status) ? row : null;
}

const today = (env) => localNow(env).slice(0, 10);
const open = (row, env) => row.status === "sent" && (!row.valid_until || row.valid_until >= today(env));

function render(row, env, { error = "", justAccepted = false } = {}) {
  let lines = [];
  try { lines = JSON.parse(row.lines || "[]"); } catch { lines = []; }
  const items = lines.map((l) => `<tr><td>${esc(l.what)}</td><td class="amt">${money(l.cents)}</td></tr>`).join("");
  const tax = row.tax_cents ? `<tr><td class="muted">Subtotal</td><td class="amt">${money(row.subtotal_cents)}</td></tr>
<tr><td class="muted">${esc(row.tax_label || "Tax")}</td><td class="amt">${money(row.tax_cents)}</td></tr>` : "";
  const deposit = row.deposit_cents ? `<p>A deposit of <strong>${money(row.deposit_cents)}</strong> is due when you accept; the rest is invoiced as the work is done.</p>` : "";
  const valid = row.valid_until ? `<p class="muted">Good until ${esc(day(row.valid_until))}.</p>` : "";
  const note = row.note ? `<p>${esc(row.note)}</p>` : "";
  const terms = row.terms ? `<h2>Terms</h2><p class="terms">${esc(row.terms)}</p>` : "";
  let action = "";
  if (row.status === "accepted") {
    action = `<p class="done">${justAccepted ? "Thank you. " : ""}Accepted by ${esc(row.accepted_name)} on ${esc(day(String(row.accepted_at || "").slice(0, 10)))}. ${esc(row.business || "The business")} has been told; ${row.deposit_cents ? "the deposit link" : "the invoice"} comes from them next.</p>`;
  } else if (row.status === "declined") {
    action = `<p class="muted">This estimate was declined.</p>`;
  } else if (!open(row, env)) {
    action = `<p class="muted">This estimate was good until ${esc(day(row.valid_until))}, so it can't be accepted here any more. Ask ${esc(row.business || "the business")} for a fresh one.</p>`;
  } else {
    action = `<form method="post">
${error ? `<p role="alert"><strong>${esc(error)}</strong></p>` : ""}
<label for="name"><strong>To accept, type your full name</strong></label>
<input type="text" id="name" name="name" autocomplete="name" maxlength="${NAME_MAX}" required>
<input class="hp" type="text" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
<p class="muted">Typing your name and pressing Accept tells ${esc(row.business || "the business")} you accept this estimate as written. It isn't a payment; ${row.deposit_cents ? "the deposit link" : "an invoice"} comes next. The time and your connection's IP address are kept with your name as the record.</p>
<button type="submit">Accept estimate</button>
</form>`;
  }
  const body = `<p class="kicker">${esc(row.business)} · Estimate ${esc(row.number)}</p>
<h1>For ${esc(row.customer)}</h1>
${note}
<table>${items}${tax}<tr class="total"><td>Total</td><td class="amt">${money(row.total_cents)}</td></tr></table>
${deposit}${valid}${action}${terms}`;
  return shell(`Estimate ${row.number} · ${row.business}`, body);
}

export async function onRequestGet({ params, env }) {
  const row = await find(env, params.token);
  return row ? render(row, env) : notFound();
}

export async function onRequestPost({ request, params, env, waitUntil }) {
  if (!sameOrigin(request)) return new Response("Forbidden", { status: 403 });
  const row = await find(env, params.token);
  if (!row) return notFound();
  const data = await readBody(request);
  if (String(data.website || "").trim()) return render(row, env);            // the honeypot: show the page again
  const name = String(data.name || "").replace(/\s+/g, " ").trim();
  if (row.status !== "sent") return render(row, env);
  if (name.length < 2 || name.length > NAME_MAX) return render(row, env, { error: "Type your full name to accept." });
  const ip = request.headers.get("cf-connecting-ip") || "";
  const agent = (request.headers.get("user-agent") || "").slice(0, 300);
  const at = new Date().toISOString().slice(0, 19) + "Z";
  const res = await env.DB.prepare(
    `UPDATE estimates SET status = 'accepted', accepted_name = ?, accepted_at = ?, accepted_ip = ?, accepted_agent = ?, updated_at = ?
      WHERE token = ? AND status = 'sent' AND (valid_until IS NULL OR valid_until >= ?)`
  ).bind(name, at, ip || null, agent || null, at, params.token, today(env)).run();
  const now = await env.DB.prepare("SELECT * FROM estimates WHERE token = ?").bind(params.token).first();
  if (!res.meta.changes) return render(now, env);                             // past its day, or accepted a moment ago
  if (env.PATCHLAMP_SLUG && env.FORWARD_EMAIL !== "off") {
    const base = (env.PATCHLAMP_URL || "https://patchlamp.com").replace(/\/$/, "");
    const origin = env.MAIL_ORIGIN || new URL(request.url).origin;
    const fields = { estimate: now.number, customer: now.customer, accepted_by: name, total: money(now.total_cents),
                     deposit: now.deposit_cents ? money(now.deposit_cents) : "none",
                     next: "Text Patch: estimate sync (the invoice or deposit link, the booking request, the customer book)" };
    waitUntil(fetch(`${base}/f/${encodeURIComponent(env.PATCHLAMP_SLUG)}/estimate-accepted`, {
      method: "POST", body: new URLSearchParams(fields),
      headers: { origin, referer: `${origin}/`, accept: "application/json", "content-type": "application/x-www-form-urlencoded" },
    }).then((r) => { if (!r.ok) console.error(`forward: patchlamp.com answered ${r.status}`); })
      .catch((e) => console.error(`forward: ${e}`)));
  }
  return render(now, env, { justAccepted: true });
}
