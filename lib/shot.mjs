#!/usr/bin/env node
// shot — a headless browser for Claude: look at a page, check it, measure it.
//
// Driven by bin/shot (a two-line wrapper). Everything runs in a fresh headless
// Chromium (Playwright's bundled build, falling back to the system Chrome).
//
//   shot <target> [opts]                screenshot (default command)
//   shot site <target> [opts]           every same-origin page, desktop + mobile
//   shot check <target> [--all]         QA report: console errors, failed requests,
//                                       broken images/links, overflow, alt text, fonts
//   shot text <target> [--selector S]   visible text (what a reader sees)
//   shot html <target> --selector S     outerHTML of the matching element(s)
//   shot css <target> <selector> [prop ...]   computed styles + box of the matches
//   shot diff <a.png> <b.png> [--out d.png]   pixel diff of two screenshots
//   shot clean [--days N]               delete old files under ./shots
//   shot doctor                         browser present, sandbox mode, deps
//
// <target> is a URL, or a local file/folder (served on a loopback port for the
// run, so relative links and CSS work exactly as on the live site).
//
// Common options (screenshot / site / check / text / html / css):
//   --mobile | --tablet | --desktop     viewport presets (default desktop 1280x800)
//   --width W --height H --dpr N        explicit viewport
//   --dark | --light                    emulate prefers-color-scheme
//   --wait MS                           extra settle time after load (default 300)
//   --wait-for SEL                      wait for a selector before acting
//   --scroll-to SEL                     scroll an element into view first
//   --click SEL  --hover SEL            interact before the shot (repeatable, in order)
//   --type "SEL=text"                   fill an input (repeatable)
//   --js CODE                           run JS in the page before the shot
//   --timeout MS                        navigation timeout (default 30000)
//   --json                              machine-readable output
// Screenshot options:
//   --out PATH        where to write (default shots/<name>-<preset>-<time>.png)
//   --full            whole page, not just the first screen
//   --selector SEL    just that element
//   --all-sizes       desktop + mobile in one run (two files)
//   --jpg             JPEG instead of PNG (smaller for texting)
//
// Sandbox: inside a client workspace (a folder with .client.json) or with
// SHOT_SANDBOX=1, targets and outputs must stay inside the workspace, and the
// browser may not reach loopback/private addresses (other than the server
// shot itself starts). Public URLs are fine.

import fs from "node:fs";
import path from "node:path";
import http from "node:http";
import net from "node:net";
import dns from "node:dns/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const CWD = process.cwd();
const SANDBOX = process.env.SHOT_SANDBOX === "1" || fs.existsSync(path.join(CWD, ".client.json"));
const PRESETS = {
  desktop: { width: 1280, height: 800, dpr: 1, mobile: false },
  laptop: { width: 1440, height: 900, dpr: 1, mobile: false },
  tablet: { width: 820, height: 1180, dpr: 2, mobile: true },
  mobile: { width: 390, height: 844, dpr: 2, mobile: true },
};
const DEFAULT_CSS_PROPS = [
  "display", "position", "width", "height", "margin", "padding", "font-family", "font-size",
  "font-weight", "line-height", "letter-spacing", "text-align", "color", "background-color",
  "border", "border-radius", "opacity", "z-index", "overflow", "gap", "flex-direction", "grid-template-columns",
];
const MIME = {
  ".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8", ".json": "application/json",
  ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
  ".svg": "image/svg+xml", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8", ".xml": "application/xml",
  ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf", ".mp3": "audio/mpeg",
  ".mp4": "video/mp4", ".webm": "video/webm", ".pdf": "application/pdf", ".avif": "image/avif",
};

// ------------------------------------------------------------------ args

function usage(code = 0) {
  const src = fs.readFileSync(fileURLToPath(import.meta.url), "utf8");
  const lines = src.split("\n").slice(1).filter((l) => l.startsWith("//")).map((l) => l.slice(3));
  console.log(lines.join("\n").trim());
  process.exit(code);
}

function die(msg, code = 2) {
  console.error(`shot: ${msg}`);
  process.exit(code);
}

const FLAGS_WITH_VALUE = new Set([
  "width", "height", "dpr", "wait", "wait-for", "scroll-to", "click", "hover", "type", "js", "timeout",
  "out", "selector", "days", "max", "depth", "user-agent",
]);
const REPEATABLE = new Set(["click", "hover", "type"]);

function parseArgs(argv) {
  const opts = { _: [], click: [], hover: [], type: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "-h" || a === "--help") usage();
    if (!a.startsWith("--")) { opts._.push(a); continue; }
    let [k, v] = a.slice(2).split(/=(.*)/s);
    if (FLAGS_WITH_VALUE.has(k)) {
      if (v === undefined) v = argv[++i];
      if (v === undefined) die(`--${k} needs a value`);
      if (REPEATABLE.has(k)) opts[k].push(v); else opts[k] = v;
    } else {
      opts[k] = true;
    }
  }
  return opts;
}

function viewportOf(opts) {
  let p = PRESETS.desktop;
  for (const k of Object.keys(PRESETS)) if (opts[k]) p = PRESETS[k];
  const vp = { ...p };
  if (opts.width) vp.width = +opts.width;
  if (opts.height) vp.height = +opts.height;
  if (opts.dpr) vp.dpr = +opts.dpr;
  vp.name = Object.keys(PRESETS).find((k) => opts[k]) || (opts.width || opts.height ? `${vp.width}x${vp.height}` : "desktop");
  return vp;
}

