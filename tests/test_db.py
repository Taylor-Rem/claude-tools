"""db, the data-layer half of site, and client doctor's binding check — no network.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

DB_WRANGLER points db at tests/fixtures/db/fake-wrangler, which runs the SQL
on a SQLite file per database (D1 is SQLite) and logs each call, so these
check real SQL against the real migrations and Functions files in
templates/. The site registry and the toolbelt env are temp files.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import datetime
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB = ROOT / "bin" / "db"
CLIENT = ROOT / "bin" / "client"
FAKE = HERE / "fixtures" / "db" / "fake-wrangler"
TEMPLATE = ROOT / "templates" / "sites" / "_shell"


def load_site():
    loader = importlib.machinery.SourceFileLoader("site_tool", str(ROOT / "bin" / "site"))
    spec = importlib.util.spec_from_loader("site_tool", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def toml(name, db_id):
    return (f'name = "{name}"\npages_build_output_dir = "."\ncompatibility_date = "2026-09-01"\n\n'
            f'[vars]\nPATCHLAMP_SLUG = "acme"\n\n'
            f'[[d1_databases]]\nbinding = "DB"\ndatabase_name = "{name}"\ndatabase_id = "{db_id}"\n')


class DbTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        (root / "d1").mkdir()
        (root / "env").write_text("")
        self.log = root / "wrangler.jsonl"
        self.clients = root / "clients"
        self.ws = self.clients / "acme"
        self.env = dict(os.environ, CLAUDE_TOOLS_ENV=str(root / "env"), DB_WRANGLER=str(FAKE),
                        FAKE_D1_DIR=str(root / "d1"), FAKE_D1_LOG=str(self.log), CLIENTS_DIR=str(self.clients),
                        RELAY_CONFIG=str(root / "no-config.json"))
        for k in ("CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"):
            self.env.pop(k, None)
        r = subprocess.run([str(CLIENT), "new", "acme", "--name", "Acme Pools", "--shared-key"], env=self.env,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        meta = json.loads((self.ws / ".client.json").read_text())
        meta["contact_email"] = "owner@acme.test"
        (self.ws / ".client.json").write_text(json.dumps(meta))
        self.repo = self.make_repo("acme-site", "uuid-1")
        self.register({"acme-site": self.row("acme-site", "uuid-1")})

    def tearDown(self):
        self.tmp.cleanup()

    def row(self, name, db_id):
        return {"host": "cloudflare", "project": name, "remote": f"git@github.com:acme/{name}.git", "d1": {"name": name, "id": db_id, "owner": "owner@acme.test"}}

    def register(self, rows):
        (self.root / "sites.json").write_text(json.dumps({"acme": rows}))

    def make_repo(self, name, db_id):
        repo = self.ws / "repos" / name
        repo.mkdir(parents=True)
        for part in ("functions", "migrations"):
            shutil.copytree(TEMPLATE / part, repo / part)
        (repo / "wrangler.toml").write_text(toml(name, db_id))
        (repo / "index.html").write_text("<h1>Acme</h1>")
        (repo / "CLAUDE.md").write_text("site manual")
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", f"git@github.com:acme/{name}.git"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                        "--allow-empty", "-m", "start"], check=True)
        return repo

    def db(self, *args):
        return subprocess.run([sys.executable, str(DB), *args], env=self.env, cwd=self.ws, capture_output=True, text=True)

    def calls(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    # -- migrate ---------------------------------------------------------------

    def test_migrate_applies_in_order_once_and_records_like_wrangler(self):
        r = self.db("migrate")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("applied 0001_admin.sql to D1 acme-site", r.stdout)
        r = self.db("migrate")
        self.assertIn("all 1 migration(s) applied", r.stdout)
        names = json.loads(self.db("query", "SELECT name FROM d1_migrations", "--json").stdout)
        self.assertEqual([n["name"] for n in names], ["0001_admin.sql"])
        call = self.calls()[0]
        self.assertEqual(call["args"][:4], ["d1", "execute", "acme-site", "--remote"])
        self.assertEqual(Path(call["cwd"]).resolve(), self.repo.resolve())      # the repo's wrangler.toml, nothing else

    def test_migrate_dry_run_prints_the_sql_and_writes_nothing(self):
        r = self.db("migrate", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-- would apply 0001_admin.sql", r.stdout)
        self.assertIn("CREATE TABLE IF NOT EXISTS admin_tokens", r.stdout)
        self.assertEqual(json.loads(self.db("query", "SELECT COUNT(*) AS n FROM sqlite_master", "--json").stdout)[0]["n"], 0)

    def test_local_is_a_separate_copy(self):
        self.db("migrate", "--local")
        self.assertIn("--local", self.calls()[0]["args"])
        self.assertIn("1 migration(s) applied", self.db("migrate", "--local").stdout)
        self.assertIn("applied 0001_admin.sql", self.db("migrate").stdout)

    # -- collections -----------------------------------------------------------

    def test_add_submissions_copies_numbers_wires_and_migrates(self):
        r = self.db("add", "submissions")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.repo / "migrations" / "0002_submissions.sql").exists())
        self.assertTrue((self.repo / "functions" / "api" / "submissions.js").exists())
        self.assertTrue((self.repo / "functions" / "_admin" / "submissions.js").exists())
        reg = (self.repo / "functions" / "_admin" / "collections.js").read_text()
        self.assertIn('import submissions from "./submissions.js";', reg)
        self.assertIn("export default { submissions };", reg)
        self.assertIn("applied 0002_submissions.sql", r.stdout)
        self.assertIn('action="/api/submissions"', r.stdout)                  # the form to paste
        # a second collection keeps the first in /admin; adding again changes nothing
        self.assertEqual(self.db("add", "records").returncode, 0)
        reg = (self.repo / "functions" / "_admin" / "collections.js").read_text()
        self.assertIn("export default { submissions, records };", reg)
        self.assertTrue((self.repo / "migrations" / "0003_records.sql").exists())
        r = self.db("add", "submissions")
        self.assertIn("already in", r.stdout)
        self.assertFalse((self.repo / "migrations" / "0004_submissions.sql").exists())

    def test_a_scaffold_is_refused_so_nothing_is_promised_from_it(self):
        for name in ("posts", "subscribers"):
            r = self.db("add", name)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("scaffold", r.stderr)
        self.assertFalse((self.repo / "migrations" / "0002_posts.sql").exists())

    def test_collections_lists_ready_scaffold_and_added(self):
        self.db("add", "submissions")
        out = self.db("collections").stdout
        self.assertRegex(out, r"submissions\s+added")
        self.assertRegex(out, r"posts\s+scaffold")
        self.assertRegex(out, r"bookings\s{2,}times the owner opens")
        self.assertRegex(out, r"records\s{2,}the generic list")

    def test_the_submissions_function_and_view_match_the_table(self):
        """The columns the Function inserts and the view lists exist in the migration."""
        self.db("add", "submissions")
        cols = {c["name"] for c in json.loads(self.db("query", "PRAGMA table_info(submissions)", "--json").stdout)}
        fn = (self.repo / "functions" / "api" / "submissions.js").read_text()
        self.assertIn("INSERT INTO submissions (form, name, email, phone, message, fields, ip_hash)", fn)
        self.assertTrue({"form", "name", "email", "phone", "message", "fields", "ip_hash", "status", "notes",
                         "created_at", "updated_at"} <= cols)
        view = (self.repo / "functions" / "_admin" / "submissions.js").read_text()
        for col in ("created_at", "name", "email", "form", "status", "notes", "updated_at"):
            self.assertIn(f'"{col}"', view)

    def test_add_bookings_wires_both_views_and_prints_the_calendar(self):
        r = self.db("add", "bookings")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.repo / "migrations" / "0002_bookings.sql").exists())
        self.assertTrue((self.repo / "functions" / "api" / "bookings.js").exists())
        reg = (self.repo / "functions" / "_admin" / "collections.js").read_text()
        self.assertIn("export default { bookings, slots };", reg)
        self.assertIn('action="/api/bookings"', r.stdout)                     # the calendar to paste
        self.assertIn('id="book"', r.stdout)
        cols = {c["name"] for c in json.loads(self.db("query", "PRAGMA table_info(booking_slots)", "--json").stdout)}
        self.assertTrue({"starts_at", "minutes", "capacity", "label", "status"} <= cols)
        r = self.db("exec", "INSERT INTO booking_slots (starts_at, minutes, capacity) VALUES ('2099-10-06T09:00', 60, 1)")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_bookings_function_checks_capacity_in_one_statement(self):
        """The SQL in functions/api/bookings.js, run on the real migration: the
        last place can be taken once, a closed or past slot not at all, and a
        cancelled booking frees its place."""
        import re as _re
        import sqlite3
        src = ROOT / "templates" / "collections" / "bookings"
        fn = (src / "functions" / "api" / "bookings.js").read_text()
        taken = _re.search(r'const TAKEN = "([^"]+)"', fn).group(1)
        sqls = [x.replace("${TAKEN}", taken) for x in _re.findall(r"prepare\(\s*`([^`]+)`", fn)]
        listing = next(x for x in sqls if x.lstrip().startswith("SELECT * FROM ("))
        insert = next(x for x in sqls if x.lstrip().startswith("INSERT INTO bookings"))
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript((next((src / "migrations").glob("*.sql"))).read_text())
        now, later = "2026-10-01T08:00", "2026-11-30T08:00"
        con.execute("INSERT INTO booking_slots (starts_at, capacity) VALUES ('2026-10-06T09:00', 2)")      # 1
        con.execute("INSERT INTO booking_slots (starts_at, status) VALUES ('2026-10-07T09:00', 'closed')")  # 2
        con.execute("INSERT INTO booking_slots (starts_at) VALUES ('2026-09-01T09:00')")                   # 3, past
        book = lambda slot: con.execute(insert, ("Dana", "d@x.test", None, None, None, slot, now)).rowcount
        self.assertEqual([dict(r)["id"] for r in con.execute(listing, (now, later))], [1])
        self.assertEqual(book(1), 1)
        self.assertEqual(dict(con.execute(listing, (now, later)).fetchone())["places"], 1)
        self.assertEqual(book(1), 1)
        self.assertEqual(book(1), 0, "full")
        self.assertEqual(list(con.execute(listing, (now, later))), [], "a full slot is left off the calendar")
        self.assertEqual((book(2), book(3), book(99)), (0, 0, 0), "closed, past, no such slot")
        con.execute("UPDATE bookings SET status = 'cancelled' WHERE id = 1")
        self.assertEqual(book(1), 1, "a cancelled booking frees its place")
        row = con.execute("SELECT slot_id, starts_at, name FROM bookings ORDER BY id DESC").fetchone()
        self.assertEqual(tuple(row), (1, "2026-10-06T09:00", "Dana"))
        view = (src / "functions" / "_admin" / "bookings.js").read_text() + (src / "functions" / "_admin" / "slots.js").read_text()
        cols = {r["name"] for t in ("bookings", "booking_slots") for r in con.execute(f"PRAGMA table_info({t})")}
        for col in _re.findall(r'(?:name: "|\["(?=[a-z_]+", "[A-Z]))([a-z_]+)"', view):
            self.assertIn(col, cols, col)

    def test_add_catalog_wires_products_hours_orders_and_prints_the_shop(self):
        r = self.db("add", "catalog")
        self.assertEqual(r.returncode, 0, r.stderr)
        for m in ("0002_catalog.sql", "0003_orders.sql"):
            self.assertTrue((self.repo / "migrations" / m).exists(), m)
        reg = (self.repo / "functions" / "_admin" / "collections.js").read_text()
        self.assertIn("export default { catalog, hours, orders };", reg)
        self.assertIn("data-shop", r.stdout)
        cols = {t: {c["name"] for c in json.loads(self.db("query", f"PRAGMA table_info({t})", "--json").stdout)}
                for t in ("products", "hours", "orders")}
        import re as _re
        src = ROOT / "templates" / "collections" / "catalog" / "functions"
        views = {"catalog": "products", "hours": "hours", "orders": "orders"}
        for v, table in views.items():
            text = (src / "_admin" / f"{v}.js").read_text()
            for col in _re.findall(r'(?:name: "|\["(?=[a-z_]+", "[A-Z]))([a-z_]+)"', text):
                self.assertIn(col, cols[table], f"{v}: {col}")
        ins = (src / "api" / "checkout.js").read_text()
        m = _re.search(r"INSERT INTO orders \(([^)]+)\)", ins)
        self.assertTrue({c.strip() for c in m.group(1).split(",")} <= cols["orders"])

    def test_the_catalog_functions_run(self):
        """checkout.js and stripe-webhook.js under node, with a stand-in D1 and
        Stripe: prices come from the database, no key means 'off', and only a
        correctly signed, fresh event marks an order paid."""
        node = shutil.which("node")
        if not node:
            self.skipTest("no node")
        work = Path(self.tmp.name) / "fn"
        shutil.copytree(TEMPLATE / "functions", work / "functions")
        shutil.copytree(ROOT / "templates" / "collections" / "catalog" / "functions", work / "functions", dirs_exist_ok=True)
        script = work / "run.mjs"
        script.write_text(r"""
