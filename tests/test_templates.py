"""The kinds of site (templates/sites/<type>/) and their live demos — no network.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

What's pinned: every type says what it is (template.json) and names
collections that exist; the files every site shares are the same in every
type (only the palette in :root differs); a type with a database posts its
forms to the collections it starts with; no template carries the demo bar;
and each type's demo, where its workspace is on this machine, has the same
sections and forms as its template — the demo is the template with demo
content, so a demo that works is a template that works.
"""

import importlib.machinery
import importlib.util
import json
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "templates" / "sites"
CLIENTS = Path(os.environ.get("CLIENTS_DIR", Path.home() / "projects" / "clients"))
SHARED = ("_headers", "_redirects", ".gitignore", "js/main.js", ".claude/settings.json")
TYPES = sorted(d.name for d in SITES.iterdir() if d.is_dir() and not d.name.startswith("_"))


def load_site():
    loader = importlib.machinery.SourceFileLoader("site_tool_t", str(ROOT / "bin" / "site"))
    spec = importlib.util.spec_from_loader("site_tool_t", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def after_root(css):
    return css[css.index("}", css.index(":root")):]


def shape(html):
    """What a page is made of: its section ids and where its forms post."""
    return (re.findall(r'<section[^>]*\bid="([^"]+)"', html), re.findall(r'<form[^>]*\baction="([^"]+)"', html))


class TemplatesTest(unittest.TestCase):
    def test_the_types(self):
        self.assertIn("business", TYPES)
        self.assertIn("service", TYPES)
        site = load_site()
        self.assertEqual(sorted(site.templates()), TYPES)
        self.assertTrue(site.use_template("service")["db"])
        self.assertEqual(site.TEMPLATE_DIR, SITES / "service")
        self.assertFalse(site.use_template(None).get("db"), "no --template is business")
        with self.assertRaises(SystemExit):
            site.use_template("marketplace")

    def test_each_type_says_what_it_is(self):
        for t in TYPES:
            info = json.loads((SITES / t / "template.json").read_text())
            for k in ("title", "summary", "pages", "demo", "workspace"):
                self.assertTrue(info.get(k), f"{t}: template.json has no {k}")
            for c in info.get("collections") or []:
                self.assertTrue((ROOT / "templates" / "collections" / c / "collection.json").exists(), f"{t}: {c}")
                self.assertEqual(json.loads((ROOT / "templates" / "collections" / c / "collection.json").read_text())["status"],
                                 "ready", f"{t} starts with {c}, which is a scaffold")
            self.assertEqual(bool(info.get("db")), bool(info.get("collections")), t)

    def test_shared_files_are_the_same_in_every_type(self):
        for f in SHARED:
            want = (SITES / "business" / f).read_text()
            for t in TYPES:
                self.assertEqual((SITES / t / f).read_text(), want, f"{t}/{f} differs from business/{f}")
        want = after_root((SITES / "business" / "css" / "style.css").read_text())
        for t in TYPES:
            self.assertEqual(after_root((SITES / t / "css" / "style.css").read_text()), want,
                             f"{t}/css/style.css differs from business's past :root (only the palette may)")

    def test_a_database_type_posts_to_its_collections(self):
        for t in TYPES:
            info = json.loads((SITES / t / "template.json").read_text())
            html = (SITES / t / "index.html").read_text()
            actions = shape(html)[1]
            for a in actions:
                if a.startswith("/api/"):
                    self.assertTrue(info.get("db"), f"{t} posts to {a} without a database")
                    self.assertIn(a.split("/")[2], info["collections"] + ["checkout"], f"{t}: {a}")

    def test_no_template_carries_the_demo_bar_or_a_demo_s_words(self):
        for t in TYPES:
            for p in (SITES / t).rglob("*.html"):
                text = p.read_text()
                self.assertNotIn('class="demo-bar"', text, p)
                self.assertNotIn("This is a demo", text, p)

    def test_each_demo_has_its_template_s_shape(self):
        seen = 0
        for t in TYPES:
            info = json.loads((SITES / t / "template.json").read_text())
            repos = CLIENTS / info["workspace"] / "repos"
            if not repos.is_dir():
                continue
            for repo in repos.iterdir():
                if not (repo / "index.html").exists():
                    continue
                seen += 1
                self.assertEqual(shape((repo / "index.html").read_text()), shape((SITES / t / "index.html").read_text()),
                                 f"{info['workspace']}'s home page has drifted from the {t} template")
                self.assertIn("This is a demo", (repo / "index.html").read_text(), f"{info['workspace']} must say it's a demo")
        if not seen:
            self.skipTest("no demo workspaces on this machine")


if __name__ == "__main__":
    unittest.main()
