"""The customer book (ROADMAP B122): `db customers …`, `db jobs …`, the
collection's own Functions (the upsert a booking will call, the CSV import on
/admin) — on the fake wrangler and, for the Functions, under node with a D1
stand-in over node:sqlite. No network.

    python3 -m unittest tests.test_db_customers -q   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402

import csv
import datetime
import io
import json
import shutil
import subprocess
import unittest
from pathlib import Path

import test_db  # noqa: E402  (its setUp makes a workspace with a site and a database)

ROOT = test_db.ROOT
COLL = ROOT / "templates" / "collections" / "customers"
TODAY = datetime.date.today()


def ago(n):
    return (TODAY - datetime.timedelta(days=n)).isoformat()


def us(n):
    """US short date, the way a spreadsheet saves one."""
    d = TODAY - datetime.timedelta(days=n)
    return f"{d.month}/{d.day}/{d.year}"


# Twenty customers the way an owner's sheet has them: their own headers, US
# dates, a column we don't know (pool size), one person twice, one with no date.
SHEET = [
    ["Customer Name", "Mobile", "Email", "Street", "City", "Last Visit", "Pool size"],
    ["Dana Ruiz", "(801) 555-0134", "dana@example.com", "12 Elm", "Provo", us(10), "16x32"],
    ["Sam Smith", "801.555.0101", "", "4 Oak", "Orem", us(120), ""],
    ["Pat Lee", "+1 801 555 0102", "PAT@Example.com", "", "", us(95), "spa"],
    ["Jo Park", "8015550103", "", "", "", us(30), ""],
    ["Kim Diaz", "801-555-0104", "", "", "", us(200), ""],
    ["Lou Grant", "801-555-0105", "", "", "", us(89), ""],
    ["Max Hill", "801-555-0106", "", "", "", us(91), ""],
    ["Ned Wolf", "801-555-0107", "", "", "", us(5), ""],
    ["Oli Moss", "801-555-0108", "", "", "", us(400), ""],
    ["Pia Rand", "801-555-0109", "", "", "", us(60), ""],
    ["Quin Bay", "801-555-0110", "", "", "", us(1), ""],
    ["Ray Cole", "801-555-0111", "", "", "", us(150), ""],
    ["Sue Dunn", "801-555-0112", "", "", "", us(45), ""],
    ["Tim Ford", "801-555-0113", "", "", "", "", ""],
    ["Uma Gale", "801-555-0114", "", "", "", us(20), ""],
    ["Vic Hart", "801-555-0115", "", "", "", us(100), ""],
    ["Wes Ives", "801-555-0116", "", "", "", us(15), ""],
    ["Xia Jett", "801-555-0117", "", "", "", us(70), ""],
    ["Dana R.", "801 555 0134", "", "", "", us(3), ""],       # Dana again, newer visit
    ["Zed Lark", "801-555-0119", "zed@example.com", "", "", us(92), ""],
]
LAPSED = ["Sam Smith", "Pat Lee", "Kim Diaz", "Max Hill", "Oli Moss", "Ray Cole", "Vic Hart", "Zed Lark"]


class CustomerBookTest(unittest.TestCase):
    setUp = test_db.DbTest.setUp
    tearDown = test_db.DbTest.tearDown
    row = test_db.DbTest.row
    register = test_db.DbTest.register
    make_repo = test_db.DbTest.make_repo
    db = test_db.DbTest.db
    calls = test_db.DbTest.calls

    def book(self):
        r = self.db("add", "customers")
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def j(self, *args):
        r = self.db(*args, "--json")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return json.loads(r.stdout)

    def sheet(self, rows=SHEET, name="customers.csv"):
        p = self.ws / "incoming" / name
        p.parent.mkdir(exist_ok=True)
        with open(p, "w", newline="") as f:
            csv.writer(f).writerows(rows)
        return p

    # -- add -------------------------------------------------------------------

    def test_add_wires_both_views_the_pages_and_the_lib(self):
        r = self.book()
        for f in ("migrations/0002_customers.sql", "functions/_admin/customers.js", "functions/_admin/jobs.js",
                  "functions/_lib/customers.js", "functions/admin/customers/[id].js",
                  "functions/admin/customers/import.js", "functions/admin/customers/index.js", "functions/admin/jobs/[id].js"):
            self.assertTrue((self.repo / f).exists(), f)
        self.assertIn("export default { customers, jobs };", (self.repo / "functions/_admin/collections.js").read_text())
        self.assertIn("customers", r.stdout)
        cols = {t: {c["name"] for c in json.loads(self.db("query", f"PRAGMA table_info({t})", "--json").stdout)}
                for t in ("customers", "jobs")}
        self.assertTrue({"name", "phone", "email", "address", "notes", "tags", "last_seen", "created_at", "contact"} <= cols["customers"])
        self.assertTrue({"customer_id", "date", "what", "amount_cents", "status"} <= cols["jobs"])
        # every column a view names is a column of its table
        import re
        for v, t in (("customers", "customers"), ("jobs", "jobs")):
            text = (COLL / "functions" / "_admin" / f"{v}.js").read_text()
            for col in re.findall(r'(?:name: "|\["(?=[a-z_]+", "[A-Z]))([a-z_]+)"', text):
                self.assertIn(col, cols[t], f"{v}: {col}")

    def test_a_named_list_on_records_is_replaced_and_its_rows_move_in(self):
        """demo-service's shape before B122: customers and jobs as named lists on records."""
        self.assertEqual(self.db("add", "records").returncode, 0)
        adm = self.repo / "functions" / "_admin"
        for name, kind in (("customers", "customer"), ("jobs", "job")):
            (adm / f"{name}.js").write_text(f'export default {{ table: "records", filter: {{ kind: "{kind}" }}, title: "{name}", list: [["title", "Name"]] }};\n')
        test_db_views = [("records", "records"), ("customers", "customers"), ("jobs", "jobs")]
        (adm / "collections.js").write_text("".join(f'import {v} from "./{m}.js";\n' for v, m in test_db_views)
                                            + "export default { records, customers, jobs };\n")
        self.db("exec", "INSERT INTO records (kind, title, notes, data) VALUES ('customer', 'Sam Example', 'Mondays', '{\"phone\":\"801-555-0199\"}')")
        self.db("exec", "INSERT INTO records (kind, title, notes) VALUES ('customer', 'Robin Sample', 'Spa only')")
        self.db("exec", "INSERT INTO records (kind, title, status) VALUES ('job', 'Replace pump seal — Sam Example', 'done')")
        self.db("exec", "INSERT INTO records (kind, title, status) VALUES ('job', 'Something with no name', 'open')")
        r = self.book()
        self.assertIn("replaced: it was a list on records", r.stdout)
        self.assertIn('table: "customers"', (adm / "customers.js").read_text())
        self.assertIn('table: "jobs"', (adm / "jobs.js").read_text())
        r = self.db("customers", "import", "--from-records")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("moved 2 customers and 1 job", r.stdout)
        self.assertIn("1 job not moved", r.stdout)
        sam = self.j("customers", "show", "801-555-0199")
        self.assertEqual((sam["name"], sam["notes"]), ("Sam Example", "Mondays"))
        self.assertEqual([(x["what"], x["status"]) for x in sam["jobs"]], [("Replace pump seal", "done")])
        self.assertIn("moved 0 customers and 0 jobs", self.db("customers", "import", "--from-records").stdout, "twice is once")

    def test_a_web_tool_with_the_same_table_name_is_refused(self):
        (self.repo / "migrations" / "0002_jobs.sql").write_text("CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY, title TEXT);\n")
        r = self.db("add", "customers")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("already makes a jobs table", r.stderr)
        self.assertFalse(list((self.repo / "migrations").glob("*_customers.sql")))

    def test_without_the_book_it_says_how(self):
        r = self.db("customers", "find", "Dana")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("db add customers", r.stderr)

    # -- the acceptance, by text ----------------------------------------------

    def test_twenty_row_import_then_who_havent_i_seen_in_90_days(self):
        self.book()
        p = self.sheet()
        r = self.db("customers", "import", str(p), "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("'Mobile' -> phone", r.stdout)
        self.assertIn("'Last Visit' -> last seen", r.stdout)
        self.assertIn("into the notes: 'Pool size'", r.stdout)
        self.assertIn("19 new, 0 already in the book (filled in, never overwritten), 1 repeated in the file (merged)", r.stdout)
        self.assertIn("1 with no date in 'Last Visit'", r.stdout)
        self.assertEqual(self.j("query", "SELECT COUNT(*) AS n FROM customers")[0]["n"], 0, "a dry run writes nothing")
        r = self.db("customers", "import", str(p))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("the book has 19 customers", r.stdout)
        out = self.j("customers", "lapsed")
        self.assertEqual(sorted(c["name"] for c in out["customers"]), sorted(LAPSED))
        self.assertEqual(out["never_seen"], 1)                          # Tim Ford, no date
        text = self.db("customers", "lapsed").stdout
        self.assertIn("8 not seen in 90 days", text)
        self.assertIn("(and 1 with no visit on record", text)
        self.assertNotIn("Lou Grant", text, "89 days is inside 90")
        # the repeat merged into Dana's record, the newer visit won, nothing overwritten
        dana = self.j("customers", "show", "801-555-0134")
        self.assertEqual((dana["name"], dana["email"], dana["last_seen"]), ("Dana Ruiz", "dana@example.com", ago(3)))
        self.assertEqual(dana["address"], "12 Elm, Provo")
        self.assertIn("Pool size: 16x32", dana["notes"])
        # importing the same sheet again adds nobody
        r = self.db("customers", "import", str(p))
        self.assertIn("0 new, 19 already in the book", r.stdout)
        self.assertIn("the book has 19 customers", r.stdout)
        # a job done brings someone back
        self.j("jobs", "add", "Sam Smith", "Filter clean", "--status", "done", "--amount", "85")
        self.assertNotIn("Sam Smith", [c["name"] for c in self.j("customers", "lapsed")["customers"]])
        # and a job booked from today on keeps someone off the list
        self.j("jobs", "add", "Kim Diaz", "Opening", "--date", (TODAY + datetime.timedelta(days=7)).isoformat())
        self.assertNotIn("Kim Diaz", [c["name"] for c in self.j("customers", "lapsed")["customers"]])

    def test_an_excel_sheet_reads_the_same(self):
        try:
            import openpyxl  # noqa: F401
        except ImportError:
            self.skipTest("no openpyxl")
        import openpyxl
        wb = openpyxl.Workbook()
        for r in SHEET[:4]:
            wb.active.append(r)
        p = self.ws / "incoming" / "book.xlsx"
        p.parent.mkdir(exist_ok=True)
        wb.save(p)
        self.book()
        r = self.db("customers", "import", str(p))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("the book has 3 customers", r.stdout)

    def test_a_sheet_with_no_name_phone_or_email_is_refused_with_the_headers(self):
        self.book()
        p = self.sheet([["Pool", "Size"], ["a", "b"]])
        r = self.db("customers", "import", str(p))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Pool, Size", r.stderr)
        r = self.db("import", "customers", str(p))
        self.assertIn("db customers import", r.stderr)

    # -- find / show / add / set -----------------------------------------------

    def test_who_is_a_phone_number_and_when_did_we_last_do_the_smiths(self):
        self.book()
        self.db("customers", "import", str(self.sheet()))
        self.j("jobs", "add", "Sam Smith", "Green-to-clean", "--date", ago(120), "--status", "done", "--amount", "$1,200")
        for term in ("801-555-0101", "(801) 555-0101", "8015550101", "+18015550101", "555-0101", "the Smiths", "smith"):
            got = self.j("customers", "find", term)
            self.assertEqual([c["name"] for c in got], ["Sam Smith"], term)
        got = self.j("customers", "find", "the Smiths")[0]
        self.assertEqual((got["jobs_count"], got["last_job"]["what"], got["last_job"]["amount_cents"]), (1, "Green-to-clean", 120000))
        self.assertEqual(self.j("customers", "find", "pat@EXAMPLE.com")[0]["name"], "Pat Lee")
        self.assertEqual(self.j("customers", "find", "nobody here"), [])
        text = self.db("customers", "find", "801-555-0101").stdout
        self.assertIn("#2 Sam Smith · 801-555-0101", text)
        self.assertIn("last: Green-to-clean", text)

    def test_show_names_one_or_says_which(self):
        self.book()
        self.j("customers", "add", "John Smith", "--phone", "8015550001")
        self.j("customers", "add", "John Smith", "--phone", "8015550002")
        r = self.db("customers", "show", "John Smith", "--json")
        self.assertEqual(r.returncode, 3)
        self.assertEqual(len(json.loads(r.stdout)["matches"]), 2, "a name alone never merges two people")
        r = self.db("customers", "show", "Nobody", "--json")
        self.assertEqual(r.returncode, 4)
        self.assertEqual(self.j("customers", "show", "2")["phone"], "801-555-0002")

    def test_add_matches_by_phone_or_email_and_fills_in(self):
        self.book()
        a = self.j("customers", "add", "Dana Ruiz", "--phone", "(801) 555-0134")
        self.assertTrue(a["created"])
        self.assertEqual((a["customer"]["phone"], a["customer"]["last_seen"]), ("801-555-0134", None))
        b = self.j("customers", "add", "D Ruiz", "--phone", "801.555.0134", "--email", "Dana@Example.com", "--seen", "today")
        self.assertFalse(b["created"])
        self.assertEqual((b["customer"]["name"], b["customer"]["email"], b["customer"]["last_seen"]),
                         ("Dana Ruiz", "dana@example.com", TODAY.isoformat()))
        c = self.j("customers", "add", "Dana", "--email", "dana@example.com")
        self.assertEqual(c["customer"]["id"], a["customer"]["id"])

    def test_set_contact_stop_and_tags(self):
        self.book()
        self.j("customers", "add", "Dana Ruiz", "--phone", "8015550134", "--tags", "weekly")
        c = self.j("customers", "set", "8015550134", "--contact", "stop", "--add-tag", "spa", "--add-tag", "Weekly")["customer"]
        self.assertEqual((c["contact"], c["tags"]), ("stop", "weekly, spa"))
        self.j("jobs", "add", "1", "Old job", "--date", ago(200), "--status", "done")
        self.assertIn("asked not to be contacted", self.db("customers", "lapsed").stdout)
        self.j("customers", "set", "1", "--name", "Dana Ruiz-Lee")
        self.assertEqual(self.j("jobs", "ls", "1")[0]["customer_name"], "Dana Ruiz-Lee")

    # -- jobs ------------------------------------------------------------------

    def test_jobs_add_done_and_the_feeders_ref(self):
        self.book()
        self.j("customers", "add", "Dana Ruiz", "--phone", "8015550134")
        j = self.j("jobs", "add", "Dana", "Weekly service", "--amount", "450")
        self.assertEqual((j["job"]["status"], j["job"]["amount_cents"], j["job"]["date"]), ("booked", 45000, TODAY.isoformat()))
        self.assertIsNone(j["customer"]["last_seen"], "booked is not seen")
        d = self.j("jobs", "done", "Dana")                              # the one booked job
        self.assertEqual(d["job"]["status"], "done")
        self.assertEqual(d["customer"]["last_seen"], TODAY.isoformat())
        r = self.db("jobs", "done", "Dana")
        self.assertEqual(r.returncode, 3)
        self.assertIn("has no booked job", r.stderr)
        # a feeder (an invoice paid, B123/pay) writes once per source+ref
        a = self.j("jobs", "add", "8015550134", "Pump", "--source", "pay", "--ref", "in_1", "--status", "done", "--amount", "300")
        b = self.j("jobs", "add", "8015550134", "Pump (paid)", "--source", "pay", "--ref", "in_1", "--status", "done")
        self.assertEqual(a["job"]["id"], b["job"]["id"])
        self.assertTrue(b["updated"])
        self.assertEqual((b["job"]["what"], b["job"]["amount_cents"]), ("Pump (paid)", 30000))
        # --create: a customer the book hasn't met
        c = self.j("jobs", "add", "new@example.com", "Spa check", "--create", "--name", "Nia New")
        self.assertEqual((c["customer"]["name"], c["customer"]["email"]), ("Nia New", "new@example.com"))
        self.assertEqual(len(self.j("jobs", "ls")), 3)
        x = self.j("jobs", "set", str(c["job"]["id"]), "--status", "cancelled")
        self.assertEqual(x["job"]["status"], "cancelled")

    def test_export_holds_both_tables(self):
        self.book()
        self.j("customers", "add", "Dana Ruiz", "--phone", "8015550134")
        self.j("jobs", "add", "1", "Weekly service", "--status", "done")
        r = self.db("export")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = self.ws / "exports" / TODAY.isoformat()
        for t in ("customers", "jobs"):
            self.assertTrue((out / f"{t}.csv").exists(), t)
        rows = list(csv.DictReader(io.StringIO((out / "jobs.csv").read_text())))
        self.assertEqual((rows[0]["customer_name"], rows[0]["status"]), ("Dana Ruiz", "done"))
        shutil.rmtree(out)
        r = self.db("customers", "export")
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["customers.csv", "customers.json", "jobs.csv", "jobs.json"])

    # -- the site's own Functions ------------------------------------------------

    def test_the_functions_run_a_booking_creates_then_updates_last_seen(self):
        """functions/_lib/customers.js under node on the real migration (node:sqlite as D1):
        a booking's recordCustomer creates the record, a second booking (same phone, other
        spelling) updates last_seen and adds no one; addJob by source+ref writes once; the
        CSV import page reads the owner's headers."""
        node = shutil.which("node")
        if not node:
            self.skipTest("no node")
        probe = subprocess.run([node, "-e", "require('node:sqlite')"], capture_output=True, text=True)
        if probe.returncode != 0:
            self.skipTest("this node has no node:sqlite")
        work = Path(self.tmp.name) / "fn"
        shutil.copytree(test_db.TEMPLATE / "functions", work / "functions")
        shutil.copytree(COLL / "functions", work / "functions", dirs_exist_ok=True)
        (work / "functions" / "_admin" / "collections.js").write_text(
            'import customers from "./customers.js";\nimport jobs from "./jobs.js";\nexport default { customers, jobs };\n')
        mig = (COLL / "migrations" / "0001_customers.sql").read_text()
        (work / "mig.sql").write_text(mig)
        sheet = io.StringIO()
        csv.writer(sheet).writerows(SHEET[:5])
        (work / "sheet.csv").write_text(sheet.getvalue())
        script = work / "run.mjs"
        script.write_text(r"""
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import { recordCustomer, addJob, markDone, findCustomer, phoneKey, phoneShown, parseCsv, mapHeader, customerFromRow, isoDate } from "./functions/_lib/customers.js";
import { onRequestPost as importPost } from "./functions/admin/customers/import.js";
import { onRequestPost as addPost, onRequestGet as listGet } from "./functions/admin/customers/index.js";
import { onRequestPost as jobPost } from "./functions/admin/jobs/[id].js";
import { onRequestGet as showGet, onRequestPost as showPost, cents } from "./functions/admin/customers/[id].js";
const sql = new DatabaseSync(":memory:");
sql.exec(readFileSync("mig.sql", "utf8"));
const norm = (a) => a.map((x) => (x === undefined ? null : x));
const DB = { prepare(q) { const st = { args: [], bind(...a) { st.args = norm(a); return st; },
  async first() { return sql.prepare(q).get(...st.args) ?? null; },
  async all() { return { results: sql.prepare(q).all(...st.args) }; },
  async run() { const r = sql.prepare(q).run(...st.args); return { meta: { changes: Number(r.changes), last_row_id: Number(r.lastInsertRowid) } }; } }; return st; } };
const env = { DB, TIMEZONE: "America/Denver" };
const out = {};
out.keys = [phoneKey("(801) 555-0134"), phoneKey("+1 801 555 0134"), phoneKey("12"), phoneShown("+18015550134"), phoneShown("555-0110")];
out.dates = [isoDate("3/4/2026"), isoDate("2026-03-04"), isoDate("03/04/26"), isoDate("soon")];
out.cents = [cents("$1,200.50"), cents(""), cents("x")];
// the booking side of B119: first booking creates, second (same phone, other spelling) updates
const a = await recordCustomer(env, { name: "Dana Ruiz", phone: "(801) 555-0134", email: "Dana@Example.com", source: "booking", seen: "2026-10-06" });
const b = await recordCustomer(env, { name: "Dana", phone: "801.555.0134", source: "booking", seen: "2026-10-20" });
const c = await recordCustomer(env, { name: "Dana", email: "dana@example.com", source: "booking", seen: "2026-10-01" });
out.booking = [a, b, c, await findCustomer(env, { phone: "8015550134" })];
const j1 = await addJob(env, { customer_id: a.id, date: "2026-10-06", what: "Weekly service", source: "booking", ref: "7" });
const j2 = await addJob(env, { customer_id: a.id, date: "2026-10-07", what: "Weekly service", source: "booking", ref: "7" });
await markDone(env, j1.id);
out.jobs = [j1, j2, sql.prepare("SELECT customer_name, date, status FROM jobs").all(), sql.prepare("SELECT last_seen FROM customers WHERE id = ?").get(a.id)];
// a site without the book: the feeders' calls are quiet no-ops
const bare = { DB: { prepare() { const st = { bind() { return st; }, async first() { return null; } }; return st; } } };
out.bare = [await recordCustomer(bare, { name: "X", phone: "8015550000" }), await addJob(bare, { customer_id: 1, what: "x" })];
// the CSV import page
const head = mapHeader(parseCsv(readFileSync("sheet.csv", "utf8"))[0]);
out.head = head.map;
out.row = customerFromRow(head, parseCsv(readFileSync("sheet.csv", "utf8"))[1]);
const fd = new FormData(); fd.set("text", readFileSync("sheet.csv", "utf8"));
let r = await importPost({ request: new Request("https://s.example/admin/customers/import", { method: "POST", body: fd }), env, data: {} });
out.imported = [r.status, (await r.text()).match(/<p>(\d+ added[^<]*)<\/p>/)[1]];
out.count = sql.prepare("SELECT COUNT(*) AS n FROM customers").get().n;
// the add form on /admin/customers matches by phone: Dana again opens Dana
const form = (o) => new Request("https://s.example/admin/customers", { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(o) });
r = await addPost({ request: form({ name: "Dana again", phone: "801 555 0134" }), env, data: {} });
out.addSame = r.headers.get("location");
// the customer page: add a job, mark it done, the jobs under them
const page = (o) => new Request(`https://s.example/admin/customers/${a.id}`, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams(o) });
await showPost({ request: page({ action: "job", what: "Heater check", date: "2026-11-02", amount: "$125" }), env, params: { id: String(a.id) }, data: {} });
const hid = sql.prepare("SELECT id FROM jobs WHERE what = 'Heater check'").get().id;
await showPost({ request: page({ action: "done", job: String(hid) }), env, params: { id: String(a.id) }, data: {} });
await showPost({ request: page({ action: "edit", name: "Dana Ruiz-Lee", phone: "8015550134", email: "D@X.test", contact: "stop" }), env, params: { id: String(a.id) }, data: {} });
r = await showGet({ env, params: { id: String(a.id) }, data: {} });
const html = await r.text();
out.page = [html.includes("Heater check"), html.includes("$125.00"), html.includes("asked not to be contacted"), html.includes("Dana Ruiz-Lee")];
out.after = sql.prepare("SELECT name, email, contact, last_seen FROM customers WHERE id = ?").get(a.id);
out.names = sql.prepare("SELECT DISTINCT customer_name FROM jobs WHERE customer_id = ?").all(a.id).map((x) => x.customer_name);
// the list: the shell's page with the import link beside the download; a search by phone digits
r = await listGet({ request: new Request("https://s.example/admin/customers?q=8015550101"), env, params: {}, data: {} });
const list = await r.text();
out.list = [r.status, list.includes('href="/admin/customers/import"'), list.includes("Sam Smith"), list.includes("Pat Lee")];
// a job marked done on /admin/jobs (the one-tap button) moves last_seen too
const sam = sql.prepare("SELECT id FROM customers WHERE name = 'Sam Smith'").get().id;
const jid = (await addJob(env, { customer_id: sam, date: "2026-12-01", what: "Close" })).id;
r = await jobPost({ request: new Request(`https://s.example/admin/jobs/${jid}`, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ status: "done" }) }), env, params: { id: String(jid) }, data: {} });
out.jobDone = [r.status, sql.prepare("SELECT status FROM jobs WHERE id = ?").get(jid).status, sql.prepare("SELECT last_seen FROM customers WHERE id = ?").get(sam).last_seen];
console.log(JSON.stringify(out));
""")
        r = subprocess.run([node, "--no-warnings", str(script)], capture_output=True, text=True, cwd=work)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["keys"], ["8015550134", "8015550134", "", "801-555-0134", "555-0110"])
        self.assertEqual(out["dates"], ["2026-03-04", "2026-03-04", "2026-03-04", ""])
        self.assertEqual(out["cents"], [120050, None, None])
        a, b, c, found = out["booking"]
        self.assertEqual((a["created"], b["created"], c["created"]), (True, False, False))
        self.assertEqual(a["id"], b["id"])
        self.assertEqual((found["name"], found["phone"], found["email"], found["last_seen"]),
                         ("Dana Ruiz", "801-555-0134", "dana@example.com", "2026-10-20"), "later wins, never back")
        j1, j2, jobs, seen = out["jobs"]
        self.assertTrue(j1["created"])
        self.assertEqual((j2["id"], j2["created"]), (j1["id"], False), "the same booking is one job")
        self.assertEqual(jobs, [{"customer_name": "Dana Ruiz", "date": "2026-10-07", "status": "done"}])
        self.assertEqual(out["bare"], [None, None])
        self.assertEqual(out["head"], {"name": 0, "phone": 1, "email": 2, "address": 3, "city": 4, "last_seen": 5})
        self.assertEqual(out["row"]["notes"], "Pool size: 16x32")
        self.assertEqual(out["imported"][0], 200)
        self.assertEqual(out["imported"][1], "3 added, 1 already in the book and updated.")
        self.assertEqual(out["count"], 4)
        self.assertTrue(out["addSame"].endswith(f"/admin/customers/{a['id']}"))
        self.assertEqual(out["page"], [True, True, True, True])
        self.assertEqual(out["after"], {"name": "Dana Ruiz-Lee", "email": "d@x.test", "contact": "stop", "last_seen": "2026-11-02"})
        self.assertEqual(out["names"], ["Dana Ruiz-Lee"])
        self.assertEqual(out["list"], [200, True, True, False])
        self.assertEqual(out["jobDone"], [303, "done", "2026-12-01"])


if __name__ == "__main__":
    unittest.main()
