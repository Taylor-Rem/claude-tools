"""The page-load count's toolbelt half (ROADMAP B127, ~/projects/plans/50-site-numbers.md) — no network.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

What's pinned: every page of every site template carries the hit.js tag exactly once,
naming {{SLUG}}, on the line after the site chat's; the templates' rule says what it
keeps and no longer says "no analytics"; the helper puts it in, takes it out and finds
it; `site doctor`'s gaps; `site stats` reads only this workspace's project, refuses an
app that doesn't answer for it, and prints the week; `site counter` adds the line; the
broker lets a client run `stats` and `counter` but not a demo; previews carry no tag
and a claim adds it; `front --project`.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "templates" / "sites"
TYPES = sorted(d.name for d in SITES.iterdir() if d.is_dir() and not d.name.startswith("_"))
if str(ROOT / "lib") not in _sys.path:
    _sys.path.insert(0, str(ROOT / "lib"))
import site_chat  # noqa: E402
import site_hit  # noqa: E402
import sandbox_tools  # noqa: E402

TAG = '<script src="https://patchlamp.com/hit.js" data-site="{{SLUG}}" crossorigin="anonymous" defer></script>'
CHAT = '<script src="https://patchlamp.com/site-chat.js" data-site="{{SLUG}}" defer></script>'


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


PAGE = ("<html><body>\n  <footer>\n    <p class=\"patchlamp-badge\"><a href=\"https://patchlamp.com/\">Patched by Patchlamp</a></p>\n"
        "  </footer>\n</body></html>\n")


class Templates(unittest.TestCase):
    def test_every_page_carries_the_tag_once_after_the_chat_line(self):
        for t in TYPES:
            for p in sorted((SITES / t).glob("*.html")):
                html = p.read_text()
                with self.subTest(page=f"{t}/{p.name}"):
                    self.assertEqual(html.count(TAG), 1)
                    lines = html.splitlines()
                    i = next(n for n, line in enumerate(lines) if TAG in line)
                    self.assertIn(CHAT, lines[i - 1], "on the line after the site chat's")

    def test_the_rule_says_what_it_keeps(self):
        for t in TYPES:
            text = (SITES / t / "CLAUDE.md").read_text()
            with self.subTest(template=t):
                self.assertNotIn("no analytics", text, "a count is a kind of analytics: the sentence says exactly what it is")
                flat = " ".join(text.split())
                self.assertIn("The one count is patchlamp.com/hit.js: a page load's path and the site that linked to it, "
                              "nothing about the visitor (no cookie, no address, no identifier)", flat)
                self.assertIn("site stats", flat)


class Helper(unittest.TestCase):
    def test_ensure_strip_and_find(self):
        out = site_hit.ensure(PAGE, "acme")
        self.assertEqual(site_hit.slugs(out), ["acme"])
        self.assertIn('Patchlamp</a></p>\n    <script src="https://patchlamp.com/hit.js" data-site="acme" crossorigin="anonymous" defer>', out)
        old_form = PAGE.replace("</footer>", '<script src="https://patchlamp.com/hit.js" data-site="acme" defer></script>\n  </footer>')
        self.assertIn('crossorigin="anonymous"', site_hit.ensure(old_form, "acme"), "a tag without crossorigin is rewritten")
        self.assertEqual(site_hit.ensure(out, "acme"), out, "idempotent")
        self.assertEqual(site_hit.slugs(site_hit.ensure(out, "other")), ["other"])
        self.assertEqual(site_hit.strip(out), PAGE)
        both = site_hit.ensure(site_chat.ensure(PAGE, "acme"), "acme")
        lines = both.splitlines()
        i = next(n for n, line in enumerate(lines) if "hit.js" in line)
        self.assertIn("site-chat.js", lines[i - 1], "after the chat line when there is one")
        self.assertIn('  <script src="https://patchlamp.com/hit.js" data-site="acme" crossorigin="anonymous" defer></script>\n</body>',
                      site_hit.ensure("<html><body>\n  <p>hi</p>\n</body></html>\n", "acme"))
        self.assertEqual(site_hit.ensure("<p>a fragment</p>", "acme"), "<p>a fragment</p>")


class Site(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "acme"
        (self.ws / "repos" / "acme-site" / ".git").mkdir(parents=True)
        (self.ws / ".client.json").write_text(json.dumps({"slug": "acme", "name": "Acme Pools"}))
        self.site = load("site_tool_hit", ROOT / "bin" / "site")
        self.cwd = os.getcwd()
        os.chdir(self.ws)
        self.old_project = os.environ.pop("RELAY_PROJECT", None)

    def tearDown(self):
        os.chdir(self.cwd)
        if self.old_project is not None:
            os.environ["RELAY_PROJECT"] = self.old_project
        self.tmp.cleanup()

    def stats(self, answer, *argv):
        calls = []

        def fake(method, path, body=None):
            calls.append((method, path))
            return answer

        out = io.StringIO()
        code = 0
        with mock.patch.object(self.site, "app_call", fake), contextlib.redirect_stdout(out):
            a = self.site.argparse.Namespace(days=7, json=False)
            for flag in argv:
                setattr(a, flag, True)
            try:
                self.site.cmd_stats(a)
            except SystemExit as e:
                code = e.code
        return calls, out.getvalue(), code

    def test_doctor_gaps(self):
        d = self.ws / "repos" / "acme-site"
        (d / "index.html").write_text(site_hit.ensure(PAGE, "acme"))
        (d / "photos.html").write_text(PAGE)
        (d / "old.html").write_text(site_hit.ensure(PAGE, "someone-else"))
        missing, other = self.site.hit_tag_gaps(d, "acme")
        self.assertEqual(missing, ["photos.html"])
        self.assertEqual(other, ["old.html (someone-else)"])

    def test_stats_reads_this_workspace_only_and_prints_the_week(self):
        week = {"project": "acme", "days": 7, "since": "2026-09-29", "to": "2026-10-05", "totals": {"views": 12},
                "by_day": [{"day": "2026-10-03", "views": 4}, {"day": "2026-10-05", "views": 8}],
                "pages": [{"path": "/", "views": 9}, {"path": "/services", "views": 3}],
                "referrers": [{"ref": "www.google.com", "views": 5}, {"ref": "from:flyer", "views": 2}]}
        (self.ws / "repos" / "acme-site" / "index.html").write_text(PAGE)
        calls, out, code = self.stats((200, week))
        self.assertEqual(calls, [("GET", "/internal/relay/front/visits?days=7&project=acme")])
        self.assertEqual(code, 0)
        self.assertIn("Acme Pools, last 7 days (2026-09-29 to 2026-10-05): 12 page views", out)
        self.assertIn("Sat 2026-10-03      4", out)
        self.assertIn("pages:      / 9, /services 3", out)
        self.assertIn("came from:  www.google.com 5, from:flyer 2", out)
        self.assertIn("page loads, not people", out)
        self.assertIn("NOTE 1 page(s) carry no count line", out)

    def test_stats_never_shows_an_old_apps_own_numbers_as_theirs(self):
        _, out, code = self.stats((200, {"days": 7, "totals": {"views": 99, "visitor_days": 40}, "by_day": []}))
        self.assertEqual(code, 1)
        self.assertIn("doesn't count client sites yet", out)

    def test_stats_refuses_another_projects_run(self):
        os.environ["RELAY_PROJECT"] = "someone-else"
        try:
            r = subprocess.run([str(ROOT / "bin" / "site"), "stats"], cwd=self.ws, capture_output=True, text=True,
                               env=dict(os.environ, CLAUDE_TOOLS_ENV=str(Path(self.tmp.name) / "no-env"),
                                        PATCHLAMP_URL="http://127.0.0.1:9"))
        finally:
            os.environ.pop("RELAY_PROJECT", None)
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("page view", r.stdout)

    def test_counter_adds_the_line_and_commits(self):
        d = self.ws / "repos" / "acme-site"
        subprocess.run(["git", "init", "-q", str(d)], check=True)
        (d / "index.html").write_text(site_chat.ensure(PAGE, "acme"))
        (d / "about.html").write_text(site_hit.ensure(site_chat.ensure(PAGE, "acme"), "acme"))
        subprocess.run(["git", "-C", str(d), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(d), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], check=True)
        published = []
        with mock.patch.object(self.site, "registry_load", lambda: {"acme": {"acme-site": {"host": "cloudflare"}}}), \
             mock.patch.object(self.site, "cmd_publish", lambda a: published.append(a.name)), \
             mock.patch.object(self.site, "git", self._git_no_push(d)), contextlib.redirect_stdout(io.StringIO()) as out:
            self.site.cmd_counter(self.site.argparse.Namespace(name=None, check=False, dry_run=False))
        self.assertEqual(site_hit.slugs((d / "index.html").read_text()), ["acme"])
        self.assertIn("added the count line to 1 page(s)", out.getvalue())
        self.assertEqual(published, ["acme-site"])
        log = subprocess.run(["git", "-C", str(d), "log", "--format=%s", "-1"], capture_output=True, text=True).stdout
        self.assertIn("page-load count", log)

    def _git_no_push(self, d):
        real = self.site.git

        def git(repo, *args, check=True):
            if args and args[0] == "push":
                return 0, ""
            return real(repo, *args, check=check)
        return git


class Broker(unittest.TestCase):
    def test_client_and_owner_may_read_their_numbers_a_demo_may_not(self):
        roles = sandbox_tools.TOOLS["site"]["roles"]
        for role in ("client", "owner"):
            self.assertIn("stats", roles[role])
            self.assertIn("counter", roles[role])
        self.assertNotIn("stats", roles["demo"])


class Previews(unittest.TestCase):
    def test_a_preview_404_carries_no_count_and_a_claim_adds_it(self):
        leads = load("leads_tool_hit", ROOT / "bin" / "leads")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            for t in ("service", "portfolio"):
                (out / t).mkdir(parents=True)
                leads._copy_site_files(SITES / t, out / t, "Acme", 2026)
                self.assertFalse(site_hit.has((out / t / "404.html").read_text()), "a preview is nobody's site yet")
            tree, dest = Path(tmp) / "tree", Path(tmp) / "dest"
            tree.mkdir()
            dest.mkdir()
            (tree / "index.html").write_text("<html><body>\n  <footer>\n<!--c:footer\n    <p class=\"patchlamp-badge\">"
                                             "<a href=\"x\">Patched by Patchlamp</a></p>\n/c:footer-->\n  </footer>\n</body></html>\n")
            leads.claim_tree(tree, dest, "acme-plumbing")
            html = (dest / "index.html").read_text()
            self.assertEqual(site_hit.slugs(html), ["acme-plumbing"])
            self.assertLess(html.index("site-chat.js"), html.index("hit.js"))


class Front(unittest.TestCase):
    def test_front_project_asks_for_that_site(self):
        front = load("front_tool_hit", ROOT / "bin" / "front")
        seen = []

        def api(path, params=None):
            seen.append((path, params))
            return {"project": "acme", "days": 7, "since": "2026-09-29", "to": "2026-10-05", "totals": {"views": 3},
                    "by_day": [{"day": "2026-10-05", "views": 3}], "pages": [{"path": "/", "views": 3}], "referrers": []}

        with mock.patch.object(front, "api", api), contextlib.redirect_stdout(io.StringIO()) as out:
            front.show_visits(7, project="acme")
        self.assertEqual(seen, [("/visits", {"days": 7, "project": "acme"})])
        self.assertIn("acme's site, last 7 days", out.getvalue())
        self.assertIn("3 page views", out.getvalue())


if __name__ == "__main__":
    unittest.main()
