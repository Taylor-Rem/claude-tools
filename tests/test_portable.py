"""Portable by construction (ROADMAP B146, plan 55 § 5.12): the engine names no business.

    python3 -m unittest tests.test_portable   (from claude-tools/)

The engine is the seven tools that find and talk to prospects and count the money (leads, outreach,
prep, social, front, books, cloud) and every module in lib/ except the product's own (site_*, the
sandbox's tools, prices). Whatever says which business they work for lives in ventures/<name>/venture.toml;
this test takes its needles from those files (the name, the legal name, every host and domain, the reply
address, the from-name, the town, the demo number, the census file: `Venture.needles()`; and every dollar
amount in its prices module: `Venture.price_needles()`), so a second
venture tests itself the day it is added, and it fails on any of them in an engine file.

When it fails: move the literal into the venture file and read it from `V` (lib/venture.py), rather than
adding an exception here. A new lib/ module passes as long as it names no business.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent / "lib"))

import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

import venture  # noqa: E402

TOOLS = Path(__file__).resolve().parent.parent
ENGINE_TOOLS = ("leads", "outreach", "prep", "social", "front", "books", "cloud")
PRODUCT_LIB = ("site_", "sandbox_tools", "prices")      # the product's own modules (plan 55 § 5.12): they stay


def engine_files(root=TOOLS):
    files = [root / "bin" / t for t in ENGINE_TOOLS]
    files += sorted(p for p in (root / "lib").iterdir()
                    if p.is_file() and p.suffix in (".py", ".mjs", ".js") and not p.name.startswith(PRODUCT_LIB))
    return files


def all_needles(ventures_dir=None):
    ventures_dir = Path(ventures_dir or TOOLS / "ventures")
    out = set()
    for toml in sorted(ventures_dir.glob("*/venture.toml")):
        out |= set(venture.load(toml).needles())
    return sorted(out)


def all_prices(ventures_dir=None):
    """Every dollar amount a venture's prices module says ("$99", "$1,000")."""
    ventures_dir = Path(ventures_dir or TOOLS / "ventures")
    out = set()
    for toml in sorted(ventures_dir.glob("*/venture.toml")):
        out |= set(venture.load(toml).price_needles())
    return sorted(out)


def scan(files, needles, prices=()):
    """[(file, line number, needle, the line)] for every needle in every file, case-insensitively, and every
    price as a whole amount ("$50" hits "$50 a month" and "$50," but not "$500", "$50.25" or "$50,000")."""
    price_res = [(p, re.compile(re.escape(p) + r"(?!\d|[.,]\d)")) for p in prices]
    hits = []
    for f in files:
        for n, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
            low = line.lower()
            for needle in needles:
                if needle in low:
                    hits.append((f, n, needle, line.strip()[:120]))
            for p, rx in price_res:
                if rx.search(line):
                    hits.append((f, n, p, line.strip()[:120]))
    return hits


class PortableTest(unittest.TestCase):
    def test_there_are_needles_and_files(self):
        needles = all_needles()
        for want in ("patchlamp", "patchlamp.com", "trypatchlamp.com", "previews.patchlamp.com", "patchlamp.site",
                     "taylor remund", "american fork", "wasatch.db", "founder@patchlamp.com", "plateful llc"):
            self.assertIn(want, needles)
        names = {f.name for f in engine_files()}
        self.assertTrue({"leads", "outreach", "prep", "social", "front", "books", "cloud", "venture.py"} <= names)
        self.assertFalse({"prices.py", "sandbox_tools.py", "site_chat.py"} & names)

    def test_the_engine_names_no_business(self):
        hits = scan(engine_files(), all_needles(), all_prices())
        self.assertEqual([], [f"{f.relative_to(TOOLS)}:{n}: {needle!r} in {line}" for f, n, needle, line in hits],
                         "a venture's literal in an engine file: move it into ventures/<name>/venture.toml "
                         "(a price into its prices module)")

    def test_the_prices_are_the_modules(self):
        self.assertEqual(all_prices(), ["$1,000", "$20", "$250", "$400", "$50", "$99"])
        self.assertEqual(all_prices(TOOLS / "tests" / "fixtures" / "ventures"), ["$35", "$75"])

    def test_a_planted_price_fails_and_a_cost_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "leads"
            f.write_text('a = "It\'s $99 a month"\nb = "about $0.025 a read, $500 a year, $50,000"\nc = "$50, then"\n')
            self.assertEqual([(n, p) for _, n, p, _ in scan([f], [], all_prices())], [(1, "$99"), (3, "$50")])

    def test_a_planted_literal_fails(self):
        """The same scan over a copy with one domain planted in one tool finds it, and only it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bin").mkdir()
            (root / "lib").mkdir()
            for f in engine_files():
                shutil.copy2(f, root / f.parent.name / f.name)
            with open(root / "bin" / "front", "a") as fh:
                fh.write('\nPLANTED = "https://patchlamp.com/oops"\n')
            hits = scan(engine_files(root), all_needles(), all_prices())
        self.assertTrue(hits)
        self.assertEqual({(f.name, needle) for f, _, needle, _ in hits},
                         {("front", "patchlamp"), ("front", "patchlamp.com")})

    def test_a_second_ventures_needles_are_its_own(self):
        """The example venture's needles come from its file, so planting its name is caught too."""
        needles = all_needles(TOOLS / "tests" / "fixtures" / "ventures")
        self.assertIn("brightwell.example", needles)
        self.assertIn("jordan avery", needles)
        self.assertNotIn("patchlamp", needles)
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "leads"
            f.write_text('print("Hi, I\'m Jordan Avery")\n')
            self.assertEqual([h[2] for h in scan([f], needles)], ["jordan avery"])


