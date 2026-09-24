// /admin/verify?token=… — the link from the email. GET shows a button and
// changes nothing (mail scanners open links); the POST spends the token once
// and starts the session.
import { page, esc, now, sha256, startSession, readBody, redirect } from "../_lib/core.js";

const expired = (env) => page(env, "Link expired", `<h1>That link has expired</h1>
  <p>Sign-in links work once, for 15 minutes. <a href="/admin">Ask for a new one.</a></p>`, { status: 410 });

async function live(env, token) {
  if (!/^[0-9a-f]{64}$/.test(token || "")) return null;
  const row = await env.DB.prepare("SELECT token_hash, email, expires_at, used_at FROM admin_tokens WHERE token_hash = ?")
    .bind(await sha256(token)).first();
  return row && !row.used_at && row.expires_at >= now() ? row : null;
}

export async function onRequestGet({ request, env }) {
  const token = new URL(request.url).searchParams.get("token");
  if (!(await live(env, token))) return expired(env);
  return page(env, "Sign in", `<h1>Sign in</h1>
    <form class="sign-in" method="post" action="/admin/verify">
      <input type="hidden" name="token" value="${esc(token)}">
      <button type="submit">Sign in to the admin page</button>
    </form>`);
}

export async function onRequestPost({ request, env }) {
  const token = String((await readBody(request)).token || "");
  const row = await live(env, token);
  if (!row) return expired(env);
  const spent = await env.DB.prepare("UPDATE admin_tokens SET used_at = ? WHERE token_hash = ? AND used_at IS NULL")
    .bind(now(), row.token_hash).run();
  if (!spent.meta || spent.meta.changes !== 1) return expired(env);
  return redirect("/admin", { "set-cookie": await startSession(env, row.email) });
}