// ------------------------------------------------------------------ sandbox

function inside(p, root) {
  const r = path.resolve(root), q = path.resolve(p);
  return q === r || q.startsWith(r + path.sep);
}

function isPrivateIp(ip) {
  if (net.isIPv4(ip)) {
    const [a, b] = ip.split(".").map(Number);
    return a === 127 || a === 10 || a === 0 || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168)
      || (a === 169 && b === 254) || (a === 100 && b >= 64 && b <= 127);
  }
  const l = ip.toLowerCase();
  return l === "::1" || l === "::" || l.startsWith("fc") || l.startsWith("fd") || l.startsWith("fe80")
    || l.startsWith("::ffff:") && isPrivateIp(l.slice(7));
}

const dnsCache = new Map();
const resolver = new dns.Resolver({ timeout: 1000, tries: 1 });

async function hostIsPrivate(host) {
  host = host.replace(/^\[|\]$/g, "").toLowerCase();
  if (host === "localhost" || host.endsWith(".localhost") || host.endsWith(".local") || host.endsWith(".internal") || host.endsWith(".home")) return true;
  if (net.isIP(host)) return isPrivateIp(host);
  if (!dnsCache.has(host)) {
    // getaddrinfo takes ~5s per host on this box (AAAA timeouts), so ask for A via the
    // fast path and AAAA directly with a short timeout; cache per run.
    dnsCache.set(host, (async () => {
      const [v4, v6] = await Promise.allSettled([
        dns.lookup(host, { all: true, family: 4 }).then((a) => a.map((x) => x.address)),
        resolver.resolve6(host),
      ]);
      const addrs = [...(v4.status === "fulfilled" ? v4.value : []), ...(v6.status === "fulfilled" ? v6.value : [])];
      return addrs.length === 0 || addrs.some(isPrivateIp); // unresolvable: off-limits in the sandbox
    })());
  }
  return dnsCache.get(host);
}

function checkLocalPath(p) {
  const real = fs.existsSync(p) ? fs.realpathSync(p) : path.resolve(p);
  if (!fs.existsSync(real)) die(`no such file or folder: ${p}`);
  if (SANDBOX) {
    if (!inside(real, CWD)) die(`sandbox: ${p} is outside this workspace`);
    const rel = path.relative(CWD, real);
    if (/(^|\/)(\.claude|\.git|\.client\.json)(\/|$)/.test(rel)) die(`sandbox: ${p} is off-limits`);
  }
  return real;
}

function checkOutPath(p) {
  const abs = path.resolve(p);
  if (SANDBOX && !inside(abs, CWD)) die(`sandbox: output must stay inside this workspace (${p})`);
  if (SANDBOX && /(^|\/)(\.claude|\.git|repos\/[^/]+\/\.git)(\/|$)/.test(path.relative(CWD, abs))) die(`sandbox: cannot write there`);
  fs.mkdirSync(path.dirname(abs), { recursive: true });
  return abs;
}

// ------------------------------------------------------------------ static server

function serve(root) {
  // root: a folder (served as a site) or a file (its folder is served, that file is the page)
  let dir = root, entry = "/";
  if (fs.statSync(root).isFile()) { dir = path.dirname(root); entry = "/" + path.basename(root); }
  const srv = http.createServer((req, res) => {
    try {
      let u = decodeURIComponent(new URL(req.url, "http://x").pathname);
      if (u.includes("\0")) throw new Error("bad path");
      let fp = path.join(dir, u);
      if (!inside(fp, dir)) { res.writeHead(403); res.end(); return; }
      if (fs.existsSync(fp) && fs.statSync(fp).isDirectory()) {
        if (!u.endsWith("/")) { res.writeHead(301, { Location: u + "/" }); res.end(); return; }
        fp = path.join(fp, "index.html");
      }
      if (!fs.existsSync(fp) && !path.extname(fp) && fs.existsSync(fp + ".html")) fp += ".html"; // Pages-style clean URLs
      if (!fs.existsSync(fp)) {
        const nf = path.join(dir, "404.html");
        res.writeHead(404, { "Content-Type": "text/html; charset=utf-8" });
        res.end(fs.existsSync(nf) ? fs.readFileSync(nf) : "not found");
        return;
      }
      res.writeHead(200, { "Content-Type": MIME[path.extname(fp).toLowerCase()] || "application/octet-stream", "Cache-Control": "no-store" });
      fs.createReadStream(fp).pipe(res);
    } catch {
      res.writeHead(400); res.end();
    }
  });
  return new Promise((resolve) => {
    srv.listen(0, "127.0.0.1", () => {
      const port = srv.address().port;
      resolve({ url: `http://127.0.0.1:${port}${entry}`, origin: `http://127.0.0.1:${port}`, close: () => srv.close() });
    });
  });
}

// ------------------------------------------------------------------ browser

async function launchBrowser() {
  const { chromium } = await import(pathToFileURL(path.join(HERE, "node_modules/playwright/index.mjs")).href);
  try {
    return await chromium.launch();
  } catch (e) {
    try {
      return await chromium.launch({ channel: "chrome" });
    } catch {
      die(`no browser: ${e.message.split("\n")[0]}\n  fix: cd ${HERE} && npx playwright install chromium`);
    }
  }
}

