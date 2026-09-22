"""leads kit against the Place Details fixtures: no network, no census writes.
    python3 -m unittest discover -s tests -q   (from claude-tools/)
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEADS = HERE.parent / "bin" / "leads"
FIXTURES = HERE / "fixtures" / "leads"


def run(*args, env=None):
    e = dict(os.environ, **(env or {}))
    return subprocess.run([sys.executable, str(LEADS), *args], capture_output=True, text=True, env=e)


@unittest.skipUnless((Path.home() / "projects/plateful/plateful-sales/wasatch.db").exists(), "needs the census")
class KitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {"LEADS_STATE": self.tmp.name, "LEADS_LEDGER": str(Path(self.tmp.name) / "ledger.jsonl")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_fixture_kit_picks_six_open_saturday(self):
        r = run("kit", "--fixture", str(FIXTURES), "--for", "2026-09-26", "--json", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        names = [x["name"] for x in rows]
        self.assertEqual(len(rows), 6)
        self.assertNotIn("China Isle Restaurant", names)      # opens Sat 4pm
        self.assertNotIn("Off Road Mexican Food", names)      # closed Saturdays
        self.assertNotIn("Kahi Sushi", names)                 # CLOSED_TEMPORARILY
        self.assertEqual(names[0], "Whistle Wok")             # nearest first
        fong = next(x for x in rows if x["name"] == "Fong Asian Dining")
        self.assertIn("only 3 photos", " · ".join(fong["faults"]))
        self.assertTrue(any("2★" in f for f in fong["faults"]))
        jal = next(x for x in rows if "Jalisco" in x["name"])
        self.assertIn("no hours on Google", jal["faults"])
        self.assertIn("no website", " ".join(jal["faults"]))
        self.assertFalse((Path(self.tmp.name) / "ledger.jsonl").exists(), "fixtures cost nothing")

    def test_page_and_census_only(self):
        r = run("kit", "--fixture", str(FIXTURES), "--for", "2026-09-26", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Saturday kit — Sat 26 Sep", r.stdout)
        self.assertIn("Skipped: China Isle Restaurant (opens Sat 4pm)", r.stdout)
        self.assertIn("Text me the fix", r.stdout)
        self.assertLess(len(r.stdout), 4000, "one Telegram message")
        r = run("kit", "--census-only", "--no-save", "--for", "2026-09-26", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("census", r.stdout.splitlines()[1])
        self.assertNotIn("g_mp=", r.stdout)

    def test_candidates_and_doctor_run(self):
        r = run("candidates", "--n", "3", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.strip().splitlines()), 4)
        r = run("doctor", env=self.env)
        self.assertIn("census:", r.stdout)


if __name__ == "__main__":
    unittest.main()
