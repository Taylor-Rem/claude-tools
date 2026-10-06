"""estimate (ROADMAP B123): the estimates collection, `estimate new/send/accept/sync`
against the fake wrangler (D1 as SQLite) and a fake Stripe, the accept page's
Function under node with node:sqlite as D1, and the PDF through print's check.
No network.

    python3 -m unittest tests.test_estimate -q   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402

import importlib.machinery
import importlib.util
import json
import shutil
import subprocess
import sys
import threading
import unittest
from decimal import Decimal
from http.server import HTTPServer
from pathlib import Path

import test_db  # noqa: E402  (its setUp makes a workspace with a site and a database)
import test_pay  # noqa: E402  (the fake Stripe)

ROOT = test_db.ROOT
EST = ROOT / "bin" / "estimate"
COLL = ROOT / "templates" / "collections" / "estimates"
HAVE_PRINT = bool(shutil.which("node") and shutil.which("pdfinfo") and shutil.which("pdftoppm")
                  and (ROOT / "node_modules" / "jsqr").exists())


def load_estimate():
    loader = importlib.machinery.SourceFileLoader("estimate_tool", str(EST))
    spec = importlib.util.spec_from_loader("estimate_tool", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Parsing(unittest.TestCase):
    def test_tax_terms_and_numbers(self):
        E = load_estimate()
        notes = "## Money\n- Sales tax: 7.25% on parts and labour\n"
        self.assertEqual(E.TAX_RE.search(notes).group(1), "7.25")
        self.assertIsNone(E.TAX_RE.search("We don't charge tax.\n"))
        self.assertEqual(E.tax_label(Decimal("7.250")), "Sales tax 7.25%")
        facts = "## Policies\n- Repairs priced first.\n\n## Terms\nHalf up front.\nUpdated: 2026-10-04\n\n## Not offered\nx\n"
        self.assertEqual(E.section(facts, "Terms"), "Half up front.")
        self.assertEqual(E.section(facts, "Policies"), "- Repairs priced first.")
        self.assertEqual(E.long_day("2026-10-19"), "October 19, 2026")
        self.assertEqual([E.number_of(x) for x in ("3", "E-3", "e-0003", "#12")], ["E-0003", "E-0003", "E-0003", "E-0012"])
        self.assertEqual((E.amt(30000), E.amt(2175), E.amt(5)), ("300.00", "21.75", "0.05"))
        self.assertEqual(E.valid_until("14d", E.dt.date(2026, 10, 5)), "2026-10-19")


class EstimateTest(unittest.TestCase):
    row = test_db.DbTest.row
    register = test_db.DbTest.register
    make_repo = test_db.DbTest.make_repo
    db = test_db.DbTest.db
    calls = test_db.DbTest.calls
    tearDown = test_db.DbTest.tearDown

    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), test_pay.Fake)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        test_db.DbTest.setUp(self)
        test_pay.Fake.state = {"sent": [], "rows": {}}
        (self.root / "env").write_text(f"STRIPE_KEY_PATCHLAMP={test_pay.LIVE}\nSTRIPE_TEST_KEY={test_pay.TEST}\n")
        for k in list(self.env):
            if k.startswith(("STRIPE_", "PATCHLAMP_RELAY")):
                self.env.pop(k)
        self.env.update(STRIPE_API_BASE=self.base, STRIPE_CONNECTED_ACCOUNT=test_pay.ACCT, SITES_REGISTRY=str(self.root / "sites.json"))
        (self.ws / "facts.md").write_text("## Policies\n- Repairs are priced before the work starts.\n\n"
                                          "## Terms\nHalf the work's price is due on acceptance.\n")
        self.assertEqual(self.db("add", "estimates").returncode, 0)

    def est(self, *args):
        r = subprocess.run([sys.executable, str(EST), *args], env={**self.env, "ESTIMATE_PROBE": "0"}, cwd=self.ws,
                           capture_output=True, text=True)
        for key in (test_pay.LIVE, test_pay.TEST):
            self.assertNotIn(key, r.stdout + r.stderr, "a key value was printed")
        return r

    def q(self, sql):
        return json.loads(self.db("query", sql, "--json").stdout)

    def test_db_add_estimates_wires_the_view_and_the_accept_page(self):
        reg = (self.repo / "functions" / "_admin" / "collections.js").read_text()
        self.assertIn('import estimates from "./estimates.js";', reg)
        self.assertTrue((self.repo / "functions" / "estimate" / "[token].js").exists())
        cols = {c["name"] for c in self.q("PRAGMA table_info(estimates)")}
        view = (COLL / "functions" / "_admin" / "estimates.js").read_text()
        import re
        for col in re.findall(r'\["([a-z_]+)", "[A-Z]', view) + re.findall(r'name: "([a-z_]+)"', view):
            self.assertIn(col, cols, col)

    def test_new_without_the_collection_says_db_add(self):
        self.db("exec", "DROP TABLE estimates", "--yes")
        r = self.est("new", "Smith", "--line", "x", "10", "--no-pdf")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("db add estimates", r.stderr)

    def test_smith_from_draft_to_invoice_booking_and_book(self):
        self.db("add", "bookings")
        self.db("add", "customers")
        r = self.est("new", "John Smith", "--line", "3 windows", "300", "--line", "2 doors", "150",
                     "--email", "smith@example.com", "--valid", "14d", "--no-pdf")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("E-0001 for John Smith (draft)", r.stdout)
        self.assertIn("total $450.00", r.stdout)
        row = self.q("SELECT * FROM estimates")[0]
        self.assertEqual((row["status"], row["subtotal_cents"], row["tax_cents"], row["total_cents"]), ("draft", 45000, 0, 45000))
        self.assertGreaterEqual(len(row["token"]), 32)
        self.assertEqual(row["terms"], "Half the work's price is due on acceptance.")
        self.assertEqual(json.loads(row["lines"]), [{"what": "3 windows", "cents": 30000}, {"what": "2 doors", "cents": 15000}])
        # a draft can't be followed through, and send --dry-run changes nothing
        self.assertIn("nothing to follow through", self.est("sync").stdout)
        r = self.est("send", "1", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.q("SELECT status FROM estimates")[0]["status"], "draft")
        # send: the page opens, the customer is in the book, the email draft is printed
        r = self.est("send", "E-0001")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"/estimate/{row['token']}", r.stdout)
        self.assertIn("Subject: Estimate E-0001 from Acme Pools", r.stdout)
        sent = self.q("SELECT status, customer_id FROM estimates")[0]
        self.assertEqual(sent["status"], "sent")
        self.assertTrue(sent["customer_id"])
        before = len(self.q("SELECT id FROM customers"))
        self.assertEqual(self.est("send", "E-0001").returncode, 0, "sending again is allowed")
        self.assertEqual(len(self.q("SELECT id FROM customers")), before, "a second send doesn't file them twice")
        # the customer accepts on the page (as the Function would write it)
        self.db("exec", "UPDATE estimates SET status = 'accepted', accepted_name = 'John Smith', "
                        "accepted_at = '2026-10-05T22:00:00Z', accepted_ip = '203.0.113.9'")
        r = self.est("sync", "--test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("invoice FERN-0001", r.stdout)
        calls = [c for c in test_pay.Fake.state["sent"] if c["path"].startswith("/v1/")]
        items = [c["body"] for c in calls if c["path"] == "/v1/invoiceitems"]
        self.assertEqual([(i["description"], i["amount"]) for i in items], [("3 windows", "30000"), ("2 doors", "15000")])
        inv = next(c for c in calls if c["path"] == "/v1/invoices" and c["method"] == "POST")
        self.assertEqual(inv["body"]["metadata[ref]"], "E-0001")
        self.assertTrue(all(c["auth"] == f"Bearer {test_pay.TEST}" for c in calls), "test key only")
        self.assertTrue(all(c["account"] == test_pay.ACCT for c in calls))
        self.assertEqual(inv["idem"], f"estimate-E-0001-{row['token']}:/v1/invoices:0", "one key per estimate: no second bill")
        self.assertIn("move it to a time", r.stdout)
        done = self.q("SELECT invoice_id, invoice_url, booking_id, job_id, followed_at FROM estimates")[0]
        self.assertEqual(done["invoice_id"], "in_1")
        self.assertIsNone(done["booking_id"], "no booking without a time")
        self.assertEqual(self.q("SELECT id FROM bookings"), [])
        self.assertTrue(done["job_id"] and done["followed_at"])
        job = self.q("SELECT what, amount_cents, status, source, ref, customer_id FROM jobs")
        self.assertEqual([j["customer_id"] for j in job], [sent["customer_id"]], "the job is on the customer send filed")
        self.assertEqual(len(self.q("SELECT id FROM customers")), before, "and no second John Smith")
        self.assertEqual([(j["amount_cents"], j["status"], j["source"], j["ref"]) for j in job], [(45000, "booked", "estimate", "E-0001")])
        # the owner moves the job on; no later sync touches it, and nothing is billed twice
        self.db("exec", f"UPDATE jobs SET status = 'done', date = '2026-10-01' WHERE id = {done['job_id']}")
        n = len(test_pay.Fake.state["sent"])
        self.assertIn("nothing to follow through", self.est("sync", "--test").stdout)
        r = self.est("sync", "E-0001", "--test")
        self.assertIn("filed already", r.stdout)
        self.assertEqual(len(test_pay.Fake.state["sent"]), n)
        self.assertEqual([(j["status"], j["date"]) for j in self.q("SELECT status, date FROM jobs")], [("done", "2026-10-01")])
        # the time, once agreed: a booking at it, on a slot of its own that is full the moment it's made
        self.assertIn("a time like 2026-10-12 09:00", self.est("sync", "E-0001", "--when", "next tuesday").stderr)
        r = self.est("sync", "E-0001", "--when", "2026-10-12 09:00", "--test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("booking #1 at 2026-10-12 09:00", r.stdout)
        b = self.q("SELECT b.name, b.status, b.starts_at, b.notes, s.capacity, s.status AS slot FROM bookings b "
                   "JOIN booking_slots s ON s.id = b.slot_id")
        self.assertEqual([(x["name"], x["status"], x["starts_at"], x["capacity"], x["slot"]) for x in b],
                         [("John Smith", "requested", "2026-10-12T09:00", 1, "open")])
        self.assertIn("booking #1 already", self.est("sync", "E-0001", "--when", "2026-10-13 09:00", "--test").stdout)
        self.assertEqual(len(self.q("SELECT id FROM bookings")), 1)

    def test_a_phone_acceptance_with_no_contact_files_one_customer_and_the_job_once(self):
        """B123 review: no bookings on the site, a name-only customer, two syncs."""
        self.db("add", "customers")
        self.est("new", "Pat Lee", "--line", "Heater", "1000", "--deposit", "250", "--no-pdf")
        r = self.est("accept", "1", "--name", "Pat Lee", "--by", "phone", "--test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("deposit link", r.stdout)
        self.assertIn("balance ($750.00) is the owner's to invoice", r.stdout)
        self.assertIn("no bookings", r.stdout)
        row = self.q("SELECT job_id, customer_id, followed_at FROM estimates")[0]
        self.assertTrue(row["job_id"] and row["customer_id"] and row["followed_at"], (r.stdout, row))
        self.db("exec", "UPDATE jobs SET status = 'done', date = '2026-10-01'")
        self.est("sync", "--test")
        self.est("sync", "1", "--test")
        self.assertEqual(len(self.q("SELECT id FROM customers WHERE name = 'Pat Lee'")), 1)
        self.assertEqual([(j["status"], j["date"]) for j in self.q("SELECT status, date FROM jobs")], [("done", "2026-10-01")])

    def test_amounts_that_arent_money_and_a_total_past_stripes_limit_are_refused(self):
        self.db("add", "customers")
        for bad in ("Infinity", "NaN", "-5"):
            r = self.est("new", "X", "--line", "a", bad, "--no-pdf")
            self.assertNotEqual(r.returncode, 0)
            self.assertNotIn("Traceback", r.stderr)
        r = self.est("new", "X", "--line", "a", "600000", "--line", "b", "500000", "--no-pdf")
        self.assertIn("more than one Stripe payment", r.stderr)

    def test_an_invoice_waits_for_an_email_and_sync_email_adds_it(self):
        """Stripe refuses a sent invoice to a customer with no email (found on demo-service, 2026-10-06)."""
        r = self.est("new", "Pat Lee", "--line", "Pump repair", "200", "--no-pdf")
        self.assertIn("no email for them", r.stdout)
        self.est("send", "1")
        self.db("exec", "UPDATE estimates SET status = 'accepted', accepted_name = 'Pat Lee', accepted_at = '2026-10-06T10:00:00Z'")
        r = self.est("sync", "--test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("needs Pat Lee's email", r.stdout)
        self.assertEqual([c for c in test_pay.Fake.state["sent"] if c["path"].startswith("/v1/")], [], "no Stripe call")
        self.assertIn("isn't an email", self.est("sync", "1", "--email", "nope", "--test").stderr)
        r = self.est("sync", "E-0001", "--email", "pat@example.com", "--test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("invoice FERN-0001", r.stdout)
        self.assertEqual(self.q("SELECT email FROM estimates")[0]["email"], "pat@example.com")

    def test_a_deposit_is_a_deposit_link_and_tax_comes_from_notes(self):
        (self.ws / "NOTES.md").write_text("Sales tax: 7.25%\n")
        r = self.est("new", "Lee", "--line", "Heater", "1000", "--deposit", "250", "--no-pdf")
        self.assertEqual(r.returncode, 0, r.stderr)
        row = self.q("SELECT tax_label, tax_cents, total_cents, deposit_cents FROM estimates")[0]
        self.assertEqual((row["tax_label"], row["tax_cents"], row["total_cents"], row["deposit_cents"]),
                         ("Sales tax 7.25%", 7250, 107250, 25000))
        r = self.est("accept", "1", "--name", "Pat Lee", "--by", "phone", "--test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("deposit link, $250.00 (TEST MODE)", r.stdout)
        self.assertIn("this site has no bookings", r.stdout)
        posts = [c for c in test_pay.Fake.state["sent"] if c["method"] == "POST"]
        self.assertEqual([c["path"] for c in posts], ["/v1/prices", "/v1/payment_links"])
        self.assertEqual(posts[0]["body"]["unit_amount"], "25000")
        acc = self.q("SELECT status, accepted_name, accepted_ip FROM estimates")[0]
        self.assertEqual((acc["status"], acc["accepted_name"], acc["accepted_ip"]), ("accepted", "Pat Lee", "recorded by the owner: phone"))

    def test_refusals(self):
        r = self.est("new", "Smith", "--line", "x", "100", "--deposit", "200", "--no-pdf")
        self.assertIn("more than the total", r.stderr)
        r = self.est("new", "Smith", "--line", "x", "abc", "--no-pdf")
        self.assertIn("isn't an amount", r.stderr)
        r = self.est("new", "Smith", "--no-pdf")
        self.assertIn("needs lines", r.stderr)
        self.est("new", "Smith", "--line", "x", "100", "--no-pdf")
        self.assertIn("void", self.est("void", "1").stdout)
        self.assertNotEqual(self.est("send", "1").returncode, 0)
        r = self.est("new", "Smith", "--line", "x", "100", "--dry-run")
        self.assertIn("nothing written", r.stdout)
        self.assertEqual(len(self.q("SELECT id FROM estimates")), 1)

    def test_a_failed_stripe_call_leaves_it_for_the_next_sync(self):
        self.env["STRIPE_CONNECTED_ACCOUNT"] = "not-an-account"
        self.est("new", "Smith", "--line", "x", "100", "--email", "s@example.com", "--no-pdf")
        self.db("exec", "UPDATE estimates SET status = 'accepted', accepted_name = 'S'")
        r = self.est("sync", "--test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("money: couldn't", r.stdout)
        self.assertIsNone(self.q("SELECT invoice_id FROM estimates")[0]["invoice_id"])
        self.assertIn("not followed through", self.est("ls").stdout)

    @unittest.skipUnless(HAVE_PRINT, "node/jsqr or poppler-utils missing")
    def test_the_pdf_passes_prints_check_and_its_qr_reads_the_accept_link(self):
        (self.root / "sites.json").write_text(json.dumps({"acme": {"acme-site": {
            **self.row("acme-site", "uuid-1"), "pages_host": "acme-site.pages.dev"}}}))
        r = self.est("new", "John Smith", "--line", "3 windows", "300", "--line", "2 doors", "150",
                     "--note", "Thanks for having us out.")
        self.assertEqual(r.returncode, 0, r.stderr)
        token = self.q("SELECT token FROM estimates")[0]["token"]
        self.assertIn(f"QR 1/1 reads https://acme-site.pages.dev/estimate/{token}", r.stdout)
        self.assertIn("page 8.5 x 11 in", r.stdout)
        pdf = Path(r.stdout.strip().splitlines()[-1])
        self.assertTrue(pdf.exists() and pdf.suffix == ".pdf")
        text = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True).stdout
        for s in ("E-0001", "John Smith", "3 windows", "$450.00", "Half the work's price is due on acceptance."):
            self.assertIn(s, text)


@unittest.skipUnless(shutil.which("node"), "no node")
class AcceptPage(unittest.TestCase):
    def test_the_page_records_the_name_time_and_ip_once(self):
        node = shutil.which("node")
        if subprocess.run([node, "-e", "require('node:sqlite')"], capture_output=True).returncode != 0:
            self.skipTest("this node has no node:sqlite")
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            shutil.copytree(test_db.TEMPLATE / "functions", work / "functions")
            shutil.copytree(COLL / "functions", work / "functions", dirs_exist_ok=True)
            (work / "mig.sql").write_text((COLL / "migrations" / "0001_estimates.sql").read_text())
            (work / "run.mjs").write_text(r"""
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import { onRequestGet, onRequestPost } from "./functions/estimate/[token].js";
const sql = new DatabaseSync(":memory:");
sql.exec(readFileSync("mig.sql", "utf8"));
const norm = (a) => a.map((x) => (x === undefined ? null : x));
const DB = { prepare(q) { const st = { args: [], bind(...a) { st.args = norm(a); return st; },
  async first() { return sql.prepare(q).get(...st.args) ?? null; },
  async all() { return { results: sql.prepare(q).all(...st.args) }; },
  async run() { const r = sql.prepare(q).run(...st.args); return { meta: { changes: Number(r.changes) } }; } }; return st; } };
