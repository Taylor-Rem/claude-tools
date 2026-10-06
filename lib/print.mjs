#!/usr/bin/env node
// print's browser half (bin/print is the CLI; see its docstring). Two jobs:
//
//   node lib/print.mjs render PAGE.html --w IN --h IN [--pdf OUT.pdf] [--png OUT.png] [--dpi 300] [--pages all]
//       lay the page out in headless Chromium at W x H inches and write a PDF
//       (vector, fonts embedded, backgrounds on) and/or a PNG at DPI.
//   node lib/print.mjs decode IMAGE.png [--crop x,y,w,h]   (fractions of the image)
//       read the QR code in a PNG with jsQR (pure JS); prints JSON
//       {"data": "..."} or {"data": null}.
//
// Everything is local: the page is a file, the browser may fetch the site's web
// fonts and nothing else matters if it can't.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const mod = (p) => import(pathToFileURL(path.join(HERE, "node_modules", p)).href);

function die(msg) { process.stderr.write(`print: ${msg}\n`); process.exit(1); }

function opts(argv) {
  const o = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith("--")) o[argv[i].slice(2)] = argv[++i];
    else o._.push(argv[i]);
  }
  return o;
}

async function launch() {
  const { chromium } = await mod("playwright/index.mjs");
  try { return await chromium.launch(); }
  catch (e) {
    try { return await chromium.launch({ channel: "chrome" }); }
    catch { die(`no browser: ${e.message.split("\n")[0]}\n  fix: cd ${HERE} && npx playwright install chromium`); }
  }
}

async function render(o) {
  const page_ = o._[0];
  if (!page_ || !fs.existsSync(page_)) die(`no page ${page_}`);
  const w = parseFloat(o.w), h = parseFloat(o.h), dpi = parseFloat(o.dpi || "300");
  if (!(w > 0 && h > 0)) die("--w and --h (inches) are required");
  const browser = await launch();
  try {
    const ctx = await browser.newContext({
      viewport: { width: Math.round(w * 96), height: Math.round(h * 96) },
      deviceScaleFactor: dpi / 96,
    });
    const page = await ctx.newPage();
    await page.goto(pathToFileURL(path.resolve(page_)).href, { waitUntil: "load", timeout: 30000 });
    try { await page.waitForLoadState("networkidle", { timeout: 8000 }); } catch {}
    await page.evaluate(() => document.fonts.ready);
    // the page's own fit() (menu) shrinks type until everything is on one sheet
    await page.evaluate(() => (window.fit ? window.fit() : null));
    const report = await page.evaluate(() => ({
      overflow: document.documentElement.scrollHeight > window.innerHeight + 1 ||
                document.documentElement.scrollWidth > window.innerWidth + 1,
      fonts: [...document.fonts].filter((f) => f.status === "loaded").map((f) => f.family),
      fit: window.fitScale || null,
    }));
    if (o.png) await page.screenshot({ path: o.png, clip: { x: 0, y: 0, width: w * 96, height: h * 96 } });
    if (o.pdf) {
      await page.emulateMedia({ media: "print" });
      await page.pdf({ path: o.pdf, width: `${w}in`, height: `${h}in`, printBackground: true,
                       margin: { top: 0, right: 0, bottom: 0, left: 0 },
                       // one sheet unless asked (--pages all: a long document, sign's signed PDF;
                       // its own @page margins then apply on every page)
                       ...(o.pages === "all" ? {} : { pageRanges: "1" }) });
    }
    process.stdout.write(JSON.stringify(report) + "\n");
  } finally {
    await browser.close();
  }
}

async function decode(o) {
  const file = o._[0];
  if (!file || !fs.existsSync(file)) die(`no image ${file}`);
  const { PNG } = await mod("pngjs/lib/png.js");
  const jsQR = (await mod("jsqr/dist/jsQR.js")).default;
  const png = PNG.sync.read(fs.readFileSync(file));
  let [x, y, cw, ch] = [0, 0, png.width, png.height];
  if (o.crop) {
    const f = o.crop.split(",").map(Number);
    x = Math.round(f[0] * png.width); y = Math.round(f[1] * png.height);
    cw = Math.round(f[2] * png.width); ch = Math.round(f[3] * png.height);
  }
  const data = new Uint8ClampedArray(cw * ch * 4);
  for (let r = 0; r < ch; r++) {
    const src = ((y + r) * png.width + x) * 4;
    data.set(png.data.subarray(src, src + cw * 4), r * cw * 4);
  }
  const hit = jsQR(data, cw, ch, { inversionAttempts: "attemptBoth" });
  process.stdout.write(JSON.stringify({ data: hit ? hit.data : null }) + "\n");
}

async function doctor() {
  const out = {};
  try { await mod("jsqr/dist/jsQR.js"); out.jsqr = true; } catch { out.jsqr = false; }
  try { await mod("pngjs/lib/png.js"); out.pngjs = true; } catch { out.pngjs = false; }
  try { const b = await launch(); out.browser = b.version(); await b.close(); } catch (e) { out.browser = null; }
  process.stdout.write(JSON.stringify(out) + "\n");
}

const [cmd, ...rest] = process.argv.slice(2);
const o = opts(rest);
if (cmd === "render") await render(o);
else if (cmd === "decode") await decode(o);
else if (cmd === "doctor") await doctor();
else die("usage: print.mjs render|decode|doctor ...");
