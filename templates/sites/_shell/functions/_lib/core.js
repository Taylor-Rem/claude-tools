// The server side of the site: helpers every Function here shares.
//
// Plain ES modules, no build step, no packages — Cloudflare Pages runs these
// files exactly as they are. Nothing in functions/ runs for the static pages:
// Pages only routes the paths that have a file here (/admin/*, /api/*).
//
// What the Functions can reach (set by `site data`, see wrangler.toml):
//   env.DB              this site's own D1 database, and nothing else
//   env.SESSION_SECRET  signs the owner's sign-in cookie (a Pages secret)
//   env.ADMIN_EMAIL     the one address that may sign in (a Pages secret)
//   env.PATCHLAMP_SLUG  this site's project on patchlamp.com (sends the email)
//   env.PATCHLAMP_URL   https://patchlamp.com
//   env.SITE_NAME       the business's name, for page titles
//   env.TIMEZONE        how times are shown on /admin (default America/Denver)

export const SESSION_COOKIE = "__Host-admin";
export const TOKEN_MINUTES = 15;
export const SESSION_DAYS = 14;
const IDENT = /^[a-z_][a-z0-9_]*$/;
const enc = new TextEncoder();

export const now = () => Math.floor(Date.now() / 1000);

export function ident(name) {
  if (!IDENT.test(name)) throw new Error(`bad identifier ${name}`);
  return name;
}

export function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function hex(buf) {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function randomHex(bytes = 32) {
  const b = new Uint8Array(bytes);
  crypto.getRandomValues(b);
  return hex(b);
}

export async function sha256(s) {
  return hex(await crypto.subtle.digest("SHA-256", enc.encode(s)));
}

async function hmac(secret, msg) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  return hex(await crypto.subtle.sign("HMAC", key, enc.encode(msg)));
}

function sameString(a, b) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

export function cookie(request, name) {
  const raw = request.headers.get("cookie") || "";
  for (const part of raw.split(/;\s*/)) {
    const i = part.indexOf("=");
    if (i > 0 && part.slice(0, i) === name) return part.slice(i + 1);
  }
  return null;
}

// A POST from a browser carries Origin; it must be this site. (No Origin at
// all is a non-browser client, which has no cookie to ride on.)
export function sameOrigin(request) {
  const origin = request.headers.get("origin");
  return !origin || origin === new URL(request.url).origin;
}

// A wall-clock time with no zone ("2026-10-06T09:00", how bookings keep a
// slot's start): shown as written, never shifted by the site's time zone.
const LOCAL_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

export function localTime(value) {
  const d = new Date(value + ":00Z");
  if (isNaN(d)) return String(value);
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC", weekday: "short", month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
  }).format(d);
}

// Now, as a wall-clock time in the site's zone ("2026-10-06T09:00").
export function localNow(env, plusDays = 0) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: env.TIMEZONE || "America/Denver", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date(Date.now() + plusDays * 86400000)).map((p) => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

export function when(value, env) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "string" && LOCAL_TIME.test(value)) return localTime(value);
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(String(value).replace(" ", "T") + (/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? "" : "Z"));
  if (isNaN(d)) return String(value);
  return new Intl.DateTimeFormat("en-US", {
    timeZone: env.TIMEZONE || "America/Denver", month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit",
  }).format(d);
}

// ---------------------------------------------------------------- pages

const STYLE = `
  .admin { max-width: 64rem; margin: 0 auto; padding: var(--space-lg, 2.5rem) var(--page-pad, 1.25rem); }
  .admin h1 { font-size: clamp(1.8rem, 5vw, 2.4rem); margin-bottom: var(--space, 1rem); }
  .admin-bar { display: flex; flex-wrap: wrap; gap: .5rem 1.5rem; align-items: center; justify-content: space-between;
    padding: .75rem var(--page-pad, 1.25rem); border-bottom: 1px solid var(--bg-line, #ddd); background: var(--bg-raised, #fff); }
  .admin-bar a { text-decoration: none; }
  .admin-bar form { margin: 0; }
  .admin table { width: 100%; border-collapse: collapse; margin: var(--space, 1rem) 0; font-size: .95rem; }
  .admin th, .admin td { text-align: left; padding: .55rem .5rem; border-bottom: 1px solid var(--bg-line, #ddd); vertical-align: top; }
  .admin th { color: var(--ink-dim, #666); font-weight: 500; }
  .admin td a { display: block; }
  .admin .table-wrap { overflow-x: auto; }
  .admin dl { display: grid; grid-template-columns: minmax(7rem, max-content) 1fr; gap: .4rem 1.25rem; margin: var(--space, 1rem) 0 var(--space-lg, 2rem); }
  .admin dt { color: var(--ink-dim, #666); }
  .admin dd { white-space: pre-wrap; overflow-wrap: anywhere; }
  .admin form.edit, .admin form.sign-in { display: grid; gap: .75rem; max-width: 30rem; }
  .admin label { display: grid; gap: .25rem; }
  .admin input, .admin select, .admin textarea { font: inherit; padding: .55rem .7rem; border: 1px solid var(--bg-line, #ccc);
    border-radius: 4px; background: var(--bg-raised, #fff); color: var(--ink, #111); }
  .admin textarea { min-height: 6rem; }
  .admin button, .admin-bar button { font: inherit; padding: .55rem 1.1rem; border: 0; border-radius: 4px;
    background: var(--accent, #333); color: #fff; cursor: pointer; justify-self: start; }
  .admin-bar button { background: transparent; color: var(--accent, #333); padding: 0; }
  .admin .pager { display: flex; gap: 1.5rem; }
  .admin .status { display: inline-block; padding: 0 .45rem; border-radius: 3px; background: var(--bg-line, #eee); font-size: .85rem; }
  .admin .cards { list-style: none; display: grid; gap: .75rem; grid-template-columns: repeat(auto-fill, minmax(14rem, 1fr)); margin: var(--space, 1rem) 0; }
  .admin .cards a { display: block; padding: 1rem; border: 1px solid var(--bg-line, #ddd); border-radius: 6px; background: var(--bg-raised, #fff); text-decoration: none; }
  .admin .note { color: var(--ink-dim, #666); }
`;

