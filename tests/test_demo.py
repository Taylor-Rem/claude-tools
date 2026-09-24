"""demo — which workspaces are demos, and the data half of a reset — no network.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

The reset's database step runs the real `db` against the fake wrangler
(tests/fixtures/db/fake-wrangler: SQLite per database), on the real bookings
and submissions migrations, so what's checked is the SQL a reset sends.
"""

import importlib.machinery
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FAKE = HERE / "fixtures" / "db" / "fake-wrangler"
SHELL = ROOT / "templates" / "sites" / "_shell"
COLLECTIONS = ROOT / "templates" / "collections"


def load_demo():
    loader = importlib.machinery.SourceFileLoader("demo_tool", str(ROOT / "bin" / "demo"))
    spec = importlib.util.spec_from_loader("demo_tool", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class DemoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = Path(self.tmp.name)
        (root / "d1").mkdir()
        (root / "env").write_text("")
        self.clients = root / "clients"
        for slug in ("demo-acme", "testaurant", "james"):
            (self.clients / slug / "repos").mkdir(parents=True)
            (self.clients / slug / ".client.json").write_text(json.dumps({"slug": slug, "name": slug}))
        (self.clients / "demo-nosite").mkdir()                   # no .client.json: not a workspace
        self.ws = self.clients / "demo-acme"
        self.repo = self.ws / "repos" / "demo-acme"
        (self.repo / "migrations").mkdir(parents=True)
        shutil.copy(SHELL / "migrations" / "0001_admin.sql", self.repo / "migrations" / "0001_admin.sql")
        shutil.copy(COLLECTIONS / "bookings" / "migrations" / "0001_bookings.sql", self.repo / "migrations" / "0002_bookings.sql")
        (self.repo / "wrangler.toml").write_text(
            'name = "demo-acme"\n[[d1_databases]]\nbinding = "DB"\ndatabase_name = "demo-acme"\ndatabase_id = "u1"\n')
        (self.repo / "seed.sql").write_text(
            "-- the golden rows; a comment with an apostrophe's fine\n"
            "INSERT INTO booking_slots (starts_at) VALUES (date('now', '+1 day') || 'T09:00');\n"
            "INSERT INTO bookings (slot_id, starts_at, name) SELECT id, starts_at, 'Sam Example' FROM booking_slots;\n")
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        (root / "sites.json").write_text(json.dumps({"demo-acme": {"demo-acme": {
            "host": "cloudflare", "project": "demo-acme", "d1": {"name": "demo-acme", "id": "u1"}}}}))
        self.env = {"CLAUDE_TOOLS_ENV": str(root / "env"), "DB_WRANGLER": str(FAKE), "FAKE_D1_DIR": str(root / "d1"),
                    "FAKE_D1_LOG": str(root / "log.jsonl"), "CLIENTS_DIR": str(self.clients),
                    "DEMO_STATE": str(root / "demo.json")}
        self.old = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.demo = load_demo()

    def tearDown(self):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def sql(self, q):
        con = sqlite3.connect(self.root / "d1" / "demo-acme.remote.sqlite")
        try:
            return con.execute(q).fetchall()
        finally:
            con.close()

    def test_the_demos_are_demo_star_and_testaurant(self):
        self.assertEqual([p.name for p in self.demo.demos()], ["demo-acme", "testaurant"])
        self.assertTrue(self.demo.is_demo("demo-store"))
        self.assertFalse(self.demo.is_demo("james"))

    def test_project_picks_the_workspace_and_refuses_a_client(self):
        self.demo.PROJECT = "demo-acme"
        self.assertEqual(self.demo.workspace()[0], self.ws)
        self.demo.PROJECT = "james"
        with self.assertRaises(SystemExit):
            self.demo.workspace()

    def test_golden_tables_are_read_from_the_migrations(self):
        self.assertEqual(self.demo.golden_tables(self.repo),
                         {"admin_tokens", "admin_sessions", "booking_slots", "bookings"})

    def test_reset_data_puts_back_tables_migrations_and_rows(self):
        self.demo.PROJECT = "demo-acme"
        self.demo.reset_data(self.ws, "demo-acme", self.repo)            # first run: migrate + seed
        self.assertEqual(self.sql("SELECT name FROM bookings"), [("Sam Example",)])
        # a stranger's evening: rows, a new table, a migration golden doesn't have
        con = sqlite3.connect(self.root / "d1" / "demo-acme.remote.sqlite")
        con.executescript("INSERT INTO booking_slots (starts_at) VALUES ('2099-01-06T09:00');"
                          "INSERT INTO bookings (slot_id, starts_at, name) VALUES (2, '2099-01-06T09:00', 'Stranger');"
                          "CREATE TABLE stray (x); INSERT INTO d1_migrations (name) VALUES ('0003_stray.sql');"
                          "INSERT INTO admin_sessions VALUES ('h', 'o@x', 1, 2);")
        con.commit(); con.close()
        counts = self.demo.reset_data(self.ws, "demo-acme", self.repo)
        self.assertEqual(counts, {"booking_slots": 1, "bookings": 1})
        self.assertEqual(self.sql("SELECT name FROM bookings"), [("Sam Example",)])
        self.assertEqual(self.sql("SELECT id FROM booking_slots"), [(1,)], "ids start again at 1")
        self.assertEqual(self.sql("SELECT name FROM sqlite_master WHERE name = 'stray'"), [])
        self.assertEqual([r[0] for r in self.sql("SELECT name FROM d1_migrations ORDER BY id")],
                         ["0001_admin.sql", "0002_bookings.sql"])
        self.assertEqual(self.sql("SELECT COUNT(*) FROM admin_sessions"), [(1,)], "the sign-in bookkeeping is kept")

    def test_a_database_without_a_seed_refuses(self):
        (self.repo / "seed.sql").unlink()
        with self.assertRaises(SystemExit):
            self.demo.reset_data(self.ws, "demo-acme", self.repo)


if __name__ == "__main__":
    unittest.main()
