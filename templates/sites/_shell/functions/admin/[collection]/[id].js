// /admin/<collection>/<id> — one entry: every column, the JSON column spelled
// out, and the fields the view lets the owner change.
import { page, esc, ident, when, money, readBody, redirect } from "../../_lib/core.js";
import { view, where, input, editFields } from "./index.js";

async function load(env, v, id) {
  const w = where(v, [["id", id]]);
  return env.DB.prepare(`SELECT * FROM ${ident(v.table)}${w.sql}`).bind(...w.args).first();
}

export async function onRequestGet({ env, params, data }) {
  const v = view(params.collection);
  const id = parseInt(params.id, 10);
  const row = v && id ? await load(env, v, id) : null;
  if (!row) return page(env, "Not found", "<h1>Not found</h1>", { status: 404, session: data.session });
  const dl = [];
  for (const [k, val] of Object.entries(row)) {
    if (k === v.json || k === "ip_hash" || val === null || val === "") continue;
    const shown = /_at$/.test(k) ? when(val, env) : /_cents$/.test(k) ? money(val) : val;
    dl.push(`<dt>${esc(k.replace(/_cents$/, "").replace(/_/g, " "))}</dt><dd>${esc(shown)}</dd>`);
  }
  if (v.json && row[v.json]) {
    let obj = {};
    try { obj = JSON.parse(row[v.json]); } catch (_) { obj = { [v.json]: row[v.json] }; }
    for (const [k, val] of Object.entries(obj)) if (row[k] !== val) dl.push(`<dt>${esc(k.replace(/[_-]/g, " "))}</dt><dd>${esc(typeof val === "string" ? val : JSON.stringify(val))}</dd>`);
  }
  // one tap to change the status ("done", "skipped"), above the full form
  const taps = (v.quick || editFields(v).some((f) => f.name === "status") && v.statuses || []).filter((st) => st !== row.status);
  const quick = taps.length && row.status !== undefined ? `<div class="quick-row">${taps.map((st) =>
    `<form class="quick" method="post"><input type="hidden" name="status" value="${esc(st)}"><button type="submit">Mark ${esc(st)}</button></form>`).join("")}</div>` : "";
  const edit = editFields(v).length
    ? `<h2>Update</h2><form class="edit" method="post">${editFields(v).map((f) => input(f, row[f.name] ?? "", v)).join("")}<button type="submit">Save</button></form>` : "";
  return page(env, `${v.singular || "Entry"} #${id}`, `<p><a href="/admin/${esc(params.collection)}">← ${esc(v.title)}</a></p>
    <h1>${esc(v.singular ? v.singular[0].toUpperCase() + v.singular.slice(1) : "Entry")} #${id}</h1>
    ${quick}<dl>${dl.join("")}</dl>${edit}`, { session: data.session });
}

export async function onRequestPost({ request, env, params, data }) {
  const v = view(params.collection);
  const id = parseInt(params.id, 10);
  const fields = v ? editFields(v) : [];
  if (v && (v.quick || []).length && !fields.some((f) => f.name === "status")) fields.push({ name: "status", type: "select", options: v.quick });
  if (!v || !id || !fields.length || !(await load(env, v, id))) {
    return page(env, "Not found", "<h1>Not found</h1>", { status: 404, session: data.session });
  }
  const body = await readBody(request);
  const sets = [], args = [];
  for (const f of fields) {
    if (!(f.name in body)) continue;
    let val = String(body[f.name]).trim().slice(0, 5000);
    if (f.type === "select" && !(f.options || v.statuses || []).includes(val)) continue;
    sets.push(`${ident(f.name)} = ?`); args.push(val);
  }
  if (v.touch) sets.push(`${ident(v.touch)} = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')`);
  if (sets.length) await env.DB.prepare(`UPDATE ${ident(v.table)} SET ${sets.join(", ")} WHERE id = ?`).bind(...args, id).run();
  // a one-tap button on the list comes back to the list it was on (this list only)
  const back = String(body.back || "");
  const list = `/admin/${params.collection}`;
  return redirect(back === list || back.startsWith(list + "?") ? back : `${list}/${id}`);
}