export function page(env, title, body, { status = 200, headers = {}, session = null } = {}) {
  const site = env.SITE_NAME || "Website";
  const bar = session
    ? `<div class="admin-bar"><a href="/admin">${esc(site)} · admin</a>
        <form method="post" action="/admin/logout"><button type="submit">Sign out</button></form></div>`
    : "";
  const html = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <meta name="description" content="${esc(site)}'s admin page, for the owner only.">
  <title>${esc(title)} — ${esc(site)}</title>
  <link rel="stylesheet" href="/css/style.css">
  <style>${STYLE}</style>
</head>
<body>
${bar}
<main class="admin">
${body}
</main>
</body>
</html>`;
  return new Response(html, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex",
      "referrer-policy": "no-referrer", "x-frame-options": "DENY", ...headers,
    },
  });
}

export function redirect(url, headers = {}) {
  return new Response(null, { status: 303, headers: { location: url, "cache-control": "no-store", ...headers } });
}

// ---------------------------------------------------------------- the owner's session

export function notSetUp(env) {
  const missing = ["DB", "SESSION_SECRET", "ADMIN_EMAIL"].filter((k) => !env[k]);
  return missing.length ? missing : null;
}

export async function readSession(request, env) {
  const raw = cookie(request, SESSION_COOKIE);
  if (!raw || !env.SESSION_SECRET || !env.DB) return null;
  const [id, sig] = raw.split(".");
  if (!id || !sig || !sameString(sig, await hmac(env.SESSION_SECRET, id))) return null;
  const row = await env.DB.prepare("SELECT email, expires_at FROM admin_sessions WHERE id_hash = ?").bind(await sha256(id)).first();
  if (!row || row.expires_at < now()) return null;
  return { email: row.email, id };
}

export async function startSession(env, email) {
  const id = randomHex(32);
  const t = now();
  await env.DB.batch([
    env.DB.prepare("DELETE FROM admin_sessions WHERE expires_at < ?").bind(t),
    env.DB.prepare("INSERT INTO admin_sessions (id_hash, email, created_at, expires_at) VALUES (?, ?, ?, ?)")
      .bind(await sha256(id), email, t, t + SESSION_DAYS * 86400),
  ]);
  const value = `${id}.${await hmac(env.SESSION_SECRET, id)}`;
  return `${SESSION_COOKIE}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${SESSION_DAYS * 86400}`;
}

export async function endSession(request, env) {
  const s = await readSession(request, env);
  if (s) await env.DB.prepare("DELETE FROM admin_sessions WHERE id_hash = ?").bind(await sha256(s.id)).run();
  return `${SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`;
}

// The sign-in link goes out through patchlamp.com's form endpoint, which
// emails every field to the project's contact address. The site holds no
// mail key; the post comes from this site's own address, as a form would.
export async function sendSignInLink(env, request, link) {
  const base = (env.PATCHLAMP_URL || "https://patchlamp.com").replace(/\/$/, "");
  if (!env.PATCHLAMP_SLUG) return false;
  const origin = env.MAIL_ORIGIN || new URL(request.url).origin;   // MAIL_ORIGIN: local testing only
  const body = new URLSearchParams({
    sign_in_link: link,
    expires: `in ${TOKEN_MINUTES} minutes, and it works once`,
    note: "Someone asked to sign in to the website's admin page. If it wasn't you, ignore this email.",
  });
  try {
    const r = await fetch(`${base}/f/${encodeURIComponent(env.PATCHLAMP_SLUG)}/admin-sign-in`, {
      method: "POST", body,
      headers: { origin, referer: `${origin}/admin`, accept: "application/json", "content-type": "application/x-www-form-urlencoded" },
    });
    if (!r.ok) console.error(`sign-in mail: patchlamp.com answered ${r.status}`);
    return r.ok;
  } catch (e) {
    console.error(`sign-in mail: ${e}`);
    return false;
  }
}

// ---------------------------------------------------------------- collections

// Fields a public form may send: plain names, short values, at most 20.
export function formFields(data, skip = []) {
  const out = {};
  for (const [k, v] of Object.entries(data)) {
    if (typeof v !== "string" || skip.includes(k) || !/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(k)) continue;
    const t = v.trim();
    if (!t) continue;
    out[k] = t.slice(0, 2000);
    if (Object.keys(out).length >= 20) break;
  }
  return out;
}

export async function readBody(request) {
  const type = request.headers.get("content-type") || "";
  if (type.includes("application/json")) {
    const j = await request.json().catch(() => ({}));
    return j && typeof j === "object" ? j : {};
  }
  const out = {};
  const form = await request.formData();
  for (const [k, v] of form) if (typeof v === "string") out[k] = v;
  return out;
}

export function wantsJson(request) {
  return (request.headers.get("accept") || "").includes("application/json");
}

// Back to the page the form was on (this site only), with ?sent=<form>#form
// (or another anchor: the booking form is #book).
export function backTo(request, flag, hash = "form") {
  const self = new URL(request.url);
  let to = new URL("/", self);
  const ref = request.headers.get("referer");
  if (ref) {
    try {
      const r = new URL(ref);
      if (r.host === self.host) to = r;
    } catch (_) { /* keep / */ }
  }
  to.search = new URLSearchParams(flag).toString();
  to.hash = hash;
  return redirect(to.toString());
}
