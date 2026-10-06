// /sign/<token> — one document sent to one customer (`sign new`, ROADMAP B128).
// GET shows it: the text, and a form to type a full name and tick the box.
// POST records the signature: the typed name, the time (UTC), the IP the
// request came from, the browser, and the sha256 of the text at that moment.
// The owner is told through patchlamp.com's form endpoint (the same mail a
// form on the site sends); the signed PDF is made in the workspace by
// `sign show`, which is where the copies come from.
//
// GET never changes anything: mail and chat apps open links on their own to
// preview them, and a preview must not sign. A wrong, withdrawn or already
// signed link is a plain page that says so.
import { esc, sha256, readBody, sameOrigin } from "../_lib/core.js";

const TOKEN = /^[A-Za-z0-9_-]{20,100}$/;
const NAME_MAX = 120;

const STYLE = `<style>
  .sign { max-width: 40rem; margin: 0 auto; padding: 1.25rem 1rem 3rem; line-height: 1.55; }
  .sign h1 { font-size: 1.6rem; line-height: 1.2; margin: .25rem 0 .5rem; }
  .sign .for { color: #555; margin: 0 0 1.25rem; }
  .sign .doc { border: 1px solid #ddd; border-radius: .5rem; padding: 1rem; background: #fff; overflow-wrap: anywhere; }
  .sign .doc > :first-child { margin-top: 0; }
  .sign .doc h1, .sign .doc h2, .sign .doc h3 { font-family: inherit; font-weight: 700; line-height: 1.3; margin: 1.1rem 0 .35rem; letter-spacing: 0; text-transform: none; }
  .sign .doc h1 { font-size: 1.2rem; } .sign .doc h2 { font-size: 1.1rem; } .sign .doc h3 { font-size: 1rem; }
  .sign .doc p { margin: .5rem 0; }
  .sign .doc ul, .sign .doc ol { margin: .4rem 0 .8rem; padding-left: 1.4rem; }
  .sign .doc li { margin: .25rem 0; }
  .sign form { display: grid; gap: .9rem; margin: 1.5rem 0 1rem; }
  .sign label.name { display: grid; gap: .35rem; font-weight: 600; }
  .sign input[type=text] { font: inherit; font-size: 1.1rem; padding: .7rem .75rem; min-height: 48px; border: 1px solid #888; border-radius: .4rem; width: 100%; box-sizing: border-box; }
  .sign label.agree { display: flex; gap: .7rem; align-items: flex-start; min-height: 44px; }
  .sign label.agree input { width: 1.4rem; height: 1.4rem; margin: .15rem 0 0; flex: none; }
  .sign button { font: inherit; font-size: 1.1rem; font-weight: 600; min-height: 50px; border: 0; border-radius: .4rem; background: var(--accent, #1d1d1f); color: #fff; cursor: pointer; }
  .sign .plain { font-size: .9rem; color: #555; }
  .sign .done { border-left: 4px solid var(--accent, #1d1d1f); padding: .5rem 0 .5rem 1rem; margin: 1.25rem 0; }
  .sign code { word-break: break-all; overflow-wrap: anywhere; }
  .sign .err { color: #a40000; font-weight: 600; }
  @media print { .sign form, .sign .noprint { display: none; } }
</style>`;

