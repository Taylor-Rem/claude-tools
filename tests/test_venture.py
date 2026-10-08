"""The venture file (ROADMAP B146, plan 55 § 5.12): the engine tools say the same thing with the identity
moved into ventures/patchlamp/venture.toml, and say another business's identity with another file.

    python3 -m unittest tests.test_venture   (from claude-tools/)

The goldens in fixtures/venture/golden/ were captured on `main` before the move (tests/venture_capture.py
--write); every command runs offline against made-up data and stub servers.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads

import sys  # noqa: E402
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


EXAMPLE_DIR = vc.HERE / "fixtures" / "ventures"
EXAMPLE_ADDRESS = "PO Box 9, Springfield, OR 97477"
EXAMPLE_ENV = {"VENTURES_DIR": str(EXAMPLE_DIR), "VENTURE": "example", "BRIGHTWELL_MAIL_ADDRESS": EXAMPLE_ADDRESS,
               "OUTREACH_FROM": "jordan@trybrightwell.example"}


class ExampleTest(unittest.TestCase):
    """VENTURE=example (tests/fixtures/ventures/example/venture.toml): the same tools speak for Brightwell."""

    @classmethod
    def setUpClass(cls):
        cls.out = vc.capture(EXAMPLE_ENV, only={"leads-kit", "leads-kit-remote", "outreach-status", "front-doctor"})

    def test_nothing_says_patchlamp_or_its_sender(self):
        for name, text in self.out.items():
            with self.subTest(name=name):
                if name != "front-doctor":          # the example's site has no secret here: doctor says so, exit 1
                    self.assertIn("--- exit 0", text)
                low = text.lower()
                for needle in ("patchlamp", "taylor remund", "plateful", "founder@", "trypatchlamp"):
                    self.assertNotIn(needle, low)

    def test_the_kit_is_from_the_examples_town(self):
        self.assertIn("nearest Springfield with no site of their own", self.out["leads-kit"])
        self.assertIn("brightwell.example/examples", self.out["leads-kit"])

    def test_the_remote_kit_greets_as_the_example_and_signs_with_its_address(self):
        r = self.out["leads-kit-remote"]
        self.assertIn("Hi, I'm Jordan. A small business owner in Springfield.", r)
        self.assertIn("— Jordan Avery · Brightwell (Brightwell Works LLC) · hello@brightwell.example · " + EXAMPLE_ADDRESS, r)
        self.assertIn("Email footer (every cold email, from hello@):", r)

    def test_outreach_status_names_the_example_its_address_and_domains(self):
        s = self.out["outreach-status"]
        self.assertIn(f"for: Brightwell (example), from Jordan Avery in Springfield · sending domains "
                      f"trybrightwell.example · postal address {EXAMPLE_ADDRESS}", s)
        self.assertIn("jordan@trybrightwell.example", s)

    def test_front_reads_the_examples_env_names(self):
        # PATCHLAMP_URL and its secret are set in the capture's env; the example reads its own names, finds
        # neither, and says so without a request
        d = self.out["front-doctor"]
        self.assertIn("brightwell: https://brightwell.example\n  FAIL no BRIGHTWELL_RELAY_SECRET in the toolbelt", d)

    def test_the_flag_does_what_the_env_does(self):
        import os
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            env = {k: v for k, v in os.environ.items() if k != "VENTURE"}
            env.update(VENTURES_DIR=str(EXAMPLE_DIR), CLAUDE_TOOLS_ENV=os.devnull, OUTREACH_PROVIDER="fake",
                       OUTREACH_STATE=tmp, OUTREACH_LEDGER=tmp + "/ledger.jsonl", OUTREACH_NOW="2026-09-28T09:00:00")
            r = subprocess.run([sys.executable, str(vc.BIN / "outreach"), "status", "--venture", "example"],
                               capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("for: Brightwell (example), from Jordan Avery in Springfield", r.stdout)


if __name__ == "__main__":
    unittest.main()
