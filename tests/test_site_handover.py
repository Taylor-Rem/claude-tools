"""`site handover` — leaving Patchlamp in an hour (ROADMAP B69) — no network.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

What's pinned: one command puts everything that is the client's into
handover/<date>/ and one zip beside it — the site as a zip and as a git
bundle with its history, the database export, the mailing list as CSV, the
conversations as one HTML page, memory.md, the schedules, and a README of
what runs where — and prints the zip's path last for SEND-FILE. Every file in
the bundle opens. A demo's bundle carries only the asker's own conversation
and none of the shared notes. A tool that fails is a PROBLEM line and the
bundle still comes. The zip goes to the account page with the relay secret,
never for a demo. git, db, newsletter and chats are faked.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import argparse
import contextlib
import csv
import http.server
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_site():
    loader = importlib.machinery.SourceFileLoader("site_tool_handover", str(ROOT / "bin" / "site"))
    spec = importlib.util.spec_from_loader("site_tool_handover", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


FAKE_DB = """#!/usr/bin/env python3
import datetime, json, os, sys
from pathlib import Path
open(os.environ["FAKE_LOG"], "a").write("db " + " ".join(sys.argv[1:]) + "\\n")
d = Path("exports") / datetime.date.today().isoformat()
d.mkdir(parents=True, exist_ok=True)
(d / "bookings.csv").write_text("id,name\\n1,Sam Example\\n")
(d / "bookings.json").write_text(json.dumps([{"id": 1, "name": "Sam Example"}]))
print("exported 1 table")
"""

FAKE_NEWSLETTER = """#!/usr/bin/env python3
import json, os, sys
open(os.environ["FAKE_LOG"], "a").write("newsletter " + " ".join(sys.argv[1:]) + "\\n")
if os.environ.get("FAKE_NEWSLETTER") == "none":
    sys.stderr.write("newsletter: this project isn't registered on patchlamp.com yet: run `newsletter setup` first\\n")
    sys.exit(1)
if os.environ.get("FAKE_NEWSLETTER") == "error":
    sys.stderr.write("newsletter: GET /x/newsletter/subscribers: Server Error\\n")
    sys.exit(1)
print(json.dumps([{"email": "a@example.com", "created_at": "2026-09-01", "unsubscribed": False},
                  {"email": "b@example.com", "created_at": "2026-09-02", "unsubscribed": False}]))
