// /admin/<collection> — one list: a search box, a status filter (and the
// view's own choosers), a totals line, sort by any column, the rows shown as
// a CSV, 50 to a page; and (when the view allows it) a form to add an entry.
//
// A view is a descriptor in functions/_admin/<name>.js, registered in
// functions/_admin/collections.js. The shell does the work; a view says:
//   table, title, singular, plural     where the rows are, what one is called ("stop", "stops")
//   list: [[column, label], …]         the columns shown; the first links to the entry
//   statuses: [...]                    the filter pills and the counts on the totals line
//   filter: { column: value }          a fixed slice of a shared table (records, kind = "customer")
//   filters: [[column, label, "today"?], …]  a chooser per column, its values from the rows
//                                      (a route's day); "today" starts it on today when there is one
//   search: [columns]                  where the search box looks (default: the listed columns and `json`)
//   sum: [column, …]                   added up on the totals line; a *_cents column is money
//   order: [column, "asc" | "desc"]    the default sort (default: newest first); more than one
//                                      column is [[column, dir], [column, dir]] (a day, then the stop)
//   shortcuts: [[label, "SQL"], …]     a named slice as a pill ("below reorder", "on_hand < reorder_at");
//                                      the SQL is this file's, never anything a visitor typed
//   quick: ["done", …]                 one-tap status buttons on each row
//   json, create, edit, touch          the JSON column, the add form, the edit form, the "changed" column
// Anything the owner sees here, `db export` hands over as the same rows.
import { page, esc, ident, when, ago, isDate, money, csv, readBody, redirect, localNow } from "../../_lib/core.js";
import collections from "../../_admin/collections.js";

const PER_PAGE = 50;
const CSV_MAX = 10000;

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

export const plural = (v) => v.plural || (v.singular ? (/s$/.test(v.singular) ? v.singular : v.singular + "s") : "entries");
const isMoney = (col) => /_cents$/.test(col);

export function cell(col, value, env) {
  if (value === null || value === undefined || value === "") return "";
  if (/_at$/.test(col) || isDate(value)) return `<time title="${esc(when(value, env))}">${esc(ago(value, env))}</time>`;
  if (col === "status") return `<span class="status">${esc(value)}</span>`;
  if (isMoney(col)) return esc(money(value));
  const s = String(value);
  return esc(s.length > 80 ? s.slice(0, 80) + "…" : s);
}

// What the page was asked for: the search, the status, the choosers, the sort.
export function state(v, url, choices = {}) {
  const p = url.searchParams;
  const cols = v.list.map(([c]) => c);
  const status = p.get("status") && (v.statuses || []).includes(p.get("status")) ? p.get("status") : "";
  const picked = {};
  for (const [col, , start] of v.filters || []) {
    if (p.has(col)) picked[col] = p.get(col);
    else if (start === "today") {
      const today = localNow({ TIMEZONE: choices.tz }).slice(0, 10);
      picked[col] = (choices[col] || []).includes(today) ? today : "";
    } else picked[col] = "";
  }
  const [[defCol, defDir], ...then] = orders(v);
  const [byCol, byDir] = (p.get("sortby") || "").split(" ");          // the phone's sort chooser: "day asc"
  const want = byCol || p.get("sort"), wantDir = byCol ? byDir : p.get("dir");
  const sort = cols.includes(want) || want === "id" ? want : defCol;
  const dir = ["asc", "desc"].includes(wantDir) ? wantDir : (sort !== defCol ? "asc" : defDir || "desc");
  const only = (v.shortcuts || []).some(([label]) => label === p.get("only")) ? p.get("only") : "";
  return { q: (p.get("q") || "").trim().slice(0, 100), status, picked, only, sort, dir, then, usual: sort === defCol && dir === (defDir || "desc"), n: Math.max(1, parseInt(p.get("page") || "1", 10) || 1) };
}

// The default sort as [[column, dir], …].
export function orders(v) {
  const o = v.order || ["id", "desc"];
  return (Array.isArray(o[0]) ? o : [o]).map(([c, d]) => [c, d === "asc" ? "asc" : "desc"]);
}

// The WHERE for a state: the view's slice, the choosers, the search, and
// (unless leaving it out for the totals) the status.
export function conditions(v, s, withStatus = true) {
  const parts = [], args = [];
  for (const [k, x] of Object.entries(v.filter || {})) { parts.push(`${ident(k)} = ?`); args.push(x); }
  for (const [k, x] of Object.entries(s.picked)) if (x !== "") { parts.push(`${ident(k)} = ?`); args.push(x); }
  if (withStatus && s.status) { parts.push("status = ?"); args.push(s.status); }
  if (s.only) parts.push(`(${(v.shortcuts || []).find(([label]) => label === s.only)[1]})`);
  if (s.q) {
    const cols = [...new Set(v.search || [...v.list.map(([c]) => c).filter((c) => !/_at$/.test(c) && !isMoney(c)), ...(v.json ? [v.json] : [])])];
    const like = "%" + s.q.replace(/[\\%_]/g, (c) => "\\" + c) + "%";
    parts.push("(" + cols.map((c) => `${ident(c)} LIKE ? ESCAPE '\\'`).join(" OR ") + ")");
    args.push(...cols.map(() => like));
  }
  return { sql: parts.length ? ` WHERE ${parts.join(" AND ")}` : "", args };
}

