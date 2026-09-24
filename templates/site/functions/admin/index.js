// /admin — the sign-in form, or (signed in) the list of lists.
import { page, esc, ident } from "../_lib/core.js";
import collections from "../_admin/collections.js";

export function signInForm(env, message = "") {
  return page(env, "Sign in", `<h1>Sign in</h1>
    ${message}
    <p class="note">Enter the owner's email address and we'll send a sign-in link. It works once, for 15 minutes.</p>
    <form class="sign-in" method="post" action="/admin/login">
      <label>Email <input type="email" name="email" required autocomplete="email"></label>
      <button type="submit">Email me a link</button>
    </form>`);
}

export async function onRequestGet({ env, data }) {
  if (!data.session) return signInForm(env);
  const names = Object.keys(collections);
  const cards = [];
  for (const name of names) {
    const v = collections[name];
    let n = "?";
    try {
      const row = await env.DB.prepare(`SELECT COUNT(*) AS n FROM ${ident(v.table)}${v.filter ? ` WHERE ${Object.keys(v.filter).map((k) => `${ident(k)} = ?`).join(" AND ")}` : ""}`)
        .bind(...Object.values(v.filter || {})).first();
      n = row.n;
    } catch (e) { console.error(e); }
    cards.push(`<li><a href="/admin/${esc(name)}"><strong>${esc(v.title)}</strong><br><span class="note">${esc(n)} ${n === 1 ? "entry" : "entries"}</span></a></li>`);
  }
  return page(env, "Admin", `<h1>${esc(env.SITE_NAME || "Admin")}</h1>
    <p class="note">Signed in as ${esc(data.session.email)}.</p>
    ${cards.length ? `<ul class="cards">${cards.join("")}</ul>` : `<p>Nothing to show yet.</p>`}`, { session: data.session });
}

// HEAD /admin (link checkers, uptime pings): the same answer as GET, no body.
export async function onRequestHead(ctx) {
  const r = await onRequestGet(ctx);
  return new Response(null, { status: r.status, headers: r.headers });
}