"""

FAKE_CHATS = """#!/usr/bin/env python3
import os, sys
open(os.environ["FAKE_LOG"], "a").write("chats " + " ".join(sys.argv[1:]) + "\\n")
out = sys.argv[sys.argv.index("--out") + 1]
open(out, "w").write("<!doctype html><html><body><img src='data:image/jpeg;base64,/9j/'>hi</body></html>")
print(out)
"""


def run(*cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


class HandoverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.site = load_site()
        self.log = self.tmp / "calls.log"
        self.log.write_text("")
        bins = self.tmp / "bin"
        bins.mkdir()
        for name, body in (("db", FAKE_DB), ("newsletter", FAKE_NEWSLETTER), ("chats", FAKE_CHATS)):
            p = bins / name
            p.write_text(body)
            p.chmod(0o755)
        self.site.DB_BIN, self.site.NEWSLETTER_BIN, self.site.CHATS_BIN = bins / "db", bins / "newsletter", bins / "chats"
        self.site.ENV_FILE = self.tmp / "env"
        self.site.REGISTRY = self.tmp / "sites.json"
        self.site.RELAY_DIR = self.tmp / "relay"
        (self.tmp / "relay" / "state").mkdir(parents=True)
        (self.tmp / "relay" / "state" / "schedules.json").write_text(json.dumps({"jobs": [
            {"id": "s1", "project": "acme", "human": "Mondays 8am", "cron": "0 8 * * 1", "tz": "America/Denver",
             "text": "@weekly-report", "kind": "weekly", "state": "active", "sender_key": "sms:+1"},
            {"id": "s2", "project": "acme", "human": "daily 9am", "cron": "0 9 * * *", "text": "old", "state": "stopped"},
            {"id": "s3", "project": "other", "human": "daily", "cron": "0 9 * * *", "text": "not theirs", "state": "active"},
        ]}))
        self.env = {"FAKE_LOG": str(self.log)}
        self._old_env = {k: os.environ.get(k) for k in ("FAKE_LOG", "FAKE_NEWSLETTER", "RELAY_SENDER_KEY",
                                                         "PATCHLAMP_RELAY_SHARED_SECRET", "PATCHLAMP_URL")}
        os.environ.update(self.env)
        for k in ("FAKE_NEWSLETTER", "RELAY_SENDER_KEY", "PATCHLAMP_RELAY_SHARED_SECRET", "PATCHLAMP_URL"):
            os.environ.pop(k, None)
        self._cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self._cwd)
        for k, v in self._old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def workspace(self, slug="acme", db=True, memory=True):
        ws = self.tmp / "clients" / slug
        repo = ws / "repos" / f"{slug}-site"
        repo.mkdir(parents=True)
        (ws / ".client.json").write_text(json.dumps({"slug": slug, "name": "Acme Pools"}))
        if memory:
            (ws / "memory.md").write_text("## The business\nAcme Pools, Provo.\n")
        (repo / "index.html").write_text("<h1>Acme</h1>")
        run("git", "init", "-q", "-b", "main", cwd=repo)
        run("git", "-c", "user.email=t@example.com", "-c", "user.name=t", "add", ".", cwd=repo)
        run("git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "first", cwd=repo)
        run("git", "remote", "add", "origin", f"https://github.com/patchlamp/{slug}-site.git", cwd=repo)
        row = {"host": "cloudflare", "project": f"{slug}-site", "domains": ["acmepools.com"]}
        if db:
            row["d1"] = {"name": f"{slug}-site", "id": "x"}
        self.site.REGISTRY.write_text(json.dumps({slug: {f"{slug}-site": row}}))
        os.chdir(ws)
        return ws

    def handover(self, **kw):
        a = argparse.Namespace(name=None, out=None, no_upload=kw.pop("no_upload", True), dry_run=False, **kw)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            self.site.cmd_handover(a)
        return buf.getvalue()

    def unzip(self, zpath):
        dest = self.tmp / "unzipped"
        with zipfile.ZipFile(zpath) as z:
            self.assertIsNone(z.testzip(), "the zip opens and every member is intact")
            z.extractall(dest)
        (inner,) = list(dest.iterdir())
        return inner

    def test_bundles_everything_and_prints_the_zip_last(self):
        ws = self.workspace()
        out = self.handover()
        last = out.strip().splitlines()[-1]
        self.assertTrue(last.endswith(".zip") and Path(last).is_file(), "the zip's path is the last line (SEND-FILE)")
        self.assertEqual(Path(last).parent, ws / "handover")
        self.assertEqual((ws / "handover" / ".gitignore").read_text().splitlines()[-1], "*",
                         "the handover never lands in the clients/ repo")
        self.assertNotIn("PROBLEM", out)
        inner = self.unzip(last)
        names = sorted(str(p.relative_to(inner)) for p in inner.rglob("*") if p.is_file())
        self.assertEqual(names, sorted([
            "site-acme-site.zip", "site-acme-site.bundle", "database/acme-site/bookings.csv",
            "database/acme-site/bookings.json", "newsletter-subscribers.csv", "chats.html", "memory.md",
            "schedules.json", "README.md"]))
        calls = self.log.read_text()
        self.assertIn("db export --site acme-site", calls)
        self.assertIn("newsletter subscribers --json", calls)
        self.assertIn("chats --project acme -n 0 --out", calls)
        self.assertNotIn("--from", calls, "a client's bundle has every conversation on the project")

    def test_every_file_in_the_bundle_opens(self):
        self.workspace()
        inner = self.unzip(self.handover().strip().splitlines()[-1])
        with zipfile.ZipFile(inner / "site-acme-site.zip") as z:
            self.assertIn("acme-site/index.html", z.namelist())
        clone = self.tmp / "clone"
        run("git", "clone", "-q", str(inner / "site-acme-site.bundle"), str(clone), cwd=self.tmp)
        self.assertEqual((clone / "index.html").read_text(), "<h1>Acme</h1>", "the bundle clones, history and all")
        with open(inner / "newsletter-subscribers.csv") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual([r["email"] for r in rows], ["a@example.com", "b@example.com"])
        with open(inner / "database" / "acme-site" / "bookings.csv") as f:
            self.assertEqual(next(csv.DictReader(f))["name"], "Sam Example")
        json.loads((inner / "database" / "acme-site" / "bookings.json").read_text())
        jobs = json.loads((inner / "schedules.json").read_text())
        self.assertEqual([j["id"] for j in jobs], ["s1"], "their live jobs only: not stopped, not another project's")
        self.assertIn("<html", (inner / "chats.html").read_text())
        self.assertIn("Acme Pools, Provo.", (inner / "memory.md").read_text())

    def test_the_readme_says_what_runs_where_and_how_to_move(self):
        self.workspace()
        readme = (self.unzip(self.handover().strip().splitlines()[-1]) / "README.md").read_text()
        for want in ("Cloudflare Pages, project `acme-site`", "github.com/patchlamp/acme-site",
                     "acmepools.com is registered in your name", "D1 `acme-site`", "DNS records",
                     "thirty days", "Mondays 8am: @weekly-report", "newsletter-subscribers.csv"):
            self.assertIn(want, readme)

    def test_a_demo_carries_only_the_askers_conversation(self):
        self.workspace(slug="demo-service")
        os.environ["RELAY_SENDER_KEY"] = "sms:+18015550100"
        inner = self.unzip(self.handover(no_upload=False).strip().splitlines()[-1])
        self.assertIn("chats --project demo-service -n 0 --out", self.log.read_text())
        self.assertIn("--from sms:+18015550100", self.log.read_text())
        self.assertFalse((inner / "memory.md").exists(), "a demo's notes are everyone's, so they stay")
        self.assertFalse((inner / "schedules.json").exists())

    def test_a_demo_with_no_sender_has_no_conversation(self):
        self.workspace(slug="demo-service")
        out = self.handover()
        self.assertNotIn("chats ", self.log.read_text())
        self.assertIn("not included: a demo", out)

    def test_a_failing_tool_is_a_problem_line_and_the_bundle_still_comes(self):
        self.workspace()
        os.environ["FAKE_NEWSLETTER"] = "error"
        out = self.handover()
        self.assertIn("PROBLEM newsletter:", out)
        inner = self.unzip(out.strip().splitlines()[-1])
        self.assertFalse((inner / "newsletter-subscribers.csv").exists())
        self.assertIn("Patch has passed it on", (inner / "README.md").read_text())

    def test_no_list_and_no_database_are_notes_not_problems(self):
        self.workspace(db=False, memory=False)
        os.environ["FAKE_NEWSLETTER"] = "none"
        out = self.handover()
        self.assertNotIn("PROBLEM", out)
        self.assertIn("not included: no mailing list", out)
        self.assertIn("not included: memory.md", out)
        self.assertNotIn("db export", self.log.read_text())

    def test_uploads_to_the_account_page_with_the_relay_secret(self):
        seen = {}

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen["path"] = self.path
                seen["auth"] = self.headers.get("Authorization")
                seen["type"] = self.headers.get("Content-Type")
                seen["body"] = self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"account": "http://x/account#files"}).encode())

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.handle_request, daemon=True).start()
        os.environ["PATCHLAMP_URL"] = f"http://127.0.0.1:{srv.server_port}"
        os.environ["PATCHLAMP_RELAY_SHARED_SECRET"] = "test-secret"
        self.workspace()
        out = self.handover(no_upload=False)
        srv.server_close()
        self.assertEqual(seen["path"], "/internal/relay/projects/acme/handover")
        self.assertEqual(seen["auth"], "Bearer test-secret")
        self.assertTrue(seen["type"].startswith("multipart/form-data"))
        self.assertIn(b'filename="acme-handover-', seen["body"])
        self.assertIn("account page: uploaded", out)
        self.assertNotIn("test-secret", out, "the secret is never printed")

    def test_no_secret_means_no_upload_and_says_so(self):
        self.workspace()
        out = self.handover(no_upload=False)
        self.assertIn("account page: not uploaded (no PATCHLAMP_RELAY_SHARED_SECRET", out)
        self.assertTrue(out.strip().splitlines()[-1].endswith(".zip"))

    def test_the_same_day_twice_rebuilds_cleanly(self):
        ws = self.workspace()
        self.handover()
        (ws / "handover").joinpath(next(p.name for p in (ws / "handover").iterdir() if p.is_dir()), "stale.txt").write_text("x")
        inner = self.unzip(self.handover().strip().splitlines()[-1])
        self.assertFalse((inner / "stale.txt").exists())

    def test_the_subcommand_is_wired(self):
        r = subprocess.run([str(ROOT / "bin" / "site"), "handover", "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertIn("--no-upload", r.stdout)


if __name__ == "__main__":
    unittest.main()