async function resolveTarget(raw, servers) {
  if (!raw) die("missing target (a URL or a local file/folder)");
  if (/^https?:\/\//i.test(raw)) {
    const u = new URL(raw);
    if (SANDBOX && (await hostIsPrivate(u.hostname))) die(`sandbox: ${u.hostname} is a private/local address`);
    return { url: raw, label: u.hostname.replace(/^www\./, ""), local: false };
  }
  if (/^[a-z]+:\/\//i.test(raw)) die(`unsupported URL scheme in ${raw} (use http(s) or a local path)`);
  const real = checkLocalPath(raw);
  const s = await serve(real);
  servers.push(s);
  const folder = (fs.statSync(real).isFile() ? path.dirname(raw) : raw).replace(/\/$/, "");
  return {
    url: s.url, label: path.basename(real.replace(/\/index\.html?$/, "")) || "site", local: true, origin: s.origin,
    show: (u) => (u.startsWith(s.origin) ? folder + new URL(u).pathname : u),
  };
}

async function newContext(browser, opts, vp, allowOrigins) {
  const ctx = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    deviceScaleFactor: vp.dpr,
    isMobile: vp.mobile,
    hasTouch: vp.mobile,
    colorScheme: opts.dark ? "dark" : opts.light ? "light" : undefined,
    reducedMotion: "reduce",
    userAgent: opts["user-agent"] || (vp.mobile
      ? "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1 shot"
      : undefined),
    acceptDownloads: false,
    ignoreHTTPSErrors: false,
  });
  ctx.setDefaultTimeout(+(opts.timeout || 30000));
  ctx.setDefaultNavigationTimeout(+(opts.timeout || 30000));
  if (SANDBOX) {
    await ctx.route("**/*", async (route) => {
      const u = new URL(route.request().url());
      if (allowOrigins.includes(u.origin)) return route.continue();
      if (["http:", "https:"].includes(u.protocol) && (await hostIsPrivate(u.hostname))) return route.abort("blockedbyclient");
      return route.continue();
    });
  }
  return ctx;
}

function attachCollectors(page) {
  const log = { console: [], failed: [], responses: [] };
  page.on("console", (m) => {
    if (["error", "warning"].includes(m.type())) log.console.push({ type: m.type(), text: m.text().slice(0, 300) });
  });
  page.on("pageerror", (e) => log.console.push({ type: "error", text: String(e.message || e).slice(0, 300) }));
  page.on("requestfailed", (r) => {
    const f = r.failure()?.errorText || "failed";
    // navigations and analytics beacons get aborted routinely; only real assets count
    if (f.includes("ERR_ABORTED") && !["image", "stylesheet", "script", "font", "media"].includes(r.resourceType())) return;
    log.failed.push({ url: r.url(), reason: f, type: r.resourceType() });
  });
  page.on("response", (r) => {
    log.responses.push({ url: r.url(), status: r.status(), type: r.request().resourceType() });
  });
  return log;
}

async function openPage(ctx, target, opts) {
  const page = await ctx.newPage();
  const log = attachCollectors(page);
  const t0 = Date.now();
  let resp;
  try {
    resp = await page.goto(target.url, { waitUntil: "load" });
  } catch (e) {
    die(`could not open ${target.url}: ${e.message.split("\n")[0]}`, 3);
  }
  try { await page.waitForLoadState("networkidle", { timeout: 8000 }); } catch {}
  const loadMs = Date.now() - t0;
  if (opts["wait-for"]) await page.waitForSelector(opts["wait-for"]);
  for (const sel of opts.click) await page.locator(sel).first().click();
  for (const sel of opts.hover) await page.locator(sel).first().hover();
  for (const spec of opts.type) {
    const [sel, text] = spec.split(/=(.*)/s);
    await page.locator(sel).first().fill(text ?? "");
  }
  if (opts["scroll-to"]) await page.locator(opts["scroll-to"]).first().scrollIntoViewIfNeeded();
  if (opts.js) await page.evaluate(opts.js);
  await page.waitForTimeout(+(opts.wait ?? 300));
  return { page, log, status: resp?.status(), loadMs };
}

function stamp() {
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\..*/, "").replace("T", "-");
}

function summarizeLog(log) {
  const failed = log.failed.concat(log.responses.filter((r) => r.status >= 400).map((r) => ({ url: r.url, reason: `HTTP ${r.status}`, type: r.type })));
  const errs = log.console.filter((c) => c.type === "error");
  const parts = [];
  if (errs.length) parts.push(`${errs.length} console error${errs.length > 1 ? "s" : ""}`);
  if (failed.length) parts.push(`${failed.length} failed request${failed.length > 1 ? "s" : ""}`);
  return { failed, errors: errs, line: parts.length ? parts.join(", ") : "no console errors, no failed requests" };
}

function short(u, origin) {
  return origin && u.startsWith(origin) ? u.slice(origin.length) || "/" : u.length > 90 ? u.slice(0, 87) + "..." : u;
}

// ------------------------------------------------------------------ commands