const forwarded = [];
let down = false;
globalThis.fetch = async (url, init) => { if (down) return new Response("{}", { status: 503 });
  forwarded.push([url, Object.fromEntries(new URLSearchParams(init.body))]); return new Response("{}", { status: 201 }); };
const env = { DB, TIMEZONE: "America/Denver", PATCHLAMP_SLUG: "acme" };
const T = "tok_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", D = "tok_dddddddddddddddddddddddddddddd", X = "tok_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx";
const ins = sql.prepare("INSERT INTO estimates (number, token, business, customer, lines, subtotal_cents, total_cents, deposit_cents, valid_until, terms, status) VALUES (?, ?, 'Acme Pools', 'John Smith', ?, 45000, 45000, 0, ?, 'Half up front.', ?)");
const lines = JSON.stringify([{ what: "3 windows", cents: 30000 }, { what: "2 <b>doors</b>", cents: 15000 }]);
ins.run("E-0001", T, lines, "2099-01-01", "sent");
ins.run("E-0002", D, lines, "2099-01-01", "draft");
ins.run("E-0003", X, lines, "2020-01-01", "sent");
const P = "tok_pppppppppppppppppppppppppppppp";
ins.run("E-0004", P, lines, "2099-01-01", "sent");
sql.prepare("UPDATE estimates SET deposit_cents = 10000 WHERE token = ?").run(P);
const waits = [];
const ctx = (token, req) => ({ request: req, env, params: { token }, waitUntil: (p) => waits.push(p) });
const get = async (token) => { const r = await onRequestGet(ctx(token, new Request(`https://s.example/estimate/${token}`))); return [r.status, await r.text()]; };
const post = async (token, body, origin = "https://s.example") => {
  const r = await onRequestPost(ctx(token, new Request(`https://s.example/estimate/${token}`, { method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded", origin, "cf-connecting-ip": "203.0.113.9", "user-agent": "UA" },
    body: new URLSearchParams(body) }))); return [r.status, await r.text()]; };
