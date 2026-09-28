"""Web tools (ROADMAP B40) and the admin console (B41) — no network.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

The /admin shell's list and entry pages run under node against a stand-in
D1 made of node:sqlite (real SQL, the real migrations and views); `db add
--from-sheet` and `db tools` run on test_db's fake-wrangler workspace;
`site shell`'s drift and `client doctor`'s view check on plain folders.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_db  # noqa: E402  (its workspace setup; its tests stay in its own module)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SHELL = ROOT / "templates" / "sites" / "_shell"
TOOLS = ROOT / "templates" / "tools"
COLL = ROOT / "templates" / "collections"
NODE = shutil.which("node")

D1 = r"""
import { DatabaseSync } from "node:sqlite";
export function d1(db) {
  return { prepare(sql) { const st = { args: [], bind(...a) { st.args = a; return st; },
    async all() { return { results: db.prepare(sql).all(...st.args) }; },
    async first() { return db.prepare(sql).get(...st.args) ?? null; },
    async run() { const r = db.prepare(sql).run(...st.args); return { meta: { changes: Number(r.changes), last_row_id: Number(r.lastInsertRowid) } }; } }; return st; },
    async batch(sts) { return Promise.all(sts.map((s) => s.run())); } };
}
export function open(files) { const db = new DatabaseSync(":memory:"); for (const f of files) db.exec(f); return db; }
"""


@unittest.skipUnless(NODE, "no node")
class AdminShell(unittest.TestCase):
    """The list page: search, status pills, totals, CSV, sort, choosers, shortcuts, one-tap status."""

    def run_js(self, views, sql_files, body):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        work = Path(tmp.name)
        shutil.copytree(SHELL / "functions", work / "functions")
        for mod, src in views.items():
            shutil.copy(src, work / "functions" / "_admin" / f"{mod}.js")
        (work / "functions" / "_admin" / "collections.js").write_text(
            "".join(f'import {m} from "./{m}.js";\n' for m in views) + f"export default {{ {', '.join(views)} }};\n")
        (work / "d1.mjs").write_text(D1)
        (work / "run.mjs").write_text(
            'import fs from "node:fs";\nimport { d1, open } from "./d1.mjs";\n'
            'import { onRequestGet as list } from "./functions/admin/[collection]/index.js";\n'
            'import { onRequestPost as save, onRequestGet as one } from "./functions/admin/[collection]/[id].js";\n'
            f"const db = open({json.dumps([Path(f).read_text() for f in sql_files])});\n"
            'const env = { DB: d1(db), TIMEZONE: "America/Denver", SITE_NAME: "Test" };\n'
            'const get = async (c, q = "") => { const r = await list({ request: new Request(`https://x.test/admin/${c}${q}`), env, params: { collection: c }, data: { session: {} } }); return { status: r.status, type: r.headers.get("content-type"), rp: r.headers.get("referrer-policy"), text: await r.text() }; };\n'
            "const totals = (t) => (t.match(/class=\"totals\">([^<]*)/) || [])[1];\n"
            "const out = {};\n" + body + "\nconsole.log(JSON.stringify(out));\n")
        r = subprocess.run([NODE, "--no-warnings", "run.mjs"], cwd=work, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_submissions_search_filter_totals_csv_sort(self):
        out = self.run_js({"submissions": COLL / "submissions/functions/_admin/submissions.js"},
                          [COLL / "submissions/migrations/0001_submissions.sql"], r"""
db.exec(`INSERT INTO submissions (form, name, email, message, status) VALUES
  ('quote', 'Jordan Placeholder', 'j@example.com', '=HYPERLINK("x")', 'new'),
  ('quote', 'Casey Demo', 'c@example.com', 'pump, loud', 'replied'),
  ('quote', 'Sam Example', 's@example.com', 'heater', 'new')`);