async function cmdShot(opts, browser, servers) {
  const target = await resolveTarget(opts._[0], servers);
  const vps = opts["all-sizes"] ? [PRESETS.desktop, PRESETS.mobile].map((p, i) => ({ ...p, name: i ? "mobile" : "desktop" })) : [viewportOf(opts)];
  const results = [];
  for (const vp of vps) {
    const ctx = await newContext(browser, opts, vp, target.origin ? [target.origin] : []);
    const { page, log, status, loadMs } = await openPage(ctx, target, opts);
    const ext = opts.jpg ? "jpg" : "png";
    const base = opts.out && vps.length === 1 ? opts.out : path.join(opts.out || "shots", `${target.label}-${vp.name}${opts.full ? "-full" : ""}-${stamp()}.${ext}`);
    const out = checkOutPath(base);
    const shotOpts = { path: out, type: opts.jpg ? "jpeg" : "png", animations: "disabled", ...(opts.jpg ? { quality: 85 } : {}) };
    if (opts.selector) {
      const loc = page.locator(opts.selector).first();
      if (!(await loc.count())) die(`nothing matches ${opts.selector}`);
      await loc.screenshot(shotOpts);
    } else {
      await page.screenshot({ ...shotOpts, fullPage: !!opts.full });
    }
    const title = await page.title();
    const h = await page.evaluate(() => document.documentElement.scrollHeight);
    const sum = summarizeLog(log);
    results.push({ path: out, viewport: `${vp.width}x${vp.height}@${vp.dpr}x`, vh: vp.height, preset: vp.name, title, status, page_height: h, load_ms: loadMs, ...sum });
    await ctx.close();
  }
  if (opts.json) return console.log(JSON.stringify({ target: target.url, shots: results }, null, 2));
  for (const r of results) {
    console.log(`${r.path}`);
    console.log(`  ${r.preset} ${r.viewport}${opts.full ? " full page" : ""} · "${r.title}" · HTTP ${r.status} in ${r.load_ms}ms · page ${r.page_height}px tall${!opts.full && r.page_height > r.vh ? " (use --full for all of it)" : ""}`);
    console.log(`  ${r.line}`);
    for (const f of r.failed.slice(0, 8)) console.log(`    ✗ ${f.reason}  ${short(f.url, target.origin)}`);
    for (const e of r.errors.slice(0, 8)) console.log(`    ! ${e.text}`);
  }
}

async function collectLinks(page, origin) {
  return page.evaluate((origin) => {
    const out = new Set();
    for (const a of document.querySelectorAll("a[href]")) {
      try {
        const u = new URL(a.getAttribute("href"), location.href);
        if (u.origin !== origin) continue;
        if (!/^$|\.html?$|\/$/.test(u.pathname.split("/").pop() ?? "") && /\.[a-z0-9]{2,5}$/i.test(u.pathname)) continue; // files, not pages
        u.hash = ""; u.search = "";
        u.pathname = u.pathname.replace(/\/index\.html?$/, "/");
        out.add(u.href);
      } catch {}
    }
    return [...out];
  }, origin);
}

async function cmdSite(opts, browser, servers) {
  const target = await resolveTarget(opts._[0], servers);
  const origin = new URL(target.url).origin;
  const allowed = target.origin ? [target.origin] : [];
  const max = +(opts.max || 25);
  const vps = opts.mobile || opts.tablet || opts.width ? [viewportOf(opts)] : [PRESETS.desktop, PRESETS.mobile].map((p, i) => ({ ...p, name: i ? "mobile" : "desktop" }));
  const dir = checkOutPath(path.join(opts.out || "shots", `${target.label}-site-${stamp()}`));
  fs.mkdirSync(dir, { recursive: true });
  const seen = new Set([target.url]);
  const queue = [target.url];
  const rows = [];
  while (queue.length && rows.length < max) {
    const url = queue.shift();
    const row = { url, files: [] };
    for (const vp of vps) {
      const ctx = await newContext(browser, opts, vp, allowed);
      let page, log;
      try {
        ({ page, log } = await openPage(ctx, { url }, { ...opts, click: [], hover: [], type: [] }));
      } catch (e) { row.error = String(e.message).split("\n")[0]; await ctx.close(); continue; }
      const slug = (new URL(url).pathname.replace(/\/$/, "") || "/index").replace(/\.html?$/, "").replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "index";
      const file = path.join(dir, `${slug}-${vp.name}.png`);
      await page.screenshot({ path: file, fullPage: true, animations: "disabled" });
      row.files.push(file);
      row.title = await page.title();
      const sum = summarizeLog(log);
      row.issues = (row.issues || 0) + sum.errors.length + sum.failed.length;
      if (vp === vps[0]) for (const l of await collectLinks(page, origin)) if (!seen.has(l)) { seen.add(l); queue.push(l); }
      await ctx.close();
    }
    rows.push(row);
  }
  if (opts.json) return console.log(JSON.stringify({ dir, pages: rows }, null, 2));
  console.log(`${dir}/  (${rows.length} page${rows.length !== 1 ? "s" : ""}${queue.length ? `, ${queue.length} more not visited (--max)` : ""})`);
  for (const r of rows) {
    console.log(`  ${short(r.url, origin)}  "${r.title || ""}"${r.issues ? `  ⚠ ${r.issues} issue${r.issues > 1 ? "s" : ""} (run: shot check ${target.show ? target.show(r.url) : r.url})` : ""}${r.error ? `  ✗ ${r.error}` : ""}`);
    for (const f of r.files) console.log(`      ${path.basename(f)}`);
  }
}

