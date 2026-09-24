// /admin/<collection> — one list, newest first, 50 to a page; and (when the
// view allows it) a form to add an entry.
import { page, esc, ident, when, readBody, redirect } from "../../_lib/core.js";
import collections from "../../_admin/collections.js";

const PER_PAGE = 50;

export function view(name) {
  return Object.prototype.hasOwnProperty.call(collections, name) ? collections[name] : null;
}

export function where(v, extra = []) {
  const parts = Object.keys(v.filter || {}).map((k) => `${ident(k)} = ?`).concat(extra.map(([k]) => `${ident(k)} = ?`));
  return { sql: parts.length ? ` WHERE ${parts.join(" AND ")}` : "", args: Object.values(v.filter || {}).concat(extra.map(([, x]) => x)) };
}

export function input(f, value = "", v = {}) {
  const label = esc(f.label || f.name);
  if (f.type === "select") {
    const opts = (f.options || v.statuses || []).map((o) => `<option${o === value ? " selected" : ""}>${esc(o)}</option>`).join("");
    return `<label>${label} <select name="${esc(f.name)}">${opts}</select></label>`;
  }
  if (f.type === "textarea") return `<label>${label} <textarea name="${esc(f.name)}">${esc(value)}</textarea></label>`;
  return `<label>${label} <input name="${esc(f.name)}" type="${esc(f.type || "text")}" value="${esc(value)}"${f.required ? " required" : ""}></label>`;
}

function cell(v, col, value, env) {
  if (/_at$/.test(col)) return esc(when(value, env));
  if (col === "status") return `<span class="status">${esc(value)}</span>`;
  const s = String(value ?? "");
  return esc(s.length > 80 ? s.slice(0, 80) + "…" : s);
}

export async function onRequestGet({ request, env, params, data }) {
  const v = view(params.collection);
  if (!v) return page(env, "Not found", "<h1>No such list</h1>", { status: 404, session: data.session });
  const url = new URL(request.url);
  const n = Math.max(1, parseInt(url.searchParams.get("page") || "1", 10) || 1);
  const status = url.searchParams.get("status");
  const w = where(v, status && (v.statuses || []).includes(status) ? [["status", status]] : []);
  const cols = ["id", ...v.list.map(([c]) => c)].map(ident);
  const rows = (await env.DB.prepare(`SELECT ${cols.join(", ")} FROM ${ident(v.table)}${w.sql} ORDER BY id DESC LIMIT ? OFFSET ?`)
    .bind(...w.args, PER_PAGE + 1, (n - 1) * PER_PAGE).all()).results || [];
  const more = rows.length > PER_PAGE;
  const shown = rows.slice(0, PER_PAGE);
  const head = v.list.map(([, label]) => `<th scope="col">${esc(label)}</th>`).join("");
  const body = shown.map((r) => `<tr>${v.list.map(([c], i) => `<td>${i === 0 ? `<a href="/admin/${esc(params.collection)}/${r.id}">${cell(v, c, r[c], env) || "#" + r.id}</a>` : cell(v, c, r[c], env)}</td>`).join("")}</tr>`).join("");
  const filters = (v.statuses || []).length
    ? `<p class="note">Show: <a href="?">all</a> ${v.statuses.map((s) => `· <a href="?status=${esc(s)}">${esc(s)}</a>`).join(" ")}</p>` : "";
  const pager = `<p class="pager">${n > 1 ? `<a href="?page=${n - 1}${status ? `&status=${esc(status)}` : ""}">Newer</a>` : ""}${more ? `<a href="?page=${n + 1}${status ? `&status=${esc(status)}` : ""}">Older</a>` : ""}</p>`;
  const create = v.create
    ? `<h2>Add ${esc(v.singular || "an entry")}</h2><form class="edit" method="post">${v.create.map((f) => input(f, f.default || "", v)).join("")}<button type="submit">Add</button></form>` : "";
  return page(env, v.title, `<h1>${esc(v.title)}</h1>${filters}
    ${shown.length ? `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${pager}`
      : `<p>Nothing here yet${status ? ` marked ${esc(status)}` : ""}.</p>`}
    ${create}`, { session: data.session });
}

export async function onRequestPost({ request, env, params, data }) {
  const v = view(params.collection);
  if (!v || !v.create) return page(env, "Not found", "<h1>No such list</h1>", { status: 404, session: data.session });
  const body = await readBody(request);
  const cols = [], args = [];
  for (const f of v.create) {
    const val = String(body[f.name] ?? "").trim().slice(0, 5000);
    if (f.required && !val) return page(env, "Missing", `<h1>${esc(f.label || f.name)} is needed</h1><p><a href="/admin/${esc(params.collection)}">Back</a></p>`, { status: 422, session: data.session });
    cols.push(ident(f.name)); args.push(val);
  }
  for (const [k, x] of Object.entries(v.filter || {})) { cols.push(ident(k)); args.push(x); }
  const r = await env.DB.prepare(`INSERT INTO ${ident(v.table)} (${cols.join(", ")}) VALUES (${cols.map(() => "?").join(", ")})`).bind(...args).run();
  return redirect(`/admin/${params.collection}/${r.meta.last_row_id}`);
}
