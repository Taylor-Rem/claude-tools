"""print — the QR encoder (against a real decoder), the layout math, where a
QR points, the menu parser, and the PDF check.

    python3 -m unittest tests.test_print -q   (from claude-tools/)

The encoder test rasterises the matrix itself (a tiny PNG writer below) and
asks jsQR (node_modules) to read it; the check test renders a real PDF with
the toolbelt's Chromium. Both skip, saying why, when node or the browser is
missing.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import argparse
import importlib.machinery
import importlib.util
import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
_TMP = tempfile.mkdtemp(prefix="print-test-")
os.environ["SITES_REGISTRY"] = str(Path(_TMP) / "sites.json")


def load():
    loader = importlib.machinery.SourceFileLoader("print_tool", str(ROOT / "bin" / "print"))
    spec = importlib.util.spec_from_loader("print_tool", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


P = load()
HAVE_NODE = bool(shutil.which("node")) and (ROOT / "node_modules" / "jsqr").exists()


def png_of(matrix, scale=4, quiet=4):
    n = len(matrix) + 2 * quiet
    rows = []
    for y in range(n * scale):
        my = y // scale - quiet
        line = bytearray([0])
        for x in range(n * scale):
            mx = x // scale - quiet
            dark = 0 <= my < len(matrix) and 0 <= mx < len(matrix) and matrix[my][mx]
            line += b"\x00\x00\x00" if dark else b"\xff\xff\xff"
        rows.append(bytes(line))
    raw = zlib.compress(b"".join(rows))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", n * scale, n * scale, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


class Encoder(unittest.TestCase):
    def test_version_capacity_matches_the_standard(self):
        # byte-mode capacities at level M (ISO 18004 table 7)
        for ver, cap in ((1, 14), (2, 26), (3, 42), (4, 62), (5, 84), (7, 122), (10, 213), (20, 666), (40, 2331)):
            self.assertEqual(P.qr_version_for(cap), ver, cap)
            if ver < 40:
                self.assertEqual(P.qr_version_for(cap + 1), ver + 1, cap + 1)

    def test_size_and_finders(self):
        m = P.qr_matrix("https://patchlamp.com/")
        self.assertEqual(len(m), P.qr_version_for(22) * 4 + 17)
        for (x, y) in ((0, 0), (len(m) - 7, 0), (0, len(m) - 7)):
            self.assertTrue(all(m[y][x + i] for i in range(7)))     # the finder's top edge
            self.assertFalse(m[y + 1][x + 1])                       # its white ring

    @unittest.skipUnless(HAVE_NODE, "node + jsqr not installed (npm install in claude-tools)")
    def test_a_real_decoder_reads_every_version_we_make(self):
        texts = ["https://x.co/", "https://testaurant.pages.dev/#menu",
                 "https://maps.app.goo.gl/AbCdEfGhIjKlMnOp1",
                 "https://www.google.com/maps/place/Testaurant/@40.37,-111.79,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x1",
                 "https://example.com/" + "a" * 150, "https://example.com/?q=" + "é" * 120,
                 "https://example.com/" + "b" * 400]
        with tempfile.TemporaryDirectory() as tmp:
            for i, t in enumerate(texts):
                f = Path(tmp) / f"{i}.png"
                f.write_bytes(png_of(P.qr_matrix(t)))
                self.assertEqual(P.decode(f), t, f"version {P.qr_version_for(len(t.encode()))}")


class Layout(unittest.TestCase):
    def test_tent_is_letter_folded_in_half_with_mirrored_panels(self):
        lay = P.tent_layout()
        self.assertEqual(lay["page"], (8.5, 11.0))
        self.assertEqual(lay["fold_y"], 5.5)
        back, front = lay["panels"]
        self.assertEqual((back["y"], back["rotate"]), (0.0, 180))
        self.assertEqual((front["y"], front["rotate"]), (5.5, 0))
        self.assertEqual(back["h"] + front["h"], 11.0)
        self.assertGreater(front["text_w"], 3.5)                    # the headline has room
        self.assertEqual(lay["qr_regions"], [(0.0, 0.0, 1.0, 0.5), (0.0, 0.5, 1.0, 0.5)])

    def test_sticker_bleed_cut_safe(self):
        lay = P.sticker_layout()
        self.assertEqual(lay["page"], (4.25, 4.25))
        self.assertEqual(lay["cut"], (0.125, 0.125, 4.0, 4.0))
        x, y, w, h = lay["safe"]
        self.assertEqual((x, w), (0.375, 3.5))

    def test_printed_qr_sizes_clear_the_minimum_module(self):
        css = (ROOT / "templates" / "print" / "print.css").read_text()
        long_url = "https://www.google.com/maps/place/Some+Restaurant+Name/@40.3769,-111.7958,17z"
        need = P.qr_min_inches(long_url)
        for sel, size in ((".tent .panel .qr-wrap", 2.3), (".sticker .qr-wrap", 1.35),
                          (".flyer .qr-wrap", 1.7), ("body.qr .qr-wrap", 2.7), (".menu .qr-small", 1.2)):
            self.assertIn(f"{sel} {{ width: {size}in", css)
            self.assertGreaterEqual(size, need, sel)


class Targets(unittest.TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name) / "clients" / "pho-place"
        (self.ws / "repos" / "pho-site").mkdir(parents=True)
        self.meta = {"slug": "pho-place", "name": "Pho Place"}
        self.reg = {"pho-place": {"pho-site": {"host": "cloudflare", "project": "pho-site"}}}
        os.chdir(self.ws)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def ctx(self):
        (self.ws / ".client.json").write_text(json.dumps(self.meta))
        Path(os.environ["SITES_REGISTRY"]).write_text(json.dumps(self.reg))
        P.REGISTRY = Path(os.environ["SITES_REGISTRY"])
        return P.Ctx(argparse.Namespace(site=None, name=None))

    def test_site_url_order(self):
        self.assertEqual(P.resolve_target("site", self.ctx()), "https://pho-site.pages.dev/")
        self.reg["pho-place"]["pho-site"]["pages_host"] = "pho-site-x1.pages.dev"
        self.assertEqual(P.resolve_target(None, self.ctx()), "https://pho-site-x1.pages.dev/")
        self.meta["live_url"] = "https://old.example.com"
        self.assertEqual(P.resolve_target("site", self.ctx()), "https://old.example.com/")
        self.reg["pho-place"]["pho-site"]["domains"] = ["phoplace.com", "www.phoplace.com"]
        self.assertEqual(P.resolve_target("site", self.ctx()), "https://phoplace.com/")

    def test_menu_prefers_a_page_then_an_anchor(self):
        repo = self.ws / "repos" / "pho-site"
        self.assertEqual(P.resolve_target("menu", self.ctx()), "https://pho-site.pages.dev/")
        (repo / "index.html").write_text('<section id="menu"></section><section id="shop"></section>')
        self.assertEqual(P.resolve_target("order", self.ctx()), "https://pho-site.pages.dev/#shop")
        (repo / "menu.html").write_text("menu")
        self.assertEqual(P.resolve_target("menu", self.ctx()), "https://pho-site.pages.dev/menu")

    def test_listing_from_notes_or_stop(self):
        with self.assertRaises(SystemExit):
            P.resolve_target("listing", self.ctx())
        (self.ws / "NOTES.md").write_text("Google listing: https://maps.app.goo.gl/Xy12AbC. Owner: Mike.\n")
        self.assertEqual(P.resolve_target("listing", self.ctx()), "https://maps.app.goo.gl/Xy12AbC")
        self.meta["listing"] = "https://www.google.com/maps/place/Pho+Place"
        self.assertEqual(P.resolve_target("listing", self.ctx()), "https://www.google.com/maps/place/Pho+Place")

    def test_urls_and_nonsense(self):
        ctx = self.ctx()
        self.assertEqual(P.resolve_target("https://a.b/c?d=1", ctx), "https://a.b/c?d=1")
        self.assertEqual(P.resolve_target("phoplace.com/menu", ctx), "https://phoplace.com/menu")
        with self.assertRaises(SystemExit):
            P.resolve_target("the website please", ctx)

    def test_two_sites_need_a_name(self):
        self.reg["pho-place"]["pho-two"] = {"project": "pho-two"}
        with self.assertRaises(SystemExit):
            P.resolve_target("site", self.ctx())

    def test_outside_a_workspace_site_needs_a_url(self):
        os.chdir(self.tmp.name)
        ctx = P.Ctx(argparse.Namespace(site=None, name=None))
        with self.assertRaises(SystemExit):
            P.resolve_target("site", ctx)
        self.assertEqual(P.resolve_target("https://patchlamp.com/", ctx), "https://patchlamp.com/")

    def test_url_words(self):
        self.assertEqual(P.url_words("https://www.phoplace.com/"), "phoplace.com")
        self.assertEqual(P.url_words("https://pho.pages.dev/#shop"), "pho.pages.dev")
        self.assertEqual(P.url_words("https://pho.pages.dev/menu"), "pho.pages.dev/menu")
        self.assertEqual(P.url_words("https://maps.app.goo.gl/Xy"), "Find us on Google Maps")

    def test_brand_from_site_tokens_and_default(self):
        self.assertEqual(P.brand(self.ctx())["source"], "default")
        css = self.ws / "repos" / "pho-site" / "css"
        css.mkdir()
        (css / "style.css").write_text(":root { --ink: #111; --accent: #b4532a; --font-display: Georgia, serif; "
                                       "--bg-line: url(x); }")
        b = P.brand(self.ctx())
        self.assertEqual((b["ink"], b["accent"], b["font_display"]), ("#111", "#b4532a", "Georgia, serif"))
        self.assertEqual(b["line"], P.DEFAULT_BRAND["line"])          # url() never reaches the page


class Menu(unittest.TestCase):
    def test_parse(self):
        m = P.parse_menu_md("# Pho Place\nHouse broth.\n\n## Pho\n- Beef pho — $13\n  Brisket, rare eye.\n"
                            "- Veg pho | $11 | mushroom\n- Chicken pho .... 12.50\n\n## Drinks\n- Tea $3\n- Water\n\n## Empty\n")
        self.assertEqual(m["title"], "Pho Place")
        self.assertEqual(m["note"], "House broth.")
        self.assertEqual([s["name"] for s in m["sections"]], ["Pho", "Drinks"])
        pho = m["sections"][0]["items"]
        self.assertEqual(pho[0], {"name": "Beef pho", "price": "13", "desc": "Brisket, rare eye."})
        self.assertEqual(pho[1], {"name": "Veg pho", "price": "11", "desc": "mushroom"})
        self.assertEqual(pho[2]["price"], "12.50")
        self.assertEqual(m["sections"][1]["items"][1], {"name": "Water", "price": "", "desc": ""})

    def test_money(self):
        self.assertEqual((P.money(1300), P.money(1250)), ("13", "12.50"))


@unittest.skipUnless(HAVE_NODE and shutil.which("pdftoppm") and shutil.which("pdfinfo"),
                     "node/jsqr or poppler-utils missing")
class Check(unittest.TestCase):
    def test_the_check_passes_a_good_pdf_and_catches_bad_ones(self):
        url = "https://testaurant.pages.dev/#menu"
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "q.pdf"
            body = P.fill("qr.html", NAME="Test", QR=P.qr_block(url, P.DEFAULT_BRAND), URL=P.url_words(url))
            P.render(P.page("qr", body, P.DEFAULT_BRAND, 3.0, 3.75), pdf, 3.0, 3.75)
            ok, lines = P.check(pdf, 3.0, 3.75, url)
            self.assertTrue(ok, lines)
            self.assertFalse(P.check(pdf, 3.0, 3.75, "https://elsewhere.example/")[0])
            self.assertFalse(P.check(pdf, 8.5, 11.0, url)[0])

    def test_tent_end_to_end_reads_both_panels(self):
        cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                out = subprocess.run([str(ROOT / "bin" / "print"), "tent", "Order at the counter",
                                      "--qr", "https://example.com/order", "--name", "Pho Place"],
                                     capture_output=True, text=True, timeout=180)
            finally:
                os.chdir(cwd)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn("QR 2/2 reads https://example.com/order", out.stdout)
            last = out.stdout.strip().splitlines()[-1]
            self.assertTrue(last.startswith("/") and last.endswith(".pdf"), last)


if __name__ == "__main__":
    unittest.main()
