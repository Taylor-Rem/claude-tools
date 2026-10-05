"""img gen: the patchlamp styles bring Patch's portrait as the reference (B112, plan 48).

    python3 -m unittest tests.test_img_style_ref   (from claude-tools/)

image_call is stubbed, so nothing is generated and nothing is paid for: the
test only looks at what would have been sent.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402

import argparse
import base64
import importlib.util
import io
import contextlib
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = Path(__file__).resolve().parent
IMG = HERE.parent / "bin" / "img"

PNG = base64.b64encode(base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")).decode()


def load_img():
    spec = importlib.util.spec_from_loader("img_mod", SourceFileLoader("img_mod", str(IMG)))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class StyleRefTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.img = load_img()
        self.portrait = self.dir / "portrait.jpg"
        self.portrait.write_bytes(b"fake jpeg")
        self.img.PATCH_REF = self.portrait
        self.img.STYLE_REFS = {k: self.portrait for k in self.img.STYLE_REFS}
        self.img.STYLES_FILE = self.dir / "no-styles.json"   # the defaults, not this machine's overrides
        self.calls = []

        def fake_image_call(engine, quality, prompt, aspect=None, sources=(), text_first=False):
            self.calls.append({"prompt": prompt, "sources": list(sources)})
            return (lambda: (PNG, "image/png", 0.0)), "fake-model", "1K", 0.0, "fake:KEY", "KEY"
        self.img.image_call = fake_image_call

    def tearDown(self):
        self.tmp.cleanup()

    def gen(self, style, ref=None, no_style_ref=False):
        args = argparse.Namespace(prompt="Patch at the board", engine="gemini", style=style, quality="menu",
                                  aspect="1:1", ref=ref, no_style_ref=no_style_ref, n=1, out=None,
                                  out_dir=str(self.dir / "out"), ledger=str(self.dir / "ledger.jsonl"), no_ledger=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.img.cmd_gen(args)
        return self.calls[-1]

    def test_both_patchlamp_styles_bring_the_portrait_and_say_so(self):
        for style in ("patchlamp-night", "patchlamp-social"):
            call = self.gen(style)
            self.assertEqual(call["sources"], [str(self.portrait)], style)
            self.assertIn("the one in the reference image", call["prompt"], style)

    def test_plain_brings_nothing(self):
        call = self.gen("plain")
        self.assertEqual(call["sources"], [])
        self.assertNotIn("reference image", call["prompt"])

    def test_no_style_ref_leaves_it_out(self):
        call = self.gen("patchlamp-night", no_style_ref=True)
        self.assertEqual(call["sources"], [])

    def test_an_own_ref_replaces_the_portrait(self):
        other = self.dir / "other.jpg"
        other.write_bytes(b"x")
        call = self.gen("patchlamp-night", ref=[str(other)])
        self.assertEqual(call["sources"], [str(other)])

    def test_the_portrait_passed_by_hand_gets_the_same_sentence(self):
        call = self.gen("patchlamp-night", ref=[str(self.portrait)])
        self.assertEqual(call["sources"], [str(self.portrait)])
        self.assertEqual(call["prompt"].count("the one in the reference image"), 1)

    def test_the_sidecar_records_the_portrait(self):
        self.gen("patchlamp-night")
        [side] = list((self.dir / "out").rglob("*.json"))
        import json
        self.assertEqual(json.loads(side.read_text())["refs"], [str(self.portrait.resolve())])

    def test_the_night_preset_lets_the_product_show_as_shapes(self):
        night = self.img.default_styles()["patchlamp-night"]
        self.assertIn("message bubbles", night)
        self.assertNotIn("no readable screens", night)


if __name__ == "__main__":
    unittest.main()
