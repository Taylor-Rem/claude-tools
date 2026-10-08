"""The venture file (ROADMAP B146, plan 55 § 5.12): the engine tools say the same thing with the identity
moved into ventures/patchlamp/venture.toml, and say another business's identity with another file.

    python3 -m unittest tests.test_venture   (from claude-tools/)

The goldens in fixtures/venture/golden/ were captured on `main` before the move (tests/venture_capture.py
--write); every command runs offline against made-up data and stub servers.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads

import unittest  # noqa: E402

import venture_capture as vc  # noqa: E402


class GoldenTest(unittest.TestCase):
    """VENTURE unset and VENTURE=patchlamp reproduce today's output byte for byte."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        cls.unset = vc.capture({})
        cls.named = vc.capture({"VENTURE": "patchlamp"})

    def check(self, got):
        names = sorted(p.stem for p in vc.GOLDEN.glob("*.txt"))
        self.assertTrue(names)
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(got[name], (vc.GOLDEN / f"{name}.txt").read_text())

    def test_unset_reproduces_the_goldens(self):
        self.check(self.unset)

    def test_patchlamp_reproduces_the_goldens(self):
        self.check(self.named)


if __name__ == "__main__":
    unittest.main()