const AUDIT = `(() => {
  const vw = document.documentElement.clientWidth;
  const sw = document.documentElement.scrollWidth;
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== "hidden" && s.display !== "none"; };
  const desc = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += "#" + el.id;
    else if (el.className && typeof el.className === "string") s += "." + el.className.trim().split(/\\s+/).slice(0, 2).join(".");
    const t = (el.innerText || el.getAttribute("alt") || el.getAttribute("src") || "").trim().replace(/\\s+/g, " ");
    return t ? s + ' "' + t.slice(0, 40) + (t.length > 40 ? "…" : "") + '"' : s;
  };
  const overflow = [];
  for (const el of document.body.querySelectorAll("*")) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 || r.left < -1) {
      if (getComputedStyle(el).position === "fixed") continue;
      if (el.closest("[style*='overflow'], pre, .scroll, [class*='carousel'], [class*='marquee']")) continue;
      overflow.push(desc(el) + " (" + Math.round(r.left) + ".." + Math.round(r.right) + "px, viewport " + vw + "px)");
      if (overflow.length >= 8) break;
    }
  }
  const imgs = [...document.images];
  const brokenImgs = imgs.filter((i) => i.complete && i.naturalWidth === 0 && i.getAttribute("src")).map((i) => i.getAttribute("src"));
  const noAlt = imgs.filter((i) => !i.hasAttribute("alt")).map((i) => i.getAttribute("src") || desc(i));
  const emptyLinks = [...document.querySelectorAll("a")].filter((a) => vis(a) && !a.innerText.trim() && !a.querySelector("img[alt]:not([alt=''])") && !a.getAttribute("aria-label")).map(desc);
  const badHref = [...document.querySelectorAll("a[href]")].filter((a) => /^(#|javascript:|)$/.test(a.getAttribute("href").trim())).map((a) => desc(a));
  const tiny = document.documentElement.clientWidth < 500
    ? [...document.querySelectorAll("a, button, [role=button], input, select")].filter((el) => { if (!vis(el)) return false; const r = el.getBoundingClientRect(); return r.width < 24 || r.height < 24; }).map(desc).slice(0, 8)
    : [];
  const tinyText = [...document.querySelectorAll("p, li, a, span, td, label, small")].filter((el) => vis(el) && el.innerText.trim() && parseFloat(getComputedStyle(el).fontSize) < 11).map(desc).slice(0, 5);
  const fonts = [...document.fonts].filter((f) => f.status === "error").map((f) => f.family + " " + f.weight);
  const loadedFonts = [...new Set([...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family))];
  const headings = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].map((h) => h.tagName + ": " + h.innerText.trim().replace(/\\s+/g, " ").slice(0, 60));
  const h1s = document.querySelectorAll("h1").length;
  const meta = document.querySelector("meta[name=description]")?.content || "";
  const viewportMeta = !!document.querySelector("meta[name=viewport]");
  const lang = document.documentElement.getAttribute("lang") || "";
  const mixed = [...document.querySelectorAll("[src], [href]")].map((e) => e.getAttribute("src") || e.getAttribute("href")).filter((u) => location.protocol === "https:" && /^http:\\/\\//.test(u));
  return { vw, sw, overflow, brokenImgs, noAlt, emptyLinks, badHref, tiny, tinyText, fonts, loadedFonts, headings, h1s, title: document.title, meta, viewportMeta, lang, mixed, textLen: document.body.innerText.length };
})()`;

async function checkOne(browser, url, allowed, opts, origin, checkLinks) {
  const report = { url, viewports: {}, links: [] };
  for (const vp of [PRESETS.desktop, PRESETS.mobile].map((p, i) => ({ ...p, name: i ? "mobile" : "desktop" }))) {
    const ctx = await newContext(browser, opts, vp, allowed);
    let page, log, status, loadMs;
    try { ({ page, log, status, loadMs } = await openPage(ctx, { url }, { ...opts, click: [], hover: [], type: [] })); }
    catch (e) { report.error = String(e.message).split("\n")[0]; await ctx.close(); break; }
    const a = await page.evaluate(AUDIT);
    const sum = summarizeLog(log);
    report.viewports[vp.name] = { status, loadMs, audit: a, failed: sum.failed, errors: sum.errors };
    if (vp.name === "desktop" && checkLinks) {
      const links = await page.evaluate(() => [...new Set([...document.querySelectorAll("a[href]")].map((a) => { try { return new URL(a.getAttribute("href"), location.href).href; } catch { return null; } }).filter(Boolean))]);
      report.pageLinks = links;
      const req = ctx.request;
      for (const l of links.slice(0, 80)) {
        if (!/^https?:/.test(l)) continue;
        if (l.startsWith(origin) ? false : !opts.external) continue;
        if (SANDBOX && !allowed.includes(new URL(l).origin) && (await hostIsPrivate(new URL(l).hostname))) continue;
        try {
          let r = await req.fetch(l, { method: "HEAD", maxRedirects: 5, timeout: 10000 });
          if (r.status() === 405 || r.status() === 403) r = await req.fetch(l, { method: "GET", maxRedirects: 5, timeout: 10000 });
          if (r.status() >= 400) report.links.push({ url: l, status: r.status() });
        } catch (e) { report.links.push({ url: l, status: String(e.message).split("\n")[0].slice(0, 60) }); }
      }
    }
    await ctx.close();
  }
  return report;
}