function link(name, s, change = {}) {
  const next = { q: s.q, status: s.status, only: s.only, ...s.picked, ...(s.usual ? {} : { sort: s.sort, dir: s.dir }), ...change };
  const qs = new URLSearchParams();
  for (const [k, x] of Object.entries(next)) if (x !== "" && x !== undefined && x !== null && !(k === "page" && x === 1)) qs.set(k, x);
  if ("page" in change && change.page > 1) qs.set("page", change.page);
  const str = qs.toString();
  return `/admin/${name}${str ? "?" + str : ""}`;
}

// The totals line: "12 stops · 9 done · 2 skipped · 1 to do", and the sums.
export async function totals(env, v, s) {
  const sums = (v.sum || []).filter((c) => v.list.some(([x]) => x === c) || isMoney(c));
  const w = conditions(v, s, false);
  const sel = ["COUNT(*) AS n", ...sums.map((c, i) => `SUM(${ident(c)}) AS s${i}`)];
  const grouped = (v.statuses || []).length;
  const rows = (await env.DB.prepare(`SELECT ${grouped ? "status, " : ""}${sel.join(", ")} FROM ${ident(v.table)}${w.sql}${grouped ? " GROUP BY status" : ""}`)
    .bind(...w.args).all()).results || [];
  const by = Object.fromEntries(rows.map((r) => [grouped ? r.status : "", r]));
  const all = rows.reduce((a, r) => a + r.n, 0);
  const inView = s.status ? [by[s.status] || { n: 0 }] : rows;
  const sumOf = (i) => inView.reduce((a, r) => a + (Number(r[`s${i}`]) || 0), 0);
  const label = (c) => (v.list.find(([x]) => x === c) || [c, c.replace(/_cents$/, "").replace(/_/g, " ")])[1].replace(/\s*\(cents\)/i, "");
  const counts = grouped ? v.statuses.filter((st) => by[st]).map((st) => `${by[st].n} ${st}`) : [];
  const text = [`${all} ${all === 1 ? (v.singular || "entry") : plural(v)}`, ...counts].join(" · ")
    + sums.map((c, i) => ` · ${label(c)}${s.status ? ` (${s.status})` : ""}: ${isMoney(c) ? money(sumOf(i)) : sumOf(i).toLocaleString("en-US")}`).join("");
  return { text, by, all };
}