class VentureFileTest(unittest.TestCase):
    """lib/venture.py: typed, every field required, a plain error naming the file."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        src = TOOLS / "tests" / "fixtures" / "ventures" / "example" / "venture.toml"
        (self.dir / "example").mkdir()
        self.toml = self.dir / "example" / "venture.toml"
        self.toml.write_text(src.read_text())
        self.env = {k: os.environ.get(k) for k in ("VENTURE", "VENTURES_DIR")}
        os.environ["VENTURES_DIR"] = str(self.dir)
        os.environ.pop("VENTURE", None)
        venture._cache.clear()

    def tearDown(self):
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        venture._cache.clear()
        self.tmp.cleanup()

    def test_reads_typed_fields(self):
        v = venture.venture("example")
        self.assertEqual(v.name, "Brightwell")
        self.assertEqual(v.sender.town, "Springfield")
        self.assertEqual(v.outreach.domains, ["trybrightwell.example"])
        self.assertEqual(v.venture_name, "example")

    def test_a_missing_field_names_the_file_and_the_field(self):
        self.toml.write_text(self.toml.read_text().replace('town = "Springfield"\n', ""))
        with self.assertRaises(venture.VentureError) as cm:
            venture.venture("example")
        self.assertIn(str(self.toml), cm.exception.msg)
        self.assertIn("sender.town", cm.exception.msg)

    def test_a_wrong_type_and_an_unknown_field_are_errors(self):
        self.toml.write_text(self.toml.read_text().replace('domains = ["trybrightwell.example"]', 'domains = "x"'))
        with self.assertRaises(venture.VentureError) as cm:
            venture.venture("example")
        self.assertIn("outreach.domains should be list[str]", cm.exception.msg)
        venture._cache.clear()
        self.toml.write_text(self.toml.read_text().replace('domains = "x"', 'domains = ["a"]\ndomian = "typo"'))
        with self.assertRaises(venture.VentureError) as cm:
            venture.venture("example")
        self.assertIn("outreach.domian", cm.exception.msg)

    def test_unknown_venture_and_no_default(self):
        with self.assertRaises(venture.VentureError) as cm:
            venture.venture("nope")
        self.assertIn("no venture named 'nope'", cm.exception.msg)
        with self.assertRaises(venture.VentureError) as cm:
            venture.venture()
        self.assertIn("DEFAULT", cm.exception.msg)
        (self.dir / "DEFAULT").write_text("example\n")
        self.assertEqual(venture.venture().name, "Brightwell")

    def test_a_venture_error_ends_a_tool_with_its_sentence(self):
        env = dict(os.environ, VENTURE="nope")
        r = subprocess.run([sys.executable, str(TOOLS / "bin" / "front"), "doctor"], capture_output=True, text=True,
                           env=env, timeout=60)
        self.assertEqual(r.returncode, 1)
        self.assertIn("venture: no venture named 'nope'", r.stderr)

    def test_fill_and_from_argv(self):
        v = venture.venture("example")
        self.assertEqual(v.fill("{v:name} at {v:outreach.domains.0|envname}, {kept}"),
                         "Brightwell at TRYBRIGHTWELL_EXAMPLE, {kept}")
        self.assertEqual(v.fill("{v:paths.census|name}"), "oregon.db")
        argv = ["tool", "status", "--venture", "example", "--json"]
        self.assertEqual(venture.from_argv(argv).name, "Brightwell")
        self.assertEqual(argv, ["tool", "status", "--json"])
        self.assertEqual(os.environ["VENTURE"], "example")


if __name__ == "__main__":
    unittest.main()
