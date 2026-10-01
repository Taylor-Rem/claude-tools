"""IndexNow on publish (ROADMAP B49, the toolbelt half) — the HTTP call is faked.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

bin/site is loaded as a module, Cloudflare and wrangler are captured instead of
called, and IndexNow is a local HTTP server: what's pinned is that a publish
makes the site a key of its own (in the registry, not in the repo's history as
a secret — the key file *is* the proof of ownership, so it is committed and
pushed before the upload), submits the site's own URLs to its own host, records
the answer for `site doctor`, keeps the publish standing when the ping fails,
skips a site that asks not to be indexed, and sends nothing with --no-ping.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "templates" / "sites"


def load_site():
    loader = importlib.machinery.SourceFileLoader("site_tool_indexnow", str(ROOT / "bin" / "site"))
    spec = importlib.util.spec_from_loader("site_tool_indexnow", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class FakeIndexNow(BaseHTTPRequestHandler):
    state = {}

    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        self.state["posts"].append(json.loads(self.rfile.read(n) or b"{}"))
        code = self.state.get("code", 200)
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()


def run_git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


class IndexNowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeIndexNow)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.endpoint = f"http://127.0.0.1:{cls.server.server_port}/indexnow"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeIndexNow.state = {"posts": [], "code": 200}
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "env").write_text("CLOUDFLARE_API_TOKEN=fake-token\nCLOUDFLARE_ACCOUNT_ID=fake-account\n")
        (root / "sites.json").write_text(json.dumps({"acme": {"acme-site": {
            "host": "cloudflare", "project": "acme-site"}}}))
        self.ws = root / "acme"
        (self.ws / "repos").mkdir(parents=True)
        (self.ws / ".client.json").write_text(json.dumps({"slug": "acme", "name": "Acme Pools"}))
        # a real repo with a real remote: the key file has to commit and push
        self.repo = self.ws / "repos" / "acme-site"
        self.repo.mkdir()
        for f in ("index.html", "photos.html", "404.html"):
            src = SITES / "service" / f
            (self.repo / f).write_text(src.read_text() if src.exists() else "<!doctype html>\n")
        self.remote = root / "acme-site.git"
        subprocess.run(["git", "init", "-q", "--bare", str(self.remote)], check=True)
        run_git(self.repo, "init", "-q", "-b", "main")
        run_git(self.repo, "-c", "user.name=T", "-c", "user.email=t@example.com", "add", "-A")
        run_git(self.repo, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-q", "-m", "first")
        run_git(self.repo, "remote", "add", "origin", str(self.remote))
        run_git(self.repo, "push", "-q", "-u", "origin", "main")

        self.site = load_site()
        self.site.ENV_FILE = root / "env"
        self.site.REGISTRY = root / "sites.json"
        self.site.INDEXNOW_ENDPOINT = self.endpoint
        self.deploys = []
        self.site.cf_ensure_project = lambda project: None
        self.site.cf_project = lambda project: {"name": project}
        self.site.pages_host = lambda project: f"{project}.pages.dev"
        self.site.cf_domains = lambda project: []
        self.site.wait_live = lambda url, marker, seconds=240: True
        self.site.curl_header = lambda url, name: "no-cache"
        self.site.wrangler = lambda *a, **k: self.deploys.append(a) or (0, "https://abc.acme-site.pages.dev")
        self.cwd = os.getcwd()
        os.chdir(self.ws)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def publish(self, **kw):
        kw = {"name": "acme-site", "dry_run": False, "no_ping": False, **kw}
        args = argparse.Namespace(**kw)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.site.cmd_publish(args)
        return out.getvalue()

    def row(self):
        return json.loads((Path(self.site.REGISTRY)).read_text())["acme"]["acme-site"]

    # ---------------------------------------------------------------- the pieces

    def test_the_urls_are_the_site_s_own_pages(self):
        self.assertEqual(self.site.site_urls(self.repo, "https://acme.com/"),
                         ["https://acme.com/", "https://acme.com/photos.html"],
                         "the home page and the top-level pages; never 404.html")
        (self.repo / "sitemap.xml").write_text(
            '<urlset><url><loc>https://acme.com/</loc></url><url><loc>https://acme.com/a.html</loc></url></urlset>')
        self.assertEqual(self.site.site_urls(self.repo, "https://acme.com/"),
                         ["https://acme.com/", "https://acme.com/a.html"], "a sitemap wins")

    def test_the_host_is_the_custom_domain_when_there_is_one(self):
        self.assertEqual(self.site.site_host({}, "acme-site"), "acme-site.pages.dev")
        self.assertEqual(self.site.site_host({"pages_host": "acme-site-1bm.pages.dev"}, "acme-site"),
                         "acme-site-1bm.pages.dev")
        self.assertEqual(self.site.site_host({"domains": ["www.acme.com", "acme.com"]}, "acme-site"), "acme.com")

    # ---------------------------------------------------------------- a publish

    def test_a_publish_pings_with_a_key_the_site_serves(self):
        out = self.publish()
        self.assertEqual(len(self.deploys), 1)
        key = self.row()["indexnow_key"]
        self.assertRegex(key, r"^[0-9a-f]{32}$")
        self.assertEqual((self.repo / f"{key}.txt").read_text().strip(), key,
                         "IndexNow checks /<key>.txt: the file has to be in the repo")
        _, tracked = self.site.git(self.repo, "ls-files", f"{key}.txt")
        self.assertEqual(tracked, f"{key}.txt", "committed, or the upload would not carry it")
        self.assertEqual(subprocess.run(["git", "-C", str(self.repo), "log", "--oneline", "@{u}.."],
                                        capture_output=True, text=True).stdout.strip(), "", "pushed")
        post = FakeIndexNow.state["posts"][0]
        self.assertEqual(post["host"], "acme-site.pages.dev")
        self.assertEqual(post["key"], key)
        self.assertEqual(post["keyLocation"], f"https://acme-site.pages.dev/{key}.txt")
        self.assertEqual(post["urlList"], ["https://acme-site.pages.dev/",
                                           "https://acme-site.pages.dev/photos.html"])
        self.assertIn("IndexNow: 2 URL(s)", out)
        self.assertNotIn(key, out, "a key is never printed")
        self.assertEqual(self.row()["indexnow"]["status"], 200)
        self.assertTrue(self.row()["indexnow"]["ok"])
        self.assertEqual(self.row()["indexnow"]["urls"], 2)

    def test_the_key_is_made_once(self):
        self.publish()
        key = self.row()["indexnow_key"]
        self.publish()
        self.assertEqual(self.row()["indexnow_key"], key)
        self.assertEqual(len(FakeIndexNow.state["posts"]), 2)
        self.assertEqual(len(list(self.repo.glob("*.txt"))), 1)

    def test_a_refused_ping_does_not_fail_the_publish(self):
        FakeIndexNow.state["code"] = 403
        out = self.publish()
        self.assertIn("not accepted (403)", out)
        self.assertIn("the publish stands", out)
        self.assertIn("published acme-site", out)
        self.assertFalse(self.row()["indexnow"]["ok"])

    def test_no_ping(self):
        out = self.publish(no_ping=True)
        self.assertEqual(FakeIndexNow.state["posts"], [])
        self.assertEqual(list(self.repo.glob("*.txt")), [])
        self.assertNotIn("indexnow_key", self.row())
        self.assertIn("published acme-site", out)

    def test_a_site_that_asks_not_to_be_indexed_is_never_submitted(self):
        (self.repo / "robots.txt").write_text("User-agent: *\nNoindex: /\n")
        run_git(self.repo, "-c", "user.name=T", "-c", "user.email=t@example.com", "add", "-A")
        run_git(self.repo, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-q", "-m", "robots")
        run_git(self.repo, "push", "-q")
        out = self.publish()
        self.assertIn("IndexNow: skipped", out)
        self.assertEqual(FakeIndexNow.state["posts"], [])

    def test_the_badge_opt_out_is_honoured_by_the_same_publish(self):
        (self.ws / "NOTES.md").write_text("**Who this is.** Acme Pools.\n\nbadge: off\n")
        uploaded = {}

        def capture(*a, **k):
            # wrangler is handed the export tree: read what would go up
            tree = Path(a[2])
            uploaded.update({p.name: p.read_text() for p in tree.glob("*.html")})
            return 0, "https://abc.acme-site.pages.dev"

        self.site.wrangler = capture
        out = self.publish()
        self.assertIn("badge: off in NOTES.md", out)
        self.assertNotIn("Patched by Patchlamp", uploaded["index.html"])
        self.assertIn("Patched by Patchlamp", (self.repo / "index.html").read_text(),
                      "the repo is the client's record and keeps the line")

    def test_a_key_file_that_cannot_be_committed_leaves_no_dirt(self):
        """A publish refuses a dirty tree, so a failed key commit must clean up after
        itself or it breaks the next one."""
        (self.repo / ".git" / "index.lock").write_text("")      # make git refuse to commit
        out = self.publish()
        (self.repo / ".git" / "index.lock").unlink()
        self.assertIn("not committed", out)
        self.assertEqual(FakeIndexNow.state["posts"], [])
        self.assertEqual(list(self.repo.glob("*.txt")), [])
        self.assertEqual(subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"],
                                        capture_output=True, text=True).stdout.strip(), "")
        self.assertIn("published acme-site", out)

    def test_a_dry_run_sends_nothing(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.site.cmd_publish(argparse.Namespace(name="acme-site", dry_run=True, no_ping=False))
        self.site.DRY = False
        self.assertEqual(FakeIndexNow.state["posts"], [])
        self.assertIn("would submit", out.getvalue())
        self.assertEqual(list(self.repo.glob("*.txt")), [])


if __name__ == "__main__":
    unittest.main()