export async function onRequestGet({ request, env, params, data }) {
  const name = params.collection;
  const v = view(name);
  if (!v) return page(env, "Not found", "<h1>No such list</h1>", { status: 404, session: data.session });
  const url = new URL(request.url);
  const base = where(v);
  const choices = { tz: env.TIMEZONE };
  for (const [col] of v.filters || []) {
    choices[col] = ((await env.DB.prepare(`SELECT DISTINCT ${ident(col)} AS x FROM ${ident(v.table)}${base.sql} ORDER BY 1 LIMIT 100`)
      .bind(...base.args).all()).results || []).map((r) => r.x).filter((x) => x !== null && x !== "").map(String);
  }
  const s = state(v, url, choices);
  const w = conditions(v, s);
  const order = " ORDER BY " + [[s.sort, s.dir], ...(s.usual ? s.then : []), ...(s.sort === "id" ? [] : [["id", "desc"]])]
    .map(([c, d]) => `${ident(c)} ${d === "asc" ? "ASC" : "DESC"}`).join(", ");

  if (url.searchParams.get("format") === "csv") {
    const rows = (await env.DB.prepare(`SELECT * FROM ${ident(v.table)}${w.sql}${order} LIMIT ${CSV_MAX}`).bind(...w.args).all()).results || [];
    const cols = rows.length ? Object.keys(rows[0]) : ["id", ...v.list.map(([c]) => c)];
    const file = `${name}-${localNow(env).slice(0, 10)}.csv`;
    return new Response(csv(rows, cols), { headers: {
      "content-type": "text/csv; charset=utf-8", "content-disposition": `attachment; filename="${file}"`,
      "cache-control": "no-store", "x-robots-tag": "noindex" } });
  }

  const cols = [...new Set(["id", ...v.list.map(([c]) => c), ...((v.quick || []).length ? ["status"] : [])])].map(ident);
  const rows = (await env.DB.prepare(`SELECT ${cols.join(", ")} FROM ${ident(v.table)}${w.sql}${order} LIMIT ? OFFSET ?`)
    .bind(...w.args, PER_PAGE + 1, (s.n - 1) * PER_PAGE).all()).results || [];
  const more = rows.length > PER_PAGE;
  const shown = rows.slice(0, PER_PAGE);
  const t = await totals(env, v, s);
  const here = link(name, s, { page: s.n });

  const head = v.list.map(([c, label]) => {
    const on = s.sort === c;
    const dir = on && s.dir === "asc" ? "desc" : "asc";
    return `<th scope="col"${on ? ` aria-sort="${s.dir === "asc" ? "ascending" : "descending"}"` : ""}${isMoney(c) ? ' class="num"' : ""}><a href="${esc(link(name, s, { sort: c, dir }))}">${esc(label)}${on ? (s.dir === "asc" ? " ↑" : " ↓") : ""}</a></th>`;
  }).join("") + ((v.quick || []).length ? '<th scope="col"><span class="note">Mark</span></th>' : "");
  const quick = (r) => (v.quick || []).filter((st) => st !== r.status).map((st) =>
    `<form class="quick" method="post" action="/admin/${esc(name)}/${r.id}"><input type="hidden" name="status" value="${esc(st)}"><input type="hidden" name="back" value="${esc(here)}"><button type="submit">${esc(st)}</button></form>`).join(" ");
  const body = shown.map((r) => `<tr>${v.list.map(([c, label], i) => `<td data-label="${esc(label)}"${isMoney(c) ? ' class="num"' : ""}>${i === 0
    ? `<a href="/admin/${esc(name)}/${r.id}">${cell(c, r[c], env) || "#" + r.id}</a>` : cell(c, r[c], env)}</td>`).join("")}${(v.quick || []).length ? `<td class="quick-cell">${quick(r)}</td>` : ""}</tr>`).join("");

  const cuts = [];
  for (const [label] of v.shortcuts || []) {
    const c = conditions(v, { ...s, only: label, status: "" });
    cuts.push([label, (await env.DB.prepare(`SELECT COUNT(*) AS n FROM ${ident(v.table)}${c.sql}`).bind(...c.args).first()).n]);
  }
  const pill = (href, on, label, n) => `<li><a href="${esc(href)}"${on ? ' aria-current="true"' : ""}>${esc(label)} <span>${n}</span></a></li>`;
  const pills = (v.statuses || []).length || cuts.length ? `<ul class="pills">
      ${(v.statuses || []).length ? pill(link(name, s, { status: "" }), !s.status, "all", t.all) : ""}
      ${(v.statuses || []).map((st) => pill(link(name, s, { status: st }), s.status === st, st, (t.by[st] || {}).n || 0)).join("")}
      ${cuts.map(([label, n]) => pill(link(name, s, { only: s.only === label ? "" : label, status: "" }), s.only === label, label, n)).join("")}
    </ul>` : "";
  const choosers = (v.filters || []).map(([col, label]) => `<label>${esc(label)} <select name="${esc(col)}">
      <option value="">all</option>${choices[col].map((x) => `<option value="${esc(x)}"${s.picked[col] === x ? " selected" : ""}>${esc(isDate(x) ? ago(x, env) : x)}</option>`).join("")}
    </select></label>`).join("");
  const sortPick = `<label class="phone-only">Sort <select name="sortby"><option value="">${v.order ? "the usual order" : "newest first"}</option>${v.list.flatMap(([c, label]) => [["asc", "↑"], ["desc", "↓"]].map(([d, arrow]) =>
    `<option value="${esc(c)} ${d}"${s.sort === c && s.dir === d ? " selected" : ""}>${esc(label)} ${arrow}</option>`)).join("")}</select></label>`;
  const find = `<form class="find" method="get" action="/admin/${esc(name)}" role="search">
      <input type="search" name="q" value="${esc(s.q)}" placeholder="Search ${esc(plural(v))}" aria-label="Search ${esc(plural(v))}">
      ${choosers}${sortPick}
      ${s.status ? `<input type="hidden" name="status" value="${esc(s.status)}">` : ""}${s.only ? `<input type="hidden" name="only" value="${esc(s.only)}">` : ""}
      <button type="submit">Search</button>
    </form>`;
  const actions = `<p class="actions"><span class="totals">${esc(t.text)}</span>
      <a href="${esc(link(name, s, { format: "csv" }))}" download>Download CSV</a>
      ${s.q || s.status || s.only ? `<a href="/admin/${esc(name)}">Clear</a>` : ""}</p>`;
  const pager = `<p class="pager">${s.n > 1 ? `<a href="${esc(link(name, s, { page: s.n - 1 }))}">Previous 50</a>` : ""}${more ? `<a href="${esc(link(name, s, { page: s.n + 1 }))}">Next 50</a>` : ""}</p>`;
  const create = v.create
    ? `<h2>Add ${esc(v.singular || "an entry")}</h2><form class="edit" method="post">${v.create.map((f) => input(f, f.default || "", v)).join("")}<button type="submit">Add</button></form>` : "";
  const nothing = s.q || s.status || s.only || Object.values(s.picked).some((x) => x)
    ? `<p>No ${esc(plural(v))} ${s.q ? `match “${esc(s.q)}”` : "here"}${s.status ? ` marked ${esc(s.status)}` : ""}${s.only ? ` (${esc(s.only)})` : ""}.</p>` : "<p>Nothing here yet.</p>";
  return page(env, v.title, `<h1>${esc(v.title)}</h1>
    <div class="tools">${find}${pills}${actions}</div>
    ${shown.length ? `<div class="table-wrap"><table class="list"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>${pager}` : nothing}
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
