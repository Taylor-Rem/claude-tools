// /admin/jobs/<id> — the shell's entry page for a job; marking it done here
// (or with the list's one-tap "done") also moves the customer's last_seen to
// the job's date, so "who haven't I seen in 90 days" stays right.
import { onRequestGet as show, onRequestPost as save } from "../[collection]/[id].js";
import { markDone } from "../../_lib/customers.js";

export function onRequestGet(ctx) {
  return show({ ...ctx, params: { ...ctx.params, collection: "jobs" } });
}

export async function onRequestPost(ctx) {
  const c = { ...ctx, params: { ...ctx.params, collection: "jobs" } };
  const body = await ctx.request.clone().formData().catch(() => null);
  const res = await save(c);
  const id = parseInt(ctx.params.id, 10);
  if (id && body && body.get("status") === "done") await markDone(ctx.env, id);
  return res;
}
