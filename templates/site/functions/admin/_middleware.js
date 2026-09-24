// Every /admin/* request passes through here: the owner's session is read
// once, and everything but the sign-in pages needs one.
import { page, readSession, redirect, sameOrigin, notSetUp, esc } from "../_lib/core.js";

const OPEN = new Set(["/admin", "/admin/", "/admin/login", "/admin/verify", "/admin/logout"]);

export async function onRequest(ctx) {
  const { request, env } = ctx;
  const missing = notSetUp(env);
  if (missing) {
    return page(env, "Not set up", `<h1>Not set up yet</h1>
      <p class="note">This site's admin page is missing ${esc(missing.join(", "))}. Patch sets it up with <code>site data</code>.</p>`, { status: 503 });
  }
  if (request.method === "POST" && !sameOrigin(request)) {
    return page(env, "Refused", "<h1>Refused</h1><p>That form came from another site.</p>", { status: 403 });
  }
  const url = new URL(request.url);
  ctx.data.session = await readSession(request, env);
  if (!ctx.data.session && !OPEN.has(url.pathname)) return redirect("/admin");
  return ctx.next();
}
