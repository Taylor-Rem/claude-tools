"""The "Patched by Patchlamp" footer badge (ROADMAP B60, GROWTH § 15.2) — no network.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

What's pinned: every kind of site carries the badge on every page that has a
footer, with the exact words, its own segment's page on patchlamp.com and the
`?from=badge` tag the front-door counter reads (`patchlamp` HitController);
the section library's shell carries it in the client half only, so a preview
doesn't claim to be someone's site and a claimed one does; the stylesheet
defines it once, the same in every type; and `badge: off` in a workspace's
NOTES.md takes it out of what `site publish` uploads while leaving the repo
alone.
"""

import importlib.machinery
import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITES = ROOT / "templates" / "sites"
TYPES = sorted(d.name for d in SITES.iterdir() if d.is_dir() and not d.name.startswith("_"))
# each kind of site links the segment page it belongs to; template.json is where
# that lives, so the renderer (`leads preview`) and the static templates agree
WANT = {
    "business": "https://patchlamp.com/?from=badge",
    "service": "https://patchlamp.com/for/home-services?from=badge",
    "portfolio": "https://patchlamp.com/for/creatives?from=badge",
    "store": "https://patchlamp.com/for/makers-and-retail?from=badge",
    "nonprofit": "https://patchlamp.com/for/nonprofits?from=badge",
    "restaurant": "https://patchlamp.com/restaurants?from=badge",
}
SEGMENT = {t: json.loads((SITES / t / "template.json").read_text()).get("badge") for t in TYPES}


def load_site():
    loader = importlib.machinery.SourceFileLoader("site_tool_badge", str(ROOT / "bin" / "site"))
    spec = importlib.util.spec_from_loader("site_tool_badge", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class BadgeTemplateTest(unittest.TestCase):
    def test_every_type_names_its_segment_page(self):
        self.assertEqual(SEGMENT, WANT, "template.json's badge is where each type's segment page lives")
        for t in TYPES:
            self.assertTrue(SEGMENT[t].endswith("?from=badge"),
                            f"{t}: the link carries ?from=badge so `front` counts it")

    def test_every_footer_carries_the_badge(self):
        for t in TYPES:
            for p in sorted((SITES / t).rglob("*.html")):
                html = p.read_text()
                if 'class="site-footer"' not in html:
                    continue                                   # a page with no footer (some 404s)
                # the section library's shell is one file for every type: the href is
                # filled from template.json when a page is rendered
                href = "{{badge}}" if p.parent.name == "sections" else SEGMENT[t]
                with self.subTest(page=str(p.relative_to(SITES))):
                    self.assertIn(f'<a href="{href}" rel="noopener">Patched by Patchlamp</a>', html)
                    self.assertEqual(html.count("patchlamp-badge"), 1, "one badge a page")
                    # last in the footer, after the copyright
                    footer = html[html.index('class="site-footer"'):]
                    self.assertLess(footer.index("copyright"), footer.index("patchlamp-badge"))

    def test_the_library_badges_the_client_half_only(self):
        """A preview says whose it is in its own words; the badge belongs to a site
        that has been claimed, so it sits inside the <!--c:footer …--> block."""
        for t in TYPES:
            shell = SITES / t / "sections" / "_page.html"
            if not shell.exists():
                continue
            html = shell.read_text()
            client = re.search(r"<!--c:footer\n(.*?)\n[ \t]*/c:footer-->", html, re.S)
            self.assertTrue(client, shell)
            self.assertIn("patchlamp-badge", client.group(1), shell)
            self.assertIn('href="{{badge}}"', client.group(1),
                          f"{shell} is one file for every type with a library: the href is filled per type")
            self.assertEqual(html.count("patchlamp-badge"), 1, shell)
            # The renderer resolves <!--if:…--> before a page is written, so the block
            # holds no comment by the time a browser sees it — the badge must add none,
            # or it would close the c:footer comment early on the preview.
            badge = [ln for ln in client.group(1).splitlines() if "patchlamp-badge" in ln]
            self.assertEqual(len(badge), 1, shell)
            self.assertNotIn("<!--", badge[0], f"{shell}: the badge line must hold no comment")
            self.assertNotIn("-->", badge[0], f"{shell}: the badge line must hold no comment")

    def test_the_stylesheet_defines_it_once_everywhere(self):
        want = None
        for t in TYPES:
            css = (SITES / t / "css" / "style.css").read_text()
            rule = css[css.index(".patchlamp-badge"):]
            self.assertIn("opacity", rule)
            self.assertIn("color: inherit", rule)
            if want is None:
                want = rule
            self.assertEqual(rule, want, f"{t}/css/style.css: the badge's rules differ from business's")


class BadgeOptOutTest(unittest.TestCase):
    def setUp(self):
        self.site = load_site()
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def notes(self, text):
        (self.ws / "NOTES.md").write_text(text)

    def test_the_phrase(self):
        self.assertFalse(self.site.badge_off(self.ws), "no NOTES.md is not an opt-out")
        self.notes("**Who this is.** A pool company.\n")
        self.assertFalse(self.site.badge_off(self.ws))
        for phrase in ("badge: off\n", "Badge: off\n", "- badge: off\n", "**badge**: off (Lynn asked)\n",
                       "Who this is.\n\nbadge: off\n"):
            self.notes(phrase)
            self.assertTrue(self.site.badge_off(self.ws), phrase)
        for phrase in ("badge: on\n", "the badge: off is not what he said\n", "badges: off\n"):
            self.notes(phrase)
            self.assertFalse(self.site.badge_off(self.ws), phrase)

    def test_the_strip_takes_the_badge_and_nothing_else(self):
        tree = self.ws / "public"
        tree.mkdir()
        page = (SITES / "service" / "index.html").read_text()
        (tree / "index.html").write_text(page)
        (tree / "photos.html").write_text((SITES / "service" / "photos.html").read_text())
        (tree / "css").mkdir()
        (tree / "css" / "style.css").write_text((SITES / "service" / "css" / "style.css").read_text())
        self.assertEqual(self.site.strip_badge(tree), 2)
        for p in (tree / "index.html", tree / "photos.html"):
            out = p.read_text()
            self.assertNotIn("Patched by Patchlamp", out)
            self.assertNotIn("patchlamp-badge", out)
            self.assertIn("copyright", out)
            self.assertIn("</footer>", out)
        self.assertIn("patchlamp-badge", (tree / "css" / "style.css").read_text(),
                      "the stylesheet is left alone; one dead rule is cheaper than a second exception")
        self.assertEqual(self.site.strip_badge(tree), 0, "nothing to do the second time")

    def test_has_badge_reads_the_repo(self):
        repo = self.ws / "repos" / "x"
        repo.mkdir(parents=True)
        self.assertFalse(self.site.has_badge(repo))
        (repo / "index.html").write_text((SITES / "store" / "index.html").read_text())
        self.assertTrue(self.site.has_badge(repo))


if __name__ == "__main__":
    unittest.main()