let r = await get("submissions");
out.all = totals(r.text); out.rp = r.rp;
out.phone = r.text.includes('data-label="Name"') && r.text.includes("@media (max-width: 40rem)");
r = await get("submissions", "?q=casey");
out.search = [...r.text.matchAll(/data-label="Name">([^<]*)/g)].map((m) => m[1]);
r = await get("submissions", "?q=50%25_");
out.likeEscaped = r.text.includes("No submissions match");
r = await get("submissions", "?status=new");
out.status = [...r.text.matchAll(/data-label="Name">([^<]*)/g)].map((m) => m[1]);
out.pill = /aria-current="true">new <span>2/.test(r.text);
r = await get("submissions", "?sort=name&dir=asc");
out.sorted = [...r.text.matchAll(/data-label="Name">([^<]*)/g)].map((m) => m[1]);
r = await get("submissions", "?sortby=name%20desc");
out.phoneSort = [...r.text.matchAll(/data-label="Name">([^<]*)/g)].map((m) => m[1]);
r = await get("submissions", "?status=new&format=csv");
out.csvType = r.type; out.csv = r.text;
r = await get("submissions", "?sort=bogus;drop");
out.badSort = r.status;
""")
        self.assertEqual(out["all"], "3 submissions · 2 new · 1 replied")
        self.assertEqual(out["rp"], "same-origin", "no-referrer makes the browser send Origin: null and every POST is refused")
        self.assertTrue(out["phone"])
        self.assertEqual(out["search"], ["Casey Demo"])
        self.assertTrue(out["likeEscaped"])
        self.assertEqual(out["status"], ["Sam Example", "Jordan Placeholder"])
        self.assertTrue(out["pill"])
        self.assertEqual(out["sorted"], ["Casey Demo", "Jordan Placeholder", "Sam Example"])
        self.assertEqual(out["phoneSort"], ["Sam Example", "Jordan Placeholder", "Casey Demo"])
        self.assertTrue(out["csvType"].startswith("text/csv"))
        lines = out["csv"].strip().split("\r\n")
        self.assertEqual(lines[0].split(",")[:3], ["id", "form", "name"], "every column, as db export writes them")
        self.assertEqual(len(lines), 3, "only the filtered rows")
        self.assertIn(",\"'=HYPERLINK(\"\"x\"\")\",", out["csv"], "a formula from a public form stays text")
        self.assertEqual(out["badSort"], 200)

    def test_routes_opens_on_today_and_one_tap_marks_a_stop(self):
        t = TOOLS / "routes"
        out = self.run_js({"routes": t / "functions/_admin/routes.js"},
                          [t / "migrations/0001_routes.sql", t / "seed.sql"], r"""
