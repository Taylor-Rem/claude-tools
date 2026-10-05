"""The site chat's toolbelt half (ROADMAP B108, plan 45 § Contract 1 and 7) — no network.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

What's pinned: every page of every site template carries the script tag exactly
once, naming {{SLUG}} (filled by `site new`), on the line after the badge; the
helper puts it in, takes it out and finds it; `site doctor`'s check names a page
without it; `client new` stamps the facts.md skeleton with the contract's
sections and never overwrites one Patch wrote; `client doctor`'s phone check;
`demo golden` keeps facts.md and `demo reset` puts it back; a claimed preview's
pages get the tag with the new workspace's slug.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "templates" / "sites"
TYPES = sorted(d.name for d in SITES.iterdir() if d.is_dir() and not d.name.startswith("_"))
sys_path = str(ROOT / "lib")
if sys_path not in _sys.path:
    _sys.path.insert(0, sys_path)
import site_chat  # noqa: E402

TAG = '<script src="https://patchlamp.com/s/site-chat.js" data-site="{{SLUG}}" crossorigin="anonymous" defer></script>'
SECTIONS = ("Business", "Phone", "Hours", "Area served", "Services and prices", "Policies", "Not offered")


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TemplateTag(unittest.TestCase):
    def test_every_page_carries_the_tag_once_after_the_badge(self):
        for t in TYPES:
            for p in sorted((SITES / t).glob("*.html")):
                html = p.read_text()
                with self.subTest(page=f"{t}/{p.name}"):
                    self.assertEqual(html.count(TAG), 1, "the contract's tag, exactly, once a page")
                    lines = html.splitlines()
                    i = next(n for n, line in enumerate(lines) if TAG in line)
                    if "patchlamp-badge" in html:
                        self.assertIn("patchlamp-badge", lines[i - 1], "on the line after the badge")
                    else:
                        nxt = lines[i + 1] if "patchlamp.com/hit.js" not in lines[i + 1] else lines[i + 2]   # B127's count line follows it
                        self.assertIn("</body>", nxt, "a page without a badge: just before </body>")

    def test_site_new_fills_the_slug(self):
        site = load("site_tool_chat", ROOT / "bin" / "site")
        src = (ROOT / "bin" / "site").read_text()
        self.assertIn('"SLUG": meta["slug"]', src, "site new's values carry the workspace slug")
        self.assertEqual(site.fill(TAG, {"SLUG": "acme"}), site_chat.tag("acme"))
        self.assertIn('"YEAR", "SLUG", "TAGLINE", "MAIL"}', src, "and `site doctor` knows it is one site new fills")


class Helper(unittest.TestCase):
    PAGE = ("<html><body>\n  <footer>\n    <p class=\"copyright\">x</p>\n"
            "    <p class=\"patchlamp-badge\"><a href=\"https://patchlamp.com/\">Patched by Patchlamp</a></p>\n"
            "  </footer>\n</body></html>\n")

    def test_ensure_strip_and_find(self):
        out = site_chat.ensure(self.PAGE, "acme")
        self.assertEqual(site_chat.slugs(out), ["acme"])
        self.assertIn('Patchlamp</a></p>\n    <script src="https://patchlamp.com/s/site-chat.js" data-site="acme" crossorigin="anonymous"', out)
        self.assertEqual(site_chat.ensure(out, "acme"), out, "idempotent")
        self.assertEqual(site_chat.slugs(site_chat.ensure(out, "other")), ["other"], "a wrong slug is replaced")
        self.assertEqual(site_chat.strip(out), self.PAGE)
        bare = "<html><body>\n  <p>hi</p>\n</body></html>\n"
        self.assertIn('  <script src="https://patchlamp.com/s/site-chat.js" data-site="acme" crossorigin="anonymous" defer></script>\n</body>',
                      site_chat.ensure(bare, "acme"))
        self.assertEqual(site_chat.ensure("<p>a fragment</p>", "acme"), "<p>a fragment</p>")
        # B127: B108's form is still found, and ensure() moves it to the cookie-free path
        old = self.PAGE.replace("  </footer>", '    <script src="https://patchlamp.com/site-chat.js" data-site="acme" defer></script>\n  </footer>')
        self.assertEqual(site_chat.slugs(old), ["acme"])
        self.assertFalse(site_chat.current(old, "acme"))
        moved = site_chat.ensure(old, "acme")
        self.assertTrue(site_chat.current(moved, "acme"))
        self.assertNotIn('"https://patchlamp.com/site-chat.js"', moved)

    def test_site_doctor_names_the_pages_without_it(self):
        site = load("site_tool_chat2", ROOT / "bin" / "site")
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "index.html").write_text(site_chat.ensure(self.PAGE, "acme"))
            (d / "photos.html").write_text(self.PAGE)
            (d / "old.html").write_text(site_chat.ensure(self.PAGE, "someone-else"))
            (d / "functions" / "admin").mkdir(parents=True)
            (d / "functions" / "admin" / "x.html").write_text("<p>not a page</p>")
            missing, other = site.chat_tag_gaps(d, "acme")
        self.assertEqual(missing, ["photos.html"])
        self.assertEqual(other, ["old.html (someone-else)"])


class ClientFacts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.clients = root / "clients"
        self.clients.mkdir()
        (root / "config.json").write_text(json.dumps({"projects": {}, "senders": {}}))
        self.env = dict(os.environ, CLIENTS_DIR=str(self.clients), RELAY_CONFIG=str(root / "config.json"),
                        CLAUDE_TOOLS_ENV=str(root / "no-env"))
        self.client = load("client_tool_chat", ROOT / "bin" / "client")

    def tearDown(self):
        self.tmp.cleanup()

    def run_client(self, *args):
        return subprocess.run([str(ROOT / "bin" / "client"), *args], env=self.env, capture_output=True, text=True)

    def test_new_stamps_the_skeleton_and_a_restamp_keeps_patchs(self):
        r = self.run_client("new", "poolco", "--name", "Pool Co", "--shared-key")
        self.assertEqual(r.returncode, 0, r.stderr)
        f = self.clients / "poolco" / "facts.md"
        text = f.read_text()
        heads = [line[3:].strip() for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(tuple(heads), SECTIONS, "the contract's sections, in order")
        self.assertTrue(text.rstrip().splitlines()[-1].startswith("Updated: "))
        sec = self.client.facts_sections(text)
        self.assertEqual((sec["Phone"], sec["Hours"]), ("", ""), "the fallback lines start empty, never a placeholder")
        self.assertIn("no phone", self.client.facts_problem(self.clients / "poolco"))
        f.write_text(text.replace("## Phone\n", "## Phone\n801-555-0142\n"))
        self.run_client("new", "poolco", "--restamp", "--shared-key")
        self.assertIn("801-555-0142", f.read_text(), "a restamp never touches facts.md")
        self.assertEqual(self.client.facts_problem(self.clients / "poolco"), "")

    def test_doctor_warns_without_failing(self):
        self.run_client("new", "poolco", "--name", "Pool Co", "--shared-key")
        (self.clients / "poolco" / "repos" / "site" / ".git").mkdir(parents=True)
        r = self.run_client("doctor", "poolco")
        self.assertIn("facts: WARN facts.md has no phone", r.stdout)


class DemoFacts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.ws = root / "clients" / "demo-acme"
        self.ws.mkdir(parents=True)
        (self.ws / ".client.json").write_text(json.dumps({"slug": "demo-acme", "name": "Acme"}))
        self.old = {k: os.environ.get(k) for k in ("DEMO_STATE", "CLIENTS_DIR", "DEMO_FACTS_DIR")}
        os.environ.update(DEMO_STATE=str(root / "demo.json"), CLIENTS_DIR=str(root / "clients"))
        os.environ.pop("DEMO_FACTS_DIR", None)
        self.demo = load("demo_tool_chat", ROOT / "bin" / "demo")

    def tearDown(self):
        for k, v in self.old.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.tmp.cleanup()

    def test_golden_keeps_and_reset_restores(self):
        f = self.ws / "facts.md"
        self.assertEqual(self.demo.facts_restore(self.ws, "demo-acme"), "no golden", "nothing to restore: left alone")
        f.write_text("## Phone\n801-555-0142\n")
        self.demo.facts_keep(self.ws, "demo-acme")
        self.assertTrue(str(self.demo.golden_facts("demo-acme")).startswith(str(Path(self.tmp.name) / "demo-facts")),
                        "beside the state, outside the workspace")
        self.assertEqual(self.demo.facts_restore(self.ws, "demo-acme"), "same")
        f.write_text("## Phone\ncall my cousin\n")
        self.assertEqual(self.demo.facts_restore(self.ws, "demo-acme"), "restored")
        self.assertEqual(f.read_text(), "## Phone\n801-555-0142\n")
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("keep me")
        f.unlink()
        f.symlink_to(outside)
        self.demo.facts_restore(self.ws, "demo-acme")
        self.assertFalse(f.is_symlink(), "a link a run left is replaced, never followed")
        self.assertEqual(outside.read_text(), "keep me")


class ClaimTag(unittest.TestCase):
    def test_a_claimed_page_gets_the_new_slug_and_a_preview_404_none(self):
        leads = load("leads_tool_chat", ROOT / "bin" / "leads")
        with tempfile.TemporaryDirectory() as tmp:
            tree, dest = Path(tmp) / "tree", Path(tmp) / "dest"
            tree.mkdir()
            dest.mkdir()
            page = ("<html><body>\n  <footer>\n<!--c:footer\n    <p class=\"patchlamp-badge\"><a href=\"x\">"
                    "Patched by Patchlamp</a></p>\n/c:footer-->\n  </footer>\n</body></html>\n")
            (tree / "index.html").write_text(page)
            leads.claim_tree(tree, dest, "acme-plumbing")
            self.assertEqual(site_chat.slugs((dest / "index.html").read_text()), ["acme-plumbing"])
            out = Path(tmp) / "out"
            for t in ("service", "portfolio"):
                (out / t).mkdir(parents=True)
                leads._copy_site_files(SITES / t, out / t, "Acme", 2026)
                self.assertFalse(site_chat.has((out / t / "404.html").read_text()), "a preview carries no bubble")


if __name__ == "__main__":
    unittest.main()
