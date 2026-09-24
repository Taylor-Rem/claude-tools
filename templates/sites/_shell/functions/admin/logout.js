// /admin/logout — ends this session (the cookie and its row).
import { endSession, redirect } from "../_lib/core.js";

export async function onRequest({ request, env }) {
  return redirect("/admin", { "set-cookie": await endSession(request, env) });
}