function printCheck(rep, origin, show) {
  const p = (s) => console.log(s);
  p(`${show ? show(rep.url) : rep.url}`);
  if (rep.error) { p(`  ✗ could not open: ${rep.error}`); return 1; }
  let problems = 0;
  const d = rep.viewports.desktop, m = rep.viewports.mobile;
  const a = d.audit;
  p(`  "${a.title}" · HTTP ${d.status} · loads in ${d.loadMs}ms (desktop) / ${m?.loadMs ?? "?"}ms (mobile)`);
  const flag = (cond, msg, items = []) => {
    if (!cond) return;
    problems++;
    p(`  ✗ ${msg}`);
    for (const i of items.slice(0, 8)) p(`      ${i}`);
    if (items.length > 8) p(`      … ${items.length - 8} more`);
  };
  const ok = (msg) => p(`  ✓ ${msg}`);
  const errs = [...new Map([...d.errors, ...(m?.errors ?? [])].map((e) => [e.text, e])).values()];
  flag(errs.length, `${errs.length} console error${errs.length > 1 ? "s" : ""}`, errs.map((e) => e.text));
  const failed = [...new Map([...d.failed, ...(m?.failed ?? [])].map((f) => [f.url, f])).values()];
  flag(failed.length, `${failed.length} failed request${failed.length > 1 ? "s" : ""}`, failed.map((f) => `${f.reason}  ${short(f.url, origin)}`));
  if (!errs.length && !failed.length) ok("no console errors, every request succeeded");
  flag(a.brokenImgs.length, `${a.brokenImgs.length} broken image${a.brokenImgs.length > 1 ? "s" : ""}`, a.brokenImgs);
  flag(a.sw > a.vw + 1, `desktop: page is wider than the window (${a.sw}px vs ${a.vw}px) — horizontal scrollbar`, a.overflow);
  if (m) {
    const ma = m.audit;
    flag(ma.sw > ma.vw + 1, `mobile: page is wider than the screen (${ma.sw}px vs ${ma.vw}px) — sideways scroll on phones`, ma.overflow);
    if (ma.sw <= ma.vw + 1 && a.sw <= a.vw + 1) ok("fits the screen on desktop and mobile, no sideways scroll");
    flag(ma.tiny.length, `mobile: ${ma.tiny.length} tap target${ma.tiny.length > 1 ? "s" : ""} smaller than 24px`, ma.tiny);
    flag(ma.tinyText.length, `mobile: text under 11px`, ma.tinyText);
    flag(!ma.viewportMeta, "no <meta name=viewport> — phones will render the desktop layout zoomed out");
  }
  flag(a.fonts.length, `${a.fonts.length} web font${a.fonts.length > 1 ? "s" : ""} failed to load`, a.fonts);
  if (!a.fonts.length && a.loadedFonts.length) ok(`fonts loaded: ${a.loadedFonts.join(", ")}`);
  flag(a.noAlt.length, `${a.noAlt.length} image${a.noAlt.length > 1 ? "s" : ""} without alt text`, a.noAlt);
  flag(a.emptyLinks.length, `${a.emptyLinks.length} link${a.emptyLinks.length > 1 ? "s" : ""} with no text (unreadable to screen readers)`, a.emptyLinks);
  flag(a.badHref.length, `${a.badHref.length} link${a.badHref.length > 1 ? "s" : ""} going nowhere (href="#" or empty)`, a.badHref);
  flag(a.mixed.length, `${a.mixed.length} http:// resource${a.mixed.length > 1 ? "s" : ""} on an https page (blocked by browsers)`, a.mixed);
  flag(rep.links.length, `${rep.links.length} broken link${rep.links.length > 1 ? "s" : ""}`, rep.links.map((l) => `${l.status}  ${short(l.url, origin)}`));
  if (rep.pageLinks && !rep.links.length) ok(`${rep.pageLinks.filter((l) => l.startsWith(origin)).length} internal links all answer`);
  flag(!a.title, "no <title>");
  flag(a.h1s !== 1, `${a.h1s} <h1> headings (want exactly one)`, a.headings.filter((h) => h.startsWith("H1")));
  flag(!a.meta, "no meta description");
  flag(!a.lang, "no lang attribute on <html>");
  if (a.headings.length) p(`  · outline: ${a.headings.slice(0, 12).join(" | ")}${a.headings.length > 12 ? " | …" : ""}`);
  p(problems ? `  → ${problems} thing${problems > 1 ? "s" : ""} to look at` : `  → clean`);
  return problems;
}

