// POST /api/submissions — a form on this site. The row goes into this site's
// own database; a copy goes on to patchlamp.com's form endpoint so the owner
// is still emailed each one, as before the site had a database.
//
// The form: <form action="/api/submissions" method="post"> with a hidden
// `_form` (a short lowercase name: quote, contact, booking), any fields with
// plain names (name, email, phone and message get their own columns), and
// the hidden `website` honeypot. Afterwards the page reloads with ?sent=<form>#form.
import { readBody, formFields, sha256, wantsJson, backTo, now } from "../_lib/core.js";

const PER_TEN_MINUTES = 5;

export async function onRequestPost({ request, env, waitUntil }) {
  const data = await readBody(request);
  const form = /^[a-z][a-z0-9-]{0,63}$/.test(data._form || "") ? data._form : "contact";
  const reply = (status, extra = {}) =>
    wantsJson(request) ? Response.json({ ok: status < 400, ...extra }, { status }) : status < 400 ? backTo(request, { sent: form }) : backTo(request, { sent: "0" });

  if (String(data.website || "").trim()) return reply(200);          // the honeypot: pretend it worked
  const fields = formFields(data, ["website", "_form"]);
  if (!Object.keys(fields).length) return reply(422, { error: "empty form" });

  const ip = request.headers.get("cf-connecting-ip") || "";
  const ipHash = ip ? await sha256(ip + (env.SESSION_SECRET || "")) : null;
  if (ipHash) {
    const since = new Date((now() - 600) * 1000).toISOString().slice(0, 19) + "Z";
    const r = await env.DB.prepare("SELECT COUNT(*) AS n FROM submissions WHERE ip_hash = ? AND created_at > ?").bind(ipHash, since).first();
    if (r.n >= PER_TEN_MINUTES) return reply(429, { error: "too many, try again later" });
  }

  const pick = (k) => fields[k] || null;
  const row = await env.DB.prepare(
    "INSERT INTO submissions (form, name, email, phone, message, fields, ip_hash) VALUES (?, ?, ?, ?, ?, ?, ?)"
  ).bind(form, pick("name"), pick("email"), pick("phone"), pick("message"), JSON.stringify(fields), ipHash).run();

  if (env.PATCHLAMP_SLUG && env.FORWARD_EMAIL !== "off") {
    const base = (env.PATCHLAMP_URL || "https://patchlamp.com").replace(/\/$/, "");
    const origin = env.MAIL_ORIGIN || new URL(request.url).origin;
    waitUntil(fetch(`${base}/f/${encodeURIComponent(env.PATCHLAMP_SLUG)}/${form}`, {
      method: "POST", body: new URLSearchParams(fields),
      headers: { origin, referer: `${origin}/`, accept: "application/json", "content-type": "application/x-www-form-urlencoded" },
    }).then((r) => { if (!r.ok) console.error(`forward: patchlamp.com answered ${r.status}`); })
      .catch((e) => console.error(`forward: ${e}`)));
  }
  return reply(200, { id: row.meta.last_row_id });
}
