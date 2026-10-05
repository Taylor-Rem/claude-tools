// /admin/customers — the shell's list (search, sort, Download CSV), with an
// "Import a CSV" link beside the download, and an add form that matches by
// phone or email: adding someone already in the book opens their page
// instead of making a second record.
import { onRequestGet as list } from "../[collection]/index.js";
import { page, esc, readBody, redirect } from "../../_lib/core.js";
import { recordCustomer } from "../../_lib/customers.js";

export async function onRequestGet(ctx) {
  const res = await list({ ...ctx, params: { ...ctx.params, collection: "customers" } });
  if (res.status !== 200 || !(res.headers.get("content-type") || "").startsWith("text/html")) return res;
  const html = (await res.text()).replace("download>Download CSV</a>",
    'download>Download CSV</a>\n      <a href="/admin/customers/import">Import a CSV</a>');
  return new Response(html, { status: res.status, headers: res.headers });
}

export async function onRequestPost({ request, env, data }) {
  const b = await readBody(request);
  const v = (k) => String(b[k] ?? "").trim().slice(0, 5000);
  if (!v("name")) return page(env, "Missing", `<h1>A name is needed</h1><p><a href="/admin/customers">Back</a></p>`, { status: 422, session: data.session });
  const r = await recordCustomer(env, { name: v("name"), phone: v("phone"), email: v("email"), address: v("address"),
    tags: v("tags"), notes: v("notes"), source: "admin", seen: false });
  if (!r) return page(env, "Not set up", `<h1>The customer book isn't set up</h1><p>${esc("Patch adds it with db add customers.")}</p>`, { status: 503, session: data.session });
  return redirect(`/admin/customers/${r.id}`);
}
