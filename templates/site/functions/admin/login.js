// POST /admin/login — if the address is the owner's, a one-time link goes to
// it by email (through patchlamp.com); the answer is the same either way.
import { now, randomHex, sha256, readBody, sendSignInLink, TOKEN_MINUTES, esc } from "../_lib/core.js";
import { signInForm } from "./index.js";

export async function onRequestPost({ request, env }) {
  const body = await readBody(request);
  const email = String(body.email || "").trim().toLowerCase();
  const owner = String(env.ADMIN_EMAIL || "").trim().toLowerCase();
  if (owner && email === owner) {
    const t = now();
    const recent = await env.DB.prepare("SELECT COUNT(*) AS n FROM admin_tokens WHERE created_at > ?").bind(t - TOKEN_MINUTES * 60).first();
    if (recent.n < 5) {
      const token = randomHex(32);
      await env.DB.batch([
        env.DB.prepare("DELETE FROM admin_tokens WHERE expires_at < ?").bind(t - 86400),
        env.DB.prepare("INSERT INTO admin_tokens (token_hash, email, created_at, expires_at) VALUES (?, ?, ?, ?)")
          .bind(await sha256(token), owner, t, t + TOKEN_MINUTES * 60),
      ]);
      const link = `${new URL(request.url).origin}/admin/verify?token=${token}`;
      await sendSignInLink(env, request, link);
    }
  }
  return signInForm(env, `<p><strong>If ${esc(email || "that")} is the owner's address, a sign-in link is on its way.</strong>
    Open it on this device within ${TOKEN_MINUTES} minutes.</p>`);
}