const out = {};
let [s, h] = await get(T);
out.open = [s, h.includes("3 windows"), h.includes("$450.00"), h.includes("Accept estimate"), h.includes("&lt;b&gt;doors"), h.includes("Half up front."), h.includes("noindex")];
out.draft = (await get(D))[0];
out.unknown = (await get("short"))[0];
out.expired = [(await get(X))[1].includes("can't be accepted here any more"), (await post(X, { name: "John Smith" }))[1].includes("can't be accepted")];
out.foreign = (await post(T, { name: "John Smith" }, "https://evil.example"))[0];
out.noName = (await post(T, { name: " " }))[1].includes("Type your full name");
out.honeypot = await post(T, { name: "Bot", website: "x" });
out.afterBot = sql.prepare("SELECT status FROM estimates WHERE token = ?").get(T).status;
[s, h] = await post(T, { name: "  John   Smith " });
await Promise.all(waits);
out.accepted = [s, h.includes("Accepted by John Smith"), h.includes("Accept estimate"), h.includes("Acme Pools has been told")];
out.depositPage = (await get(P))[1].includes("Acme Pools invoices the rest");
down = true;
[s, h] = await post(P, { name: "Pat Lee" });
out.notTold = [h.includes("has been told"), h.includes("Save this page; Acme Pools will confirm")];
out.row = sql.prepare("SELECT status, accepted_name, accepted_ip, accepted_agent, accepted_at FROM estimates WHERE token = ?").get(T);
await post(T, { name: "Someone Else" });
out.again = sql.prepare("SELECT accepted_name FROM estimates WHERE token = ?").get(T).accepted_name;
out.forwarded = forwarded;
console.log(JSON.stringify(out));
""")
            r = subprocess.run([node, "--no-warnings", "run.mjs"], capture_output=True, text=True, cwd=work)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["open"], [200, True, True, True, True, True, True])
        self.assertEqual((out["draft"], out["unknown"]), (404, 404), "a draft or a wrong token is not found")
        self.assertEqual(out["expired"], [True, True])
        self.assertEqual(out["foreign"], 403)
        self.assertTrue(out["noName"])
        self.assertEqual(out["afterBot"], "sent", "the honeypot accepts nothing")
        self.assertEqual(out["accepted"], [200, True, False, True])
        self.assertTrue(out["depositPage"], "the balance is the business's to invoice, as it is")
        self.assertEqual(out["notTold"], [False, True], "told only when patchlamp.com took the forward")
        row = out["row"]
        self.assertEqual((row["status"], row["accepted_name"], row["accepted_ip"], row["accepted_agent"]),
                         ("accepted", "John Smith", "203.0.113.9", "UA"))
        self.assertRegex(row["accepted_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(out["again"], "John Smith", "accepted once")
        self.assertEqual(len(out["forwarded"]), 1)
        url, fields = out["forwarded"][0]
        self.assertEqual(url, "https://patchlamp.com/f/acme/estimate-accepted")
        self.assertNotIn("email", fields, "no customer address, so nothing answers the customer automatically")
        self.assertEqual((fields["estimate"], fields["accepted_by"], fields["total"]), ("E-0001", "John Smith", "$450.00"))


if __name__ == "__main__":
    unittest.main()
