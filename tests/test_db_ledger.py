"""The ledger, receipts by photo (ROADMAP B124): `db ledger …`, the photos kept
in the workspace's receipts/, `db export` zipping them beside ledger.csv, and
the collection's /admin/ledger page under node with node:sqlite as D1. On the
fake wrangler; no network.

The three receipts in tests/fixtures/receipts/ are fictional (ImageMagick text
on paper) and are what the acceptance texts to demo-service:

    bluebird-pool-supply.jpg   Bluebird Pool Supply   2026-10-02   $83.10
    juniper-fuel.jpg           Juniper Fuel & Go      2026-10-03   $61.27
    ridgeline-hardware.jpg     Ridgeline Hardware     2026-09-28   $23.96

    python3 -m unittest tests.test_db_ledger -q   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402

import csv
import datetime
import importlib.machinery
import importlib.util
import io
import json
import os
import shutil
import subprocess
import unittest
import zipfile
from pathlib import Path

import test_db  # noqa: E402  (its setUp makes a workspace with a site and a database)

ROOT = test_db.ROOT
COLL = ROOT / "templates" / "collections" / "ledger"
RECEIPTS = Path(__file__).resolve().parent / "fixtures" / "receipts"
TODAY = datetime.date.today()
THREE = [("bluebird-pool-supply.jpg", "Bluebird Pool Supply", "83.10", "2026-10-02", "supplies", "chlorine"),
         ("juniper-fuel.jpg", "Juniper Fuel & Go", "61.27", "2026-10-03", "fuel", "truck"),
         ("ridgeline-hardware.jpg", "Ridgeline Hardware", "23.96", "2026-09-28", "supplies", "truck: pump fittings")]


def load_db():
    loader = importlib.machinery.SourceFileLoader("db_tool", str(test_db.DB))
    spec = importlib.util.spec_from_loader("db_tool", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class LedgerTest(unittest.TestCase):
    setUp = test_db.DbTest.setUp
    tearDown = test_db.DbTest.tearDown
    row = test_db.DbTest.row
    register = test_db.DbTest.register
    make_repo = test_db.DbTest.make_repo
    db = test_db.DbTest.db

    def ledger(self):
        r = self.db("add", "ledger")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def j(self, *args):
        r = self.db(*args, "--json")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout)

    def texted(self, name):
        """A photo the way the relay leaves one: in incoming/."""
        dest = self.ws / "incoming" / name
        dest.parent.mkdir(exist_ok=True)
        shutil.copy(RECEIPTS / name, dest)
        return f"incoming/{name}"

    def file_three(self):
        out = []
        for f, vendor, amount, day, cat, note in THREE:
            out.append(self.j("ledger", "add", vendor, amount, "--date", day, "--category", cat, "--note", note,
                              "--photo", self.texted(f)))
        return out

    # -- add -------------------------------------------------------------------

    def test_add_wires_the_view_and_the_page(self):
        r = self.ledger()
        for f in ("migrations/0002_ledger.sql", "functions/_admin/ledger.js", "functions/admin/ledger/index.js"):
            self.assertTrue((self.repo / f).exists(), f)
        self.assertIn("ledger", (self.repo / "functions/_admin/collections.js").read_text())
        self.assertIn("ledger", r.stdout)
        cols = {c["name"] for c in json.loads(self.db("query", "PRAGMA table_xinfo(ledger)", "--json").stdout)}
        self.assertTrue({"date", "month", "vendor", "amount_cents", "category", "note", "photo", "source"} <= cols)
        import re
        text = (COLL / "functions" / "_admin" / "ledger.js").read_text()
        for col in re.findall(r'(?:name: "|\["(?=[a-z_]+", "[A-Z]))([a-z_]+)"', text):
            self.assertIn(col, cols, col)

    def test_without_the_ledger_it_says_how(self):
        r = self.db("ledger", "ls")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("db add ledger", r.stderr)

    def test_three_receipts_land_with_their_photos_and_the_month_total(self):
        self.ledger()
        a, b, c = self.file_three()
        self.assertEqual((a["receipt"]["vendor"], a["receipt"]["amount_cents"], a["receipt"]["date"]),
                         ("Bluebird Pool Supply", 8310, "2026-10-02"))
        self.assertEqual(b["month"], {"month": "2026-10", "count": 2, "total_cents": 14437})
        self.assertEqual(c["month"], {"month": "2026-09", "count": 1, "total_cents": 2396})
        for got, (f, *_rest) in zip((a, b, c), THREE):
            photo = got["receipt"]["photo"]
            self.assertTrue(photo.startswith(f"receipts/{got['receipt']['date'][:7]}/"), photo)
            self.assertEqual((self.ws / photo).read_bytes(), (RECEIPTS / f).read_bytes())
        self.assertEqual(a["receipt"]["photo"], f"receipts/2026-10/2026-10-02-bluebird-pool-supply-{a['receipt']['id']}.jpg")
        # "what did I spend in October"
        oct_ = self.j("ledger", "ls", "--month", "2026-10")
        self.assertEqual((oct_["count"], oct_["total_cents"]), (2, 14437))
        self.assertEqual({x["category"]: x["total_cents"] for x in oct_["by_category"]}, {"supplies": 8310, "fuel": 6127})
        text = self.db("ledger", "ls", "--month", "2026-10").stdout
        self.assertIn("October 2026: $144.37 over 2 receipts", text)
        # "receipts for the truck": the note, across months
        truck = self.j("ledger", "ls", "--search", "truck")
        self.assertEqual(sorted(x["vendor"] for x in truck["rows"]), ["Juniper Fuel & Go", "Ridgeline Hardware"])
        self.assertEqual(truck["total_cents"], 8523)
        # the text a run answers with
        r = self.db("ledger", "add", "Juniper Fuel & Go", "40", "--date", "2026-10-04")
        self.assertIn("filed #4 Oct 4, 2026 Juniper Fuel & Go $40.00", r.stdout)
        self.assertIn("October 2026 so far: $184.37 over 3 receipts", r.stdout)

    def test_the_same_receipt_twice_is_refused_until_forced(self):
        self.ledger()
        self.j("ledger", "add", "Bluebird Pool Supply", "83.10", "--date", "10/2/2026")
        r = self.db("ledger", "add", "bluebird pool supply", "$83.10", "--date", "2026-10-02", "--json")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(json.loads(r.stdout)["existing"]["id"], 1)
        r = self.db("ledger", "add", "Bluebird Pool Supply", "83.10", "--date", "2026-10-02", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_date_ahead_and_a_zero_total_are_refused(self):
        self.ledger()
        ahead = (TODAY + datetime.timedelta(days=30)).isoformat()
        r = self.db("ledger", "add", "Somewhere", "12", "--date", ahead)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("after today", r.stderr)
        r = self.db("ledger", "add", "Somewhere", "0")
        self.assertNotEqual(r.returncode, 0)
        r = self.db("ledger", "add", "Refund Co", "-12.50", "--date", "2026-10-01", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["receipt"]["amount_cents"], -1250)

    def test_a_photo_outside_the_workspace_or_a_link_is_refused(self):
        self.ledger()
        r = self.db("ledger", "add", "X", "5", "--photo", str(RECEIPTS / "juniper-fuel.jpg"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("outside this workspace", r.stderr)
        (self.ws / "incoming").mkdir(exist_ok=True)
        os.symlink(RECEIPTS / "juniper-fuel.jpg", self.ws / "incoming" / "link.jpg")
        r = self.db("ledger", "add", "X", "5", "--photo", "incoming/link.jpg")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(json.loads(self.db("query", "SELECT COUNT(*) AS n FROM ledger", "--json").stdout)[0]["n"], 0,
                         "nothing written for a refused photo")
        # a receipts/ that is a link is not written through
        os.symlink(self.root, self.ws / "receipts")
        r = self.db("ledger", "add", "X", "5", "--photo", self.texted("juniper-fuel.jpg"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not a plain folder", r.stderr)

    def test_set_and_rm(self):
        self.ledger()
        a, _b, _c = self.file_three()
        rid = a["receipt"]["id"]
        got = self.j("ledger", "set", str(rid), "--amount", "38.10", "--category", "Chemicals")
        self.assertEqual((got["amount_cents"], got["category"]), (3810, "chemicals"))
        photo = self.ws / got["photo"]
        r = self.db("ledger", "rm", str(rid))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(photo.exists(), "a receipt filed by mistake takes its photo with it")
        self.assertEqual(self.j("ledger", "ls", "--month", "2026-10")["count"], 1)

    def test_a_refused_photo_type_leaves_no_row(self):
        """The type and size checks run before the INSERT, so the retry isn't "already filed"."""
        self.ledger()
        (self.ws / "incoming").mkdir(exist_ok=True)
        (self.ws / "incoming" / "r.tiff").write_bytes(b"II*\x00not really")
        r = self.db("ledger", "add", "X", "5", "--date", "2026-10-01", "--photo", "incoming/r.tiff")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("a receipt is a photo or a PDF", r.stderr)
        self.assertEqual(json.loads(self.db("query", "SELECT COUNT(*) AS n FROM ledger", "--json").stdout)[0]["n"], 0)
        r = self.db("ledger", "add", "X", "5", "--date", "2026-10-01", "--photo", self.texted("juniper-fuel.jpg"))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_amounts_and_dates_are_plain(self):
        self.ledger()
        for bad in ("1e5", "inf", "nan", "12.5.1", "-"):
            r = self.db("ledger", "add", "X", bad, "--date", "2026-10-01")
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertIn("isn't an amount", r.stderr, bad)
            self.assertNotIn("Traceback", r.stderr, bad)
        r = self.db("ledger", "add", "X", "83100", "--date", "2026-10-01")   # 831.00 with the point dropped
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("over $10,000", r.stderr)
        self.assertIn("--yes", r.stderr)
        self.assertEqual(self.j("ledger", "add", "X", "831.00", "--date", "2026-10-01")["receipt"]["amount_cents"], 83100)
        r = self.db("ledger", "add", "Truck Lot", "$18,500", "--date", "2026-10-01")
        self.assertNotEqual(r.returncode, 0)
        got = self.j("ledger", "add", "Truck Lot", "$18,500", "--date", "2026-10-01", "--yes")
        self.assertEqual(got["receipt"]["amount_cents"], 1850000)
        r = self.db("ledger", "set", "1", "--amount", "83100")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--yes", r.stderr)
        r = self.db("ledger", "add", "X", "5", "--date", "2026-10-02junk")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("isn't a date", r.stderr)
        d = load_db().iso_date
        self.assertEqual([d(x) for x in ("2026-10-02", "2026-10-02T09:15:00Z", "2026-10-02 09:15", "2026-10-02junk",
                                         "2026-10-02x09:15")],
                         ["2026-10-02", "2026-10-02", "2026-10-02", "", ""])

    def test_a_new_photo_replaces_the_old_file(self):
        self.ledger()
        a, _b, _c = self.file_three()
        rid, old = a["receipt"]["id"], self.ws / a["receipt"]["photo"]
        got = self.j("ledger", "set", str(rid), "--vendor", "Bluebird Pool", "--photo", self.texted("ridgeline-hardware.jpg"))
        self.assertNotEqual(got["photo"], a["receipt"]["photo"])
        self.assertTrue((self.ws / got["photo"]).is_file())
        self.assertFalse(old.exists(), "the replaced photo is gone, so the zip holds only live ones")
        # the same name (date and vendor unchanged) is overwritten in place and kept
        got2 = self.j("ledger", "set", str(rid), "--photo", self.texted("juniper-fuel.jpg"))
        self.assertEqual(got2["photo"], got["photo"])
        self.assertEqual((self.ws / got2["photo"]).read_bytes(), (RECEIPTS / "juniper-fuel.jpg").read_bytes())

        # -- export ------------------------------------------------------------------

    def test_export_carries_the_photos_zipped_beside_the_csv(self):
        self.ledger()
        self.file_three()
        r = self.db("export")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.ws / "exports" / TODAY.isoformat()
        rows = list(csv.DictReader(io.StringIO((out / "ledger.csv").read_text())))
        self.assertEqual([x["vendor"] for x in rows], [v for _f, v, *_ in THREE])
        with zipfile.ZipFile(out / "receipts.zip") as z:
            names = z.namelist()
            self.assertEqual(sorted(names), sorted(x["photo"] for x in rows), "the zip's paths are the photo column's")
            self.assertEqual(z.read(rows[1]["photo"]), (RECEIPTS / "juniper-fuel.jpg").read_bytes())
        self.assertIn("receipts: 3 photos", r.stdout)
        shutil.rmtree(out)
        r = self.db("ledger", "export")
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["ledger.csv", "ledger.json", "receipts.zip"])

    def test_the_json_export_imports_back(self):
        """ledger.json has the CSV's columns, not the generated `month`, so `db import` takes it."""
        self.ledger()
        self.file_three()
        self.db("export")
        out = self.ws / "exports" / TODAY.isoformat()
        data = json.loads((out / "ledger.json").read_text())
        self.assertNotIn("month", data[0])
        self.assertEqual(list(data[0]), next(csv.reader(io.StringIO((out / "ledger.csv").read_text()))))
        self.db("exec", "DELETE FROM ledger", "--yes")
        r = self.db("import", "ledger", str(out / "ledger.json"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.j("ledger", "ls", "--month", "2026-10")["total_cents"], 14437)

    def test_export_says_which_photos_are_missing(self):
        self.ledger()
        a, _b, _c = self.file_three()
        (self.ws / a["receipt"]["photo"]).unlink()
        r = self.db("export")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("receipts: 2 photos", r.stdout)
        self.assertIn(f"#{a['receipt']['id']} {a['receipt']['photo']}", r.stdout)
        self.assertIn("isn't in receipts/ any more", r.stdout)

    def test_export_skips_links_left_in_receipts(self):
        self.ledger()
        self.file_three()
        os.symlink(Path.home() / ".bashrc", self.ws / "receipts" / "2026-10" / "sneaky.jpg")
        os.symlink(self.root, self.ws / "receipts" / "dir-link")
        self.db("export")
        with zipfile.ZipFile(self.ws / "exports" / TODAY.isoformat() / "receipts.zip") as z:
            self.assertEqual(len(z.namelist()), 3)
            self.assertFalse(any("sneaky" in n or "dir-link" in n for n in z.namelist()))

    # -- month words -----------------------------------------------------------------

    def test_month_words(self):
        m = load_db().month_arg
        today = datetime.date(2026, 10, 5)
        self.assertEqual([m(x, today) for x in ("2026-09", "9/2026", "september", "Sep", "sept 2025", "this", "last",
                                                "november", "december", "soon", "")],
                         ["2026-09", "2026-09", "2026-09", "2026-09", "2025-09", "2026-10", "2026-09",
                          "2025-11", "2025-12", "", ""])

    # -- the site's own page ---------------------------------------------------------

    def test_the_admin_page_says_what_it_isnt_and_totals_by_month(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("no node")
        if subprocess.run([node, "-e", "require('node:sqlite')"], capture_output=True).returncode != 0:
            self.skipTest("this node has no node:sqlite")
        work = Path(self.tmp.name) / "fn"
        shutil.copytree(test_db.TEMPLATE / "functions", work / "functions")
        shutil.copytree(COLL / "functions", work / "functions", dirs_exist_ok=True)
        (work / "functions" / "_admin" / "collections.js").write_text(
            'import ledger from "./ledger.js";\nexport default { ledger };\n')
        (work / "mig.sql").write_text((COLL / "migrations" / "0001_ledger.sql").read_text())
        (work / "run.mjs").write_text(r"""
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import { onRequestGet, onRequestPost, cents, NOT_ADVICE } from "./functions/admin/ledger/index.js";
const sql = new DatabaseSync(":memory:");
sql.exec(readFileSync("mig.sql", "utf8"));
const norm = (a) => a.map((x) => (x === undefined ? null : x));
const DB = { prepare(q) { const st = { args: [], bind(...a) { st.args = norm(a); return st; },
  async first() { return sql.prepare(q).get(...st.args) ?? null; },
  async all() { return { results: sql.prepare(q).all(...st.args) }; },
  async run() { const r = sql.prepare(q).run(...st.args); return { meta: { changes: Number(r.changes), last_row_id: Number(r.lastInsertRowid) } }; } }; return st; } };
const env = { DB, TIMEZONE: "America/Denver", SITE_NAME: "Acme" };
const out = { cents: [cents("$1,200.50"), cents("42.18"), cents("-3"), cents("x"), cents("")] };
const form = (o) => new Request("https://s.example/admin/ledger", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(o) });
let r = await onRequestPost({ request: form({ date: "2026-10-02", vendor: "Bluebird Pool Supply", amount: "$83.10", category: "supplies" }), env, data: {} });
out.added = [r.status, r.headers.get("location")];
await onRequestPost({ request: form({ date: "2026-10-03", vendor: "Juniper Fuel & Go", amount: "61.27" }), env, data: {} });
await onRequestPost({ request: form({ date: "2026-09-28", vendor: "Ridgeline Hardware", amount: "23.96" }), env, data: {} });
r = await onRequestPost({ request: form({ date: "2026-09-28", vendor: "No amount", amount: "lots" }), env, data: {} });
out.refused = r.status;
r = await onRequestGet({ request: new Request("https://s.example/admin/ledger"), env, params: {}, data: {} });
const html = await r.text();
out.page = [r.status, html.includes(NOT_ADVICE.slice(0, 60)), html.includes("not categories a CPA would sign"),
  html.includes("October 2026"), html.includes("$144.37"), html.includes("$23.96"), html.includes("Add a receipt")];
r = await onRequestGet({ request: new Request("https://s.example/admin/ledger?month=2026-10"), env, params: {}, data: {} });
const oct = await r.text();
out.october = [oct.includes("Amount: $144.37"), oct.includes("Ridgeline")];
console.log(JSON.stringify(out));
""")
        r = subprocess.run([node, "--no-warnings", "run.mjs"], capture_output=True, text=True, cwd=work)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["cents"], [120050, 4218, -300, None, None])
        self.assertEqual(out["added"], [303, "/admin/ledger/1"])
        self.assertEqual(out["refused"], 422)
        self.assertEqual(out["page"], [200, True, True, True, True, True, True])
        self.assertEqual(out["october"], [True, False], "the month chooser's total is the month's, its rows only")


if __name__ == "__main__":
    unittest.main()