function shell(env, title, body, status = 200) {
  const site = env.SITE_NAME || "";
  return new Response(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title>${esc(title)}${site ? ` — ${esc(site)}` : ""}</title>
  <link rel="stylesheet" href="/css/style.css">
  ${STYLE}
</head>
<body>
<main class="sign">
${body}
</main>
</body>
</html>`, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex",
      // same-origin, not no-referrer: with no-referrer the browser posts the form with
      // "Origin: null", and the same-site check below would refuse every real signature
      "referrer-policy": "same-origin", "x-frame-options": "DENY",
    },
  });
}

function sorry(env, msg, status = 404) {
  const site = env.SITE_NAME ? esc(env.SITE_NAME) : "the business that sent it";
  return shell(env, "This link", `<h1>This link doesn't open a document</h1><p>${esc(msg)}</p><p>Ask ${site} for a new link.</p>`, status);
}

// "2026-10-05T22:31:07Z" -> "Mon, Oct 5, 2026, 4:31 PM MDT" in the site's zone
function shownTime(iso, env) {
  const d = new Date(iso);
  if (isNaN(d)) return String(iso || "");
  return new Intl.DateTimeFormat("en-US", {
    timeZone: env.TIMEZONE || "America/Denver", weekday: "short", month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit", timeZoneName: "short",
  }).format(d);
}

async function load(env, token) {
  if (!TOKEN.test(token || "")) return null;
  return env.DB.prepare("SELECT * FROM signatures WHERE token = ?").bind(token).first();
}

function plainLine(env) {
  const site = env.SITE_NAME ? esc(env.SITE_NAME) : "the business";
  return `<p class="plain">Signing here records the name you type, the time, your internet (IP) address and this exact text, and ${site} keeps that record. It is your agreement in writing, not a notarised signature.</p>`;
}

function show(env, s, { error = "", typed = "" } = {}) {
  const site = env.SITE_NAME ? esc(env.SITE_NAME) : "";
  const head = `<h1>${esc(s.title)}</h1><p class="for">For ${esc(s.for_name)}${site ? `, from ${site}` : ""}</p>`;
  const doc = `<div class="doc">${s.body_html}</div>`;
  if (s.status === "void") return shell(env, s.title, `${head}<p class="done">${site || "The business"} withdrew this document, so it can't be signed here. Ask them if you expected to sign it.</p>`);
  if (s.status === "signed") {
    return shell(env, s.title, `${head}<div class="done"><p><strong>Signed by ${esc(s.signed_name)}</strong><br>${esc(shownTime(s.signed_at, env))}</p>
      <p class="plain">Text fingerprint (SHA-256): <code>${esc(s.signed_sha256)}</code></p>
      <p class="plain noprint">${site || "The business"} has the signed record. You can print or save this page as your own copy.</p></div>${doc}`);
  }
  return shell(env, s.title, `${head}${doc}
    <form method="post">
      ${error ? `<p class="err" role="alert">${esc(error)}</p>` : ""}
      <label class="name">Your full name
        <input type="text" name="full_name" autocomplete="name" required minlength="2" maxlength="${NAME_MAX}" value="${esc(typed)}">
      </label>
      <label class="agree"><input type="checkbox" name="agree" value="yes" required> <span>I have read this and I agree to it.</span></label>
      <button type="submit">Sign</button>
    </form>
    ${plainLine(env)}`);
}

export async function onRequestGet({ env, params }) {
  if (!env.DB) return sorry(env, "This site isn't set up to take signatures yet.", 503);
  const s = await load(env, params.token);
  if (!s) return sorry(env, "This link isn't right, or it was mistyped.");
  return show(env, s);
}

export async function onRequestPost({ request, env, params, waitUntil }) {
  if (!env.DB) return sorry(env, "This site isn't set up to take signatures yet.", 503);
  const s = await load(env, params.token);
  if (!s) return sorry(env, "This link isn't right, or it was mistyped.");
  if (s.status !== "sent") return show(env, s);
  if (!sameOrigin(request)) return sorry(env, "That came from another site, so nothing was signed.", 403);
  const data = await readBody(request);
  const typed = String(data.full_name || "").replace(/\s+/g, " ").trim().slice(0, NAME_MAX);
  if (typed.length < 2 || !/\p{L}/u.test(typed)) return show(env, s, { error: "Type your full name to sign.", typed });
  if (!data.agree) return show(env, s, { error: "Tick the box to say you've read it and agree.", typed });

  // the text as it stands now must be the text that was sent: a row changed
  // after sending is never signed, the business sends a new link instead
  const hash = await sha256(s.body);
  if (hash !== s.doc_sha256) return sorry(env, "This document changed after it was sent, so it can't be signed from this link.", 409);

  const at = new Date().toISOString().slice(0, 19) + "Z";
  const ip = request.headers.get("cf-connecting-ip") || "";
  const agent = (request.headers.get("user-agent") || "").slice(0, 300);
  const r = await env.DB.prepare(
    "UPDATE signatures SET status = 'signed', signed_name = ?, signed_at = ?, signed_ip = ?, signed_agent = ?, signed_sha256 = ?, " +
    "updated_at = ? WHERE id = ? AND status = 'sent'"
  ).bind(typed, at, ip, agent, hash, at, s.id).run();
  const signed = await env.DB.prepare("SELECT * FROM signatures WHERE id = ?").bind(s.id).first();
  if (!r.meta || !r.meta.changes) return show(env, signed);       // signed a moment ago in another tab

  // tell the owner the way a form on the site does (patchlamp.com mails them)
  if (env.PATCHLAMP_SLUG && env.FORWARD_EMAIL !== "off") {
    const base = (env.PATCHLAMP_URL || "https://patchlamp.com").replace(/\/$/, "");
    const origin = env.MAIL_ORIGIN || new URL(request.url).origin;
    const fields = {
      name: typed, document: s.title, sent_to: s.for_name, signed_at: `${shownTime(at, env)} (${at})`,
      sha256: hash, message: `${typed} signed "${s.title}". The record is on /admin/signatures; Patch makes the PDF.`,
    };
    if (s.email) fields.email = s.email;
    const fwd = fetch(`${base}/f/${encodeURIComponent(env.PATCHLAMP_SLUG)}/signature`, {
      method: "POST", body: new URLSearchParams(fields),
      headers: { origin, referer: `${origin}/`, accept: "application/json", "content-type": "application/x-www-form-urlencoded" },
    }).then((x) => { if (!x.ok) console.error(`forward: patchlamp.com answered ${x.status}`); })
      .catch((e) => console.error(`forward: ${e}`));
    if (waitUntil) waitUntil(fwd);
  }
  // back to the same page by GET, so a refresh doesn't post again
  return new Response(null, { status: 303, headers: { location: new URL(request.url).pathname, "cache-control": "no-store" } });
}