async function cmdCheck(opts, browser, servers) {
  const target = await resolveTarget(opts._[0], servers);
  const origin = new URL(target.url).origin;
  const allowed = target.origin ? [target.origin] : [];
  const urls = [target.url];
  const reports = [];
  const seen = new Set(urls);
  const max = +(opts.max || 25);
  let total = 0;
  while (urls.length && reports.length < max) {
    const url = urls.shift();
    const rep = await checkOne(browser, url, allowed, opts, origin, !opts["no-links"]);
    reports.push(rep);
    if (!opts.json) total += printCheck(rep, origin, target.show);
    if (opts.all && rep.pageLinks) {
      for (const l of rep.pageLinks) {
        let u; try { u = new URL(l); } catch { continue; }
        if (u.origin !== origin) continue;
        if (/\.[a-z0-9]{2,5}$/i.test(u.pathname) && !/\.html?$/i.test(u.pathname)) continue;
        u.hash = ""; u.search = "";
        u.pathname = u.pathname.replace(/\/index\.html?$/, "/");
        if (!seen.has(u.href)) { seen.add(u.href); urls.push(u.href); }
      }
    }
  }
  if (opts.json) return console.log(JSON.stringify(reports, null, 2));
  if (reports.length > 1) console.log(`\n${reports.length} pages, ${total} thing${total !== 1 ? "s" : ""} to look at`);
  process.exitCode = total ? 1 : 0;
}

async function cmdText(opts, browser, servers) {
  const target = await resolveTarget(opts._[0], servers);
  const ctx = await newContext(browser, opts, viewportOf(opts), target.origin ? [target.origin] : []);
  const { page } = await openPage(ctx, target, opts);
  const sel = opts.selector || "body";
  const texts = await page.locator(sel).evaluateAll((els) => els.map((e) => e.innerText));
  if (!texts.length) die(`nothing matches ${sel}`);
  if (opts.json) return console.log(JSON.stringify({ title: await page.title(), text: texts }, null, 2));
  console.log(texts.map((t) => t.replace(/\n{3,}/g, "\n\n").trim()).join("\n\n----\n\n"));
}

async function cmdHtml(opts, browser, servers) {
  const target = await resolveTarget(opts._[0], servers);
  const ctx = await newContext(browser, opts, viewportOf(opts), target.origin ? [target.origin] : []);
  const { page } = await openPage(ctx, target, opts);
  const sel = opts.selector || opts._[1] || "html";
  const html = await page.locator(sel).evaluateAll((els) => els.map((e) => e.outerHTML));
  if (!html.length) die(`nothing matches ${sel}`);
  console.log(html.slice(0, +(opts.max || 10)).join("\n\n<!-- ---- -->\n\n"));
}