let r = await get("routes");
out.today = totals(r.text);
out.picked = (r.text.match(/<option value="[^"]*" selected>([^<]*)/) || [])[1];
out.order = [...r.text.matchAll(/data-label="Stop">([^<]*)/g)].map((m) => m[1]);
r = await get("routes", "?day=");
out.week = totals(r.text);
const id = db.prepare("SELECT id FROM routes WHERE status = 'to do' AND day = date('now', '-6 hours') ORDER BY stop LIMIT 1").get().id;
const res = await save({ request: new Request(`https://x.test/admin/routes/${id}`, { method: "POST", body: new URLSearchParams({ status: "done", back: "/admin/routes?day=" }) }), env, params: { collection: "routes", id: String(id) }, data: {} });
out.back = res.headers.get("location");
out.row = db.prepare("SELECT status, updated_at IS NOT NULL AS touched FROM routes WHERE id = ?").get(id);
const evil = await save({ request: new Request(`https://x.test/admin/routes/${id}`, { method: "POST", body: new URLSearchParams({ status: "gone", back: "https://evil.example/" }) }), env, params: { collection: "routes", id: String(id) }, data: {} });
out.evil = [evil.headers.get("location"), db.prepare("SELECT status FROM routes WHERE id = ?").get(id).status];
r = await get("routes");
out.after = totals(r.text);
const page = await (await one({ env, params: { collection: "routes", id: String(id) }, data: {} })).text();
out.taps = [...page.matchAll(/<button type="submit">Mark ([^<]*)/g)].map((m) => m[1]);
out.editNamed = page.includes('name="notes"') && page.includes('name="stop"');
""")
        self.assertEqual(out["today"], "7 stops · 3 to do · 3 done · 1 skipped")
        self.assertEqual(out["picked"], "Today")
        self.assertEqual(out["order"], ["1", "2", "3", "4", "5", "6", "7"])
        self.assertEqual(out["week"], "16 stops · 8 to do · 6 done · 2 skipped")
        self.assertEqual(out["back"], "/admin/routes?day=")
        self.assertEqual(out["row"], {"status": "done", "touched": 1})
        self.assertEqual(out["evil"][1], "done", "a status the view doesn't have is ignored")
        self.assertTrue(out["evil"][0].startswith("/admin/routes/"), "back only ever returns to this list")
        self.assertEqual(out["after"], "7 stops · 2 to do · 4 done · 1 skipped")
        self.assertEqual(out["taps"], ["to do", "skipped"])
        self.assertTrue(out["editNamed"])

    def test_stock_shortcut_money_and_a_count_named_at(self):
        t = TOOLS / "stock"
        out = self.run_js({"stock": t / "functions/_admin/stock.js"},
                          [t / "migrations/0001_stock.sql", t / "seed.sql"], r"""
let r = await get("stock", "?only=below%20reorder");
out.below = [...r.text.matchAll(/data-label="Item"><a[^>]*>([^<]*)/g)].map((m) => m[1]);
out.pill = /aria-current="true">below reorder <span>6/.test(r.text);
out.reorderCell = (r.text.match(/data-label="Reorder at">([^<]*)/) || [])[1];
r = await get("stock", "?only=anything-else");
out.unknownIgnored = totals(r.text);
const page = await (await one({ env, params: { collection: "stock", id: "1" }, data: {} })).text();
out.money = /<dt>unit cost<\/dt><dd>\$6\.40<\/dd>/.test(page);
""")
        self.assertEqual(out["below"], ["Brown Butter Bakery 8 oz", "Fernhill Signature 14 oz", "Long matches (box)",
                                        "Morning Orchard 8 oz", "Soy wax (10 lb bag)", "Tins 4 oz (24)"])
        self.assertTrue(out["pill"])
        self.assertEqual(out["reorderCell"], "10", "reorder_at is a number, not a 1970 date")
        self.assertEqual(out["unknownIgnored"], "14 items · 14 stocked")
        self.assertTrue(out["money"])


class SheetToTool(unittest.TestCase):
    """db add NAME --from-sheet and db tools, on test_db's fake-wrangler workspace."""

    setUp = test_db.DbTest.setUp
    tearDown = test_db.DbTest.tearDown
    row, register, make_repo, db, calls = (test_db.DbTest.row, test_db.DbTest.register, test_db.DbTest.make_repo,
                                           test_db.DbTest.db, test_db.DbTest.calls)

    def sheet(self):
        dest = self.ws / "incoming" / "fernhill-stock.xlsx"
        dest.parent.mkdir(exist_ok=True)
        shutil.copy(TOOLS / "stock" / "fernhill-stock.xlsx", dest)
        return "incoming/fernhill-stock.xlsx"

    def test_dry_run_says_the_mapping_and_writes_nothing(self):
        r = self.db("add", "stock", "--from-sheet", self.sheet(), "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Unit cost     ->  unit_cost_cents (money", r.stdout)
        self.assertIn("On hand       ->  on_hand (whole number)", r.stdout)
        self.assertIn("Last counted  ->  last_counted (date)", r.stdout)
        self.assertIn('"below reorder" (on_hand < reorder_at)', r.stdout)
        self.assertIn("dry run: nothing written", r.stdout)
        self.assertFalse(list((self.repo / "migrations").glob("*_stock.sql")))
        self.assertFalse((self.repo / "functions" / "_admin" / "stock.js").exists())

    def test_from_sheet_makes_the_fixture_registers_migrates_and_imports(self):
        r = self.db("add", "stock", "--from-sheet", self.sheet(), "--title", "Stock", "--singular", "item",
                    "--statuses", "stocked,discontinued")
        self.assertEqual(r.returncode, 0, r.stderr)
        mig = next((self.repo / "migrations").glob("*_stock.sql"))
        self.assertEqual(mig.read_text(), (TOOLS / "stock/migrations/0001_stock.sql").read_text(),
                         "the kept fixture is exactly what the command makes")
        view = (self.repo / "functions/_admin/stock.js").read_text()
        self.assertEqual(view, (TOOLS / "stock/functions/_admin/stock.js").read_text())
        self.assertLessEqual(len(view.splitlines()), 24, "the descriptor stays small; the shell does the work")
        self.assertIn('import stock from "./stock.js";', (self.repo / "functions/_admin/collections.js").read_text())
        q = self.db("query", "SELECT COUNT(*) AS n, SUM(on_hand < reorder_at) AS below, MAX(unit_cost_cents) AS top FROM stock", "--json")
        self.assertEqual(json.loads(q.stdout), [{"n": 14, "below": 6, "top": 3200}])
        again = self.db("add", "stock", "--from-sheet", self.sheet())
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("already has a stock", again.stderr)
        t = self.db("tools")
        self.assertEqual(t.returncode, 0, t.stderr)
        self.assertRegex(t.stdout, r"stock\s+tool\s+Stock \(table stock\)\s+/admin/stock\s+14 rows")

    def test_a_csv_works_and_names_are_checked(self):
        csvf = self.ws / "incoming" / "jobs.csv"
        csvf.parent.mkdir(exist_ok=True)
        csvf.write_text("Job,Status,Total,Date\nFence,open,120.50,2026-09-01\nGate,done,80,2026-09-02\n")
        self.assertNotEqual(self.db("add", "Bad-Name", "--from-sheet", "incoming/jobs.csv").returncode, 0)
        self.assertIn("standard collection", self.db("add", "records", "--from-sheet", "incoming/jobs.csv").stderr)
        r = self.db("add", "job_log", "--from-sheet", "incoming/jobs.csv")
        self.assertEqual(r.returncode, 0, r.stderr)
        view = (self.repo / "functions/_admin/job_log.js").read_text()
        self.assertIn('statuses: ["open", "done"]', view, "a Status column's values are the statuses")
        self.assertIn('sum: ["total_cents"]', view, "a total is added up on the totals line")
        q = self.db("query", "SELECT job, status, total_cents FROM job_log ORDER BY id", "--json")
        self.assertEqual(json.loads(q.stdout), [{"job": "Fence", "status": "open", "total_cents": 12050},
                                                {"job": "Gate", "status": "done", "total_cents": 8000}])


class ShellAndDoctor(unittest.TestCase):
    def test_site_shell_drift_ignores_the_sites_own_views(self):
        site = test_db.load_site()
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            shutil.copytree(SHELL / "functions", repo / "functions")
            (repo / "functions/_admin/collections.js").write_text("export default {};\n// the site's own\n")
            self.assertEqual(site.shell_drift(repo), [])
            (repo / "functions/_lib/core.js").write_text("// old\n")
            (repo / "functions/admin/logout.js").unlink()
            self.assertEqual(site.shell_drift(repo), ["functions/_lib/core.js", "functions/admin/logout.js"])

    def test_client_doctor_knows_a_bespoke_view(self):
        from importlib.machinery import SourceFileLoader
        import importlib.util
        loader = SourceFileLoader("client_tool", str(ROOT / "bin" / "client"))
        spec = importlib.util.spec_from_loader("client_tool", loader)
        client = importlib.util.module_from_spec(spec)
        loader.exec_module(client)
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            adm = repo / "functions/_admin"
            adm.mkdir(parents=True)
            shutil.copy(COLL / "submissions/functions/_admin/submissions.js", adm)
            shutil.copy(TOOLS / "routes/functions/_admin/routes.js", adm)
            (adm / "customers.js").write_text('export default { table: "records", filter: { kind: "customer" } };\n')
            (adm / "collections.js").write_text('import submissions from "./submissions.js";\nimport customers from "./customers.js";\n'
                                                'import routes from "./routes.js";\nimport gone from "./gone.js";\n'
                                                "export default { submissions, customers, routes, gone };\n")
            views, missing = client.admin_views(repo)
            self.assertEqual(views, [("submissions", "collection"), ("customers", "named list"), ("routes", "tool")])
            self.assertEqual(missing, ["gone"])


if __name__ == "__main__":
    unittest.main()