import { onRequestPost as checkout } from "./functions/api/checkout.js";
import { onRequestGet as catalog, checkoutMode } from "./functions/api/catalog.js";
import { onRequestPost as hook, verify } from "./functions/api/stripe-webhook.js";
import { createHmac } from "node:crypto";
const out = {}; const runs = [];
const db = { prepare(sql) { const st = { args: [], bind(...a) { st.args = a; return st; },
  async first() { runs.push([sql, st.args]); return { n: 0 }; },
  async all() { runs.push([sql, st.args]); if (/FROM products/.test(sql) && /IN \(/.test(sql)) return { results: [{ id: 3, name: "Pho", price_cents: 1400 }] };
    if (/FROM products/.test(sql)) return { results: [{ id: 3, name: "Pho", price_cents: 1400, status: "on sale" }] }; return { results: [0,1,2,3,4,5,6].map((d) => ({ weekday: d, opens: "00:00", closes: "23:59" })) }; },
  async run() { runs.push([sql, st.args]); return { meta: { changes: 1, last_row_id: 1 } }; } }; return st; } };
let stripeBody = null;
globalThis.fetch = async (url, init) => { stripeBody = init.body.toString(); return new Response(JSON.stringify({ id: "cs_test_1", url: "https://checkout.stripe.com/x" }), { status: 200 }); };
const req = (body, headers = {}) => new Request("https://shop.example/api/checkout", { method: "POST", headers: { "content-type": "application/json", ...headers }, body });
let r = await checkout({ request: req(JSON.stringify({ items: [{ id: 3, qty: 2 }], name: "Sam", email: "s@x.test" })), env: { DB: db } });
out.off = [r.status, (await r.json()).checkout];
const env = { DB: db, STRIPE_SECRET_KEY: "sk_test_abc", STRIPE_WEBHOOK_SECRET: "whsec_1", TIMEZONE: "America/Denver" };
out.mode = [checkoutMode({}), checkoutMode(env), checkoutMode({ STRIPE_SECRET_KEY: "sk_live_x" })];
r = await checkout({ request: req(JSON.stringify({ items: [{ id: 3, qty: 2, price_cents: 1 }], name: "Sam", email: "s@x.test" })), env });
out.ok = await r.json();
out.stripe = Object.fromEntries(new URLSearchParams(stripeBody));
out.order = runs.find(([s]) => s.startsWith("INSERT INTO orders"))[1];
r = await checkout({ request: req(JSON.stringify({ items: [], name: "Sam", email: "s@x.test" })), env });
out.empty = r.status;
r = await catalog({ env }); out.catalog = await r.json();
const payload = JSON.stringify({ type: "checkout.session.completed", data: { object: { id: "cs_test_1", payment_status: "paid", amount_total: 2800, customer_details: { email: "s@x.test" } } } });
const t = Math.floor(Date.now() / 1000);
const sig = (secret, at) => `t=${at},v1=` + createHmac("sha256", secret).update(`${at}.${payload}`).digest("hex");
out.verify = [await verify(payload, sig("whsec_1", t), "whsec_1"), await verify(payload, sig("whsec_2", t), "whsec_1"),
              await verify(payload, sig("whsec_1", t - 600), "whsec_1"), await verify(payload, "", "whsec_1")];
runs.length = 0;
r = await hook({ request: new Request("https://shop.example/api/stripe-webhook", { method: "POST", headers: { "stripe-signature": sig("whsec_1", t) }, body: payload }), env });
out.hook = [r.status, runs.map(([s, a]) => [s.slice(0, 30), a[a.length - 1]])];
r = await hook({ request: new Request("https://shop.example/api/stripe-webhook", { method: "POST", headers: { "stripe-signature": sig("nope", t) }, body: payload }), env });
out.forged = r.status;
console.log(JSON.stringify(out));
""")
        r = subprocess.run([node, str(script)], capture_output=True, text=True, cwd=work)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["off"], [503, "off"])
        self.assertEqual(out["mode"], ["off", "test", "live"])
        self.assertEqual(out["ok"]["url"], "https://checkout.stripe.com/x")
        self.assertEqual(out["stripe"]["line_items[0][price_data][unit_amount]"], "1400", "the price is the database's")
        self.assertEqual(out["stripe"]["line_items[0][quantity]"], "2")
        self.assertEqual(out["stripe"]["mode"], "payment")
        self.assertEqual(out["order"][0], "cs_test_1")
        self.assertEqual(out["order"][6], 2800)
        self.assertEqual(out["empty"], 422)
        self.assertEqual(out["catalog"]["checkout"], "test")
        self.assertTrue(out["catalog"]["open_now"])
        self.assertEqual(out["verify"], [True, False, False, False])
        self.assertEqual(out["hook"][0], 200)
        self.assertEqual(out["hook"][1], [["UPDATE orders SET status = 'pa", "cs_test_1"]])
        self.assertEqual(out["forged"], 400)

    # -- read / write ----------------------------------------------------------

    def test_query_only_reads_and_exec_guards_the_dangerous_ones(self):
        self.db("add", "submissions")
        r = self.db("query", "DELETE FROM submissions")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("only reads", r.stderr)
        self.assertNotEqual(self.db("query", "SELECT 1; DROP TABLE submissions").returncode, 0)
        r = self.db("exec", "INSERT INTO submissions (form, name) VALUES ('quote', 'O''Brien')")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 row changed", r.stdout)
        self.assertIn("O'Brien", self.db("query", "SELECT name FROM submissions").stdout)
        for bad in ("DROP TABLE submissions", "DELETE FROM submissions", "DELETE FROM d1_migrations WHERE id = 1"):
            r = self.db("exec", bad)
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertIn("--yes", r.stderr)
        self.assertEqual(self.db("exec", "DELETE FROM submissions WHERE name = 'nobody'").returncode, 0)
        r = self.db("exec", "DROP TABLE submissions", "--dry-run", "--yes")
        self.assertIn("-- would run", r.stdout)
        self.assertIn("O'Brien", self.db("query", "SELECT name FROM submissions").stdout)
        self.assertEqual(self.db("exec", "DELETE FROM submissions", "--yes").returncode, 0)
        self.assertIn("(no rows)", self.db("query", "SELECT * FROM submissions").stdout)

    def test_export_writes_csv_and_json_per_table_without_the_sign_in_tables(self):
        self.db("add", "submissions")
        self.db("exec", "INSERT INTO submissions (form, name, email, fields) VALUES ('quote', 'Dana', 'd@x.test', '{\"size\":\"large\"}')")
        self.db("exec", "INSERT INTO admin_tokens (token_hash, email, created_at, expires_at) VALUES ('h', 'o', 1, 2)")
        r = self.db("export")
        self.assertEqual(r.returncode, 0, r.stderr)
        day = self.ws / "exports" / datetime.date.today().isoformat()
        csv_text = (day / "submissions.csv").read_text()
        self.assertTrue(csv_text.startswith("id,form,name,email,phone,message,fields,status,notes,ip_hash,created_at,updated_at"))
        self.assertIn("Dana", csv_text)
        self.assertEqual(json.loads((day / "submissions.json").read_text())[0]["email"], "d@x.test")
        self.assertFalse((day / "admin_tokens.csv").exists())
        self.assertFalse((day / "d1_migrations.csv").exists())

    def test_import_csv_and_json_into_a_table(self):
        self.db("add", "records")
        (self.ws / "incoming").mkdir(exist_ok=True)
        (self.ws / "incoming" / "c.csv").write_text("kind,title,notes\ncustomer,Dana Ruiz,Tuesdays\ncustomer,Lee O'Neil,\n")
        r = self.db("import", "records", "incoming/c.csv", "--dry-run")
        self.assertIn("dry run: 2 row(s)", r.stdout)
        self.assertEqual(self.db("import", "records", "incoming/c.csv").returncode, 0)
        (self.ws / "incoming" / "j.json").write_text(json.dumps([{"kind": "job", "title": "Heater", "data": {"size": 3}}]))
        self.assertEqual(self.db("import", "records", "incoming/j.json").returncode, 0)
        rows = json.loads(self.db("query", "SELECT kind, title, notes, data FROM records ORDER BY id", "--json").stdout)
        self.assertEqual([r["title"] for r in rows], ["Dana Ruiz", "Lee O'Neil", "Heater"])
        self.assertIsNone(rows[1]["notes"])
        self.assertEqual(json.loads(rows[2]["data"]), {"size": 3})
        (self.ws / "incoming" / "bad.csv").write_text("title,colour\nx,red\n")
        r = self.db("import", "records", "incoming/bad.csv")
        self.assertIn("no column(s) colour", r.stderr)

    # -- which database --------------------------------------------------------

    def test_a_workspace_without_a_database_is_told_how_to_get_one(self):
        self.register({"acme-site": {"host": "cloudflare", "project": "acme-site"}})
        r = self.db("query", "SELECT 1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("site data", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_two_sites_need_site_and_it_must_be_one_of_ours(self):
        self.make_repo("acme-shop", "uuid-2")
        self.register({"acme-site": self.row("acme-site", "uuid-1"), "acme-shop": self.row("acme-shop", "uuid-2")})
        r = self.db("query", "SELECT 1")
        self.assertIn("--site", r.stderr)
        self.assertEqual(self.db("migrate", "--site", "acme-shop").returncode, 0)
        self.assertEqual(self.calls()[0]["args"][2], "acme-shop")
        r = self.db("query", "SELECT 1", "--site", "someone-else")
        self.assertIn("isn't one of this workspace's sites", r.stderr)

    def test_outside_a_workspace_it_refuses(self):
        r = subprocess.run([sys.executable, str(DB), "query", "SELECT 1"], env=self.env, cwd=self.root,
                           capture_output=True, text=True)
        self.assertIn("not in a client workspace", r.stderr)

    # -- doctors ---------------------------------------------------------------

    def test_db_doctor_green_then_red_on_unapplied_or_mismatched(self):
        self.db("migrate")
        r = self.db("doctor")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("binding: wrangler.toml DB = the registry's database", r.stdout)
        self.assertIn("migrations: 1 in the repo, 1 applied", r.stdout)
        self.db("add", "submissions", "--no-migrate")
        r = self.db("doctor")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not applied: 0002_submissions.sql", r.stdout)
        self.db("migrate")
        (self.repo / "wrangler.toml").write_text(toml("acme-site", "uuid-OTHER"))
        r = self.db("doctor")
        self.assertIn("the registry says acme-site (uuid-1)", r.stdout)

    def test_client_doctor_checks_the_binding_against_sites_json(self):
        run = lambda: subprocess.run([str(CLIENT), "doctor", "acme"], env=self.env, capture_output=True, text=True)
        r = run()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("database acme-site bound as DB", r.stdout)
        (self.repo / "wrangler.toml").write_text(toml("acme-site", "uuid-OTHER"))
        r = run()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("FAIL repo acme-site: database binding", r.stdout)
        (self.repo / "wrangler.toml").unlink()
        self.assertIn("has no wrangler.toml", run().stdout)
        self.register({"acme-site": {"host": "cloudflare", "project": "acme-site"}})
        r = run()
        self.assertIn("functions/ but no database in sites.json", r.stdout)

    def test_the_client_allowlist_has_db_and_client_doctor_still_passes_it(self):
        allow = json.loads((self.ws / ".claude" / "settings.json").read_text())["permissions"]["allow"]
        self.assertIn("Bash(db *)", allow)
        self.assertIn("`db`", (self.ws / "CLAUDE.md").read_text())
        self.assertIn("## Data: a list they can see and sign in to", (self.ws / "PLAYBOOK.md").read_text())
        subprocess.run([str(CLIENT), "new", "acme", "--restamp", "--shared-key"], env=self.env, capture_output=True)
        self.assertEqual(json.loads((self.ws / ".client.json").read_text())["contact_email"], "owner@acme.test")


class SitePublishLayout(unittest.TestCase):
    """What `site publish` uploads for a site with a database."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.site = load_site()
        repo = self.root / "repo"
        repo.mkdir()
        shutil.copytree(TEMPLATE / "functions", repo / "functions")
        shutil.copytree(TEMPLATE / "migrations", repo / "migrations")
        for f in ("index.html", "404.html", "_headers", "CLAUDE.md", "README.md"):
            shutil.copy(ROOT / "templates" / "sites" / "business" / f, repo / f)
        (repo / "wrangler.toml").write_text(toml("acme-site", "uuid-1"))
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x"], check=True)
        self.repo = repo

    def tearDown(self):
        self.tmp.cleanup()

    def test_functions_and_binding_go_beside_the_pages_never_among_them(self):
        stage = self.root / "stage"
        (stage / "public").mkdir(parents=True)
        self.site.export_tree(self.repo, stage / "public", server=stage)
        self.assertTrue((stage / "functions" / "admin" / "_middleware.js").exists())
        self.assertTrue((stage / "functions" / "_lib" / "core.js").exists())
        conf = (stage / "wrangler.toml").read_text()
        self.assertIn('pages_build_output_dir = "public"', conf)
        self.assertIn('database_id = "uuid-1"', conf)
        pub = stage / "public"
        self.assertTrue((pub / "index.html").exists())
        for gone in ("functions", "migrations", "wrangler.toml", "CLAUDE.md"):
            self.assertFalse((pub / gone).exists(), gone)

    def test_a_static_site_uploads_no_functions_and_no_binding(self):
        out = self.root / "out"
        out.mkdir()
        self.site.export_tree(self.repo, out)
        self.assertFalse((out / "functions").exists())
        self.assertFalse((out / "wrangler.toml").exists())

    def test_binding_problem(self):
        entry = {"d1": {"name": "acme-site", "id": "uuid-1"}}
        self.assertIsNone(self.site.binding_problem(self.repo, entry))
        self.assertIn("registry has no database", self.site.binding_problem(self.repo, {}))
        self.assertIn("uuid-2", self.site.binding_problem(self.repo, {"d1": {"name": "acme-site", "id": "uuid-2"}}))

    def test_the_generated_wrangler_toml_parses_and_binds(self):
        import tomllib
        conf = tomllib.loads(self.site.wrangler_toml("acme-site", {"slug": "acme", "name": 'Acme "Pools"'}, "acme-site", "uuid-9"))
        self.assertEqual(conf["d1_databases"], [{"binding": "DB", "database_name": "acme-site", "database_id": "uuid-9"}])
        self.assertEqual(conf["vars"]["PATCHLAMP_SLUG"], "acme")
        self.assertEqual(conf["vars"]["SITE_NAME"], 'Acme "Pools"')

    def test_site_new_leaves_the_data_parts_out_of_a_plain_site(self):
        """The template carries functions/ and migrations/, but only `site data` copies them."""
        self.assertIn("functions", self.site.DATA_PARTS)
        self.assertIn("migrations", self.site.DATA_PARTS)
        self.assertTrue((TEMPLATE / "functions" / "admin" / "_middleware.js").exists())
        for p in (TEMPLATE / "functions").rglob("*.js"):
            self.assertNotIn("{{", p.read_text(), p)                          # `site new` fills {{…}}; JS must not trip it


if __name__ == "__main__":
    unittest.main()