async function cmdCss(opts, browser, servers) {
  const target = await resolveTarget(opts._[0], servers);
  const sel = opts._[1] || opts.selector;
  if (!sel) die("usage: shot css <target> <selector> [property ...]");
  const props = opts._.slice(2).length ? opts._.slice(2) : DEFAULT_CSS_PROPS;
  const ctx = await newContext(browser, opts, viewportOf(opts), target.origin ? [target.origin] : []);
  const { page } = await openPage(ctx, target, opts);
  const rows = await page.locator(sel).evaluateAll((els, props) => els.slice(0, 10).map((el) => {
    const cs = getComputedStyle(el), r = el.getBoundingClientRect();
    const style = {};
    for (const p of props) style[p] = cs.getPropertyValue(p);
    let d = el.tagName.toLowerCase();
    if (el.id) d += "#" + el.id;
    else if (typeof el.className === "string" && el.className.trim()) d += "." + el.className.trim().split(/\s+/).slice(0, 3).join(".");
    const fam = cs.fontFamily.split(",")[0].replace(/["']/g, "").trim();
    const faces = [...document.fonts].filter((f) => f.family.replace(/["']/g, "") === fam);
    const font = faces.find((f) => f.status === "loaded") || faces[0];
    return {
      element: d, text: (el.innerText || "").trim().replace(/\s+/g, " ").slice(0, 60),
      box: { x: Math.round(r.x), y: Math.round(r.y + scrollY), width: Math.round(r.width), height: Math.round(r.height) },
      font_loaded: font ? `${fam} ${font.status}` : (/^(serif|sans-serif|monospace|system-ui|-apple-system|ui-)/.test(fam) ? `${fam} (system)` : `${fam} is not a web font on this page — falling back`),
      style,
    };
  }), props);
  if (!rows.length) die(`nothing matches ${sel}`);
  if (opts.json) return console.log(JSON.stringify(rows, null, 2));
  const vp = viewportOf(opts);
  console.log(`${rows.length} match${rows.length > 1 ? "es" : ""} for ${sel} at ${vp.name} (${vp.width}x${vp.height})`);
  for (const r of rows) {
    console.log(`\n${r.element}${r.text ? `  "${r.text}"` : ""}`);
    console.log(`  box: ${r.box.width}x${r.box.height} at (${r.box.x}, ${r.box.y})   font: ${r.font_loaded}`);
    for (const [k, v] of Object.entries(r.style)) if (v && v !== "none" && v !== "normal" && v !== "auto" && v !== "0px" && v !== "rgba(0, 0, 0, 0)" && v !== "static" && v !== "visible" && v !== "0px none rgb(0, 0, 0)") console.log(`  ${k}: ${v}`);
  }
}

async function cmdDiff(opts) {
  const [a, b] = opts._;
  if (!a || !b) die("usage: shot diff <before.png> <after.png> [--out diff.png]");
  const { PNG } = await import(pathToFileURL(path.join(HERE, "node_modules/pngjs/lib/png.js")).href);
  const pixelmatch = (await import(pathToFileURL(path.join(HERE, "node_modules/pixelmatch/index.js")).href)).default;
  const A = PNG.sync.read(fs.readFileSync(checkLocalPath(a)));
  const B = PNG.sync.read(fs.readFileSync(checkLocalPath(b)));
  const w = Math.max(A.width, B.width), h = Math.max(A.height, B.height);
  const pad = (img) => {
    if (img.width === w && img.height === h) return img;
    const out = new PNG({ width: w, height: h });
    out.data.fill(0);
    PNG.bitblt(img, out, 0, 0, img.width, img.height, 0, 0);
    return out;
  };
  const pa = pad(A), pb = pad(B);
  const diff = new PNG({ width: w, height: h });
  const n = pixelmatch(pa.data, pb.data, diff.data, w, h, { threshold: 0.1, alpha: 0.4, diffColor: [255, 0, 90] });
  const out = checkOutPath(opts.out || path.join("shots", `diff-${stamp()}.png`));
  fs.writeFileSync(out, PNG.sync.write(diff));
  // bounding box of changes
  let minX = w, minY = h, maxX = -1, maxY = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = (y * w + x) * 4;
    if (diff.data[i] === 255 && diff.data[i + 1] === 0 && diff.data[i + 2] === 90) { if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y; }
  }
  const pct = ((n / (w * h)) * 100).toFixed(2);
  if (opts.json) return console.log(JSON.stringify({ out, changed_pixels: n, percent: +pct, size_changed: A.width !== B.width || A.height !== B.height, region: maxX >= 0 ? { x: minX, y: minY, width: maxX - minX + 1, height: maxY - minY + 1 } : null }, null, 2));
  console.log(out);
  if (A.width !== B.width || A.height !== B.height) console.log(`  sizes differ: ${A.width}x${A.height} → ${B.width}x${B.height} (page got ${B.height > A.height ? "taller" : B.height < A.height ? "shorter" : "wider/narrower"})`);
  console.log(n ? `  ${n} pixels changed (${pct}%), within x ${minX}..${maxX}, y ${minY}..${maxY} — changes are pink in the diff` : "  identical");
}

function cmdClean(opts) {
  const days = +(opts.days || 7);
  const dir = path.resolve(opts.out || "shots");
  if (!fs.existsSync(dir)) return console.log("nothing to clean");
  checkOutPath(dir);
  const cutoff = Date.now() - days * 86400e3;
  let n = 0;
  const walk = (d) => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name);
      if (e.isDirectory()) { walk(p); if (!fs.readdirSync(p).length) fs.rmdirSync(p); }
      else if (fs.statSync(p).mtimeMs < cutoff) { fs.unlinkSync(p); n++; }
    }
  };
  walk(dir);
  console.log(`removed ${n} file${n !== 1 ? "s" : ""} older than ${days} day${days !== 1 ? "s" : ""} from ${path.relative(CWD, dir) || "."}`);
}

async function cmdDoctor() {
  let ok = true;
  const say = (good, msg) => { console.log(`  ${good ? "OK  " : "FAIL"} ${msg}`); if (!good) ok = false; };
  console.log(`shot doctor (${HERE})`);
  say(fs.existsSync(path.join(HERE, "node_modules/playwright")), "playwright installed (npm install in claude-tools)");
  say(fs.existsSync(path.join(HERE, "node_modules/pixelmatch")), "pixelmatch installed (shot diff)");
  say(fs.existsSync(path.join(HERE, "node_modules/@playwright/mcp")), "@playwright/mcp installed (interactive browser for the global workspace)");
  let browser;
  try {
    browser = await launchBrowser();
    const v = browser.version();
    say(true, `headless Chromium launches (${v})`);
    const page = await browser.newPage();
    await page.setContent("<h1 style='font:20px sans-serif'>shot</h1>");
    const buf = await page.screenshot();
    say(buf.length > 500, `renders a page (${buf.length} bytes)`);
    await browser.close();
  } catch (e) { say(false, `browser: ${e.message.split("\n")[0]}`); }
  console.log(`  mode ${SANDBOX ? "sandbox (client workspace: local paths and outputs stay inside it, no private addresses)" : "unrestricted"}`);
  process.exit(ok ? 0 : 1);
}

// ------------------------------------------------------------------ main

const COMMANDS = { site: cmdSite, check: cmdCheck, text: cmdText, html: cmdHtml, css: cmdCss };

async function main() {
  const argv = process.argv.slice(2);
  if (!argv.length) usage(1);
  const opts = parseArgs(argv);
  let cmd = opts._[0];
  if (cmd === "doctor") return cmdDoctor();
  if (cmd === "clean") return cmdClean({ ...opts, _: opts._.slice(1) });
  if (cmd === "diff") return cmdDiff({ ...opts, _: opts._.slice(1) });
  let fn = cmdShot;
  if (COMMANDS[cmd]) { fn = COMMANDS[cmd]; opts._ = opts._.slice(1); }
  else if (cmd === "shot" || cmd === "screenshot") { opts._ = opts._.slice(1); }
  const servers = [];
  const browser = await launchBrowser();
  try {
    await fn(opts, browser, servers);
  } finally {
    await browser.close().catch(() => {});
    for (const s of servers) s.close();
  }
}

main().catch((e) => {
  console.error(`shot: ${e?.message?.split("\n")[0] || e}`);
  process.exit(1);
});
