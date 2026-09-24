"""db, the data-layer half of site, and client doctor's binding check — no network.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

DB_WRANGLER points db at tests/fixtures/db/fake-wrangler, which runs the SQL
on a SQLite file per database (D1 is SQLite) and logs each call, so these
check real SQL against the real migrations and Functions files in
templates/. The site registry and the toolbelt env are temp files.
"""

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
TEMPLATE = ROOT / "templates" / "site"


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
        return {"host": "cloudflare", "project": name, "d1": {"name": name, "id": db_id, "owner": "owner@acme.test"}}

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
        for name in ("bookings", "catalog", "orders", "posts", "subscribers"):
            r = self.db("add", name)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("scaffold", r.stderr)
        self.assertFalse((self.repo / "migrations" / "0002_bookings.sql").exists())

    def test_collections_lists_ready_scaffold_and_added(self):
        self.db("add", "submissions")
        out = self.db("collections").stdout
        self.assertRegex(out, r"submissions\s+added")
        self.assertRegex(out, r"bookings\s+scaffold")
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
            shutil.copy(TEMPLATE / f, repo / f)
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
