"""`leads preview --from-press` and `--press-tokens` — the press link's laptop half (ROADMAP B91,
~/projects/plans/41-the-press-link.md).

    python3 -m unittest discover -s tests -q   (from claude-tools/)

Offline, on test_leads_batch's fixture census, stand-in `outreach`, `site` and `img`: outreach's
sequences.json is written here by hand, the way `outreach send --batch --go` leaves it, and nothing
reaches Cloudflare or Google.

What's pinned: the token list is sha256 of outreach's tokens and nothing else, a suppressed address,
domain or place is `removed`, and no list is made when the suppression list can't be read; a press
by hash or by token builds the business's preview and answers its URL; a second press reuses it; an
unknown hash builds nothing; a suppressed business builds nothing; the first press, only, carries
the brief and writes one pipeline line; --no-publish never answers ok.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import hashlib  # noqa: E402
import json  # noqa: E402
import unittest  # noqa: E402

import test_leads_batch as tb  # noqa: E402  (its census, its stand-in outreach, site and img)


def sha(t):
    return hashlib.sha256(t.encode()).hexdigest()


class PressTest(unittest.TestCase):
    setUp = tb.BatchTest.setUp
    tearDown = tb.BatchTest.tearDown
    run_leads = tb.BatchTest.run_leads

    def seqs(self, *rows):
        d = self.t / "outreach"
        d.mkdir(parents=True, exist_ok=True)
        (d / "sequences.json").write_text(json.dumps([
            {"id": f"b/{pid}", "place_id": pid, "name": name, "email": email, "token": tok, "status": "active",
             "city": "Lehi", "faults": ["a", "b"], "touches": []} for pid, name, email, tok in rows]))

    def press(self, value, *extra):
        r = self.run_leads("preview", "--from-press", value, "--json", "--hero", "none", *extra)
        return r, json.loads(r.stdout)

    def test_tokens_are_hashes_with_a_state(self):
        self.seqs(("FX_B01", "Alpine Plumbing", "owner@alpineplumbing.example", "tokA1234abcd"),
                  ("FX_B02", "Juniper Plumbing", "hi@juniperplumbing.example", "tokB1234abcd"),
                  ("FX_B03", "X", "", ""))                                   # no token: not a link
        r = self.run_leads("preview", "--press-tokens", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual({sha("tokA1234abcd"): "active", sha("tokB1234abcd"): "removed"},
                         {x["hash"]: x["state"] for x in out["links"]})   # juniperplumbing.example is suppressed
        self.assertNotIn("tokA1234abcd", r.stdout)                         # the token itself never leaves the laptop
        self.assertNotIn("Alpine", r.stdout)

    def test_no_token_list_without_the_suppression_list(self):
        self.seqs(("FX_B01", "Alpine Plumbing", "owner@alpineplumbing.example", "tokA1234abcd"))
        r = self.run_leads("preview", "--press-tokens", "--json", env={"FAKE_SUPPRESS": ""})
        self.assertEqual(r.returncode, 2)
        self.assertFalse(json.loads(r.stdout)["ok"])

    def test_a_press_builds_then_reuses_and_only_the_first_carries_the_brief(self):
        self.seqs(("FX_B01", "Alpine Plumbing", "owner@alpineplumbing.example", "tokA1234abcd"))
        r, out = self.press(sha("tokA1234abcd"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(("ready", True, False, True), (out["state"], out["ok"], out["reused"], out["first"]))
        self.assertTrue(out["url"].startswith("https://previews.patchlamp.com/alpine-plumbing"))
        self.assertIn("Alpine Plumbing", out["brief"] or "")
        lines = [json.loads(x) for x in self.pipeline.read_text().splitlines()]
        self.assertEqual(["interested"], [x["outcome"] for x in lines if x.get("place_id") == "FX_B01"])
        builds = (self.t / "site.jsonl").read_text().count('"previews"')

        r, again = self.press("tokA1234abcd")                              # by token works too
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((again["url"], True, False, None), (out["url"], again["reused"], again["first"], again["brief"]))
        self.assertEqual(builds, (self.t / "site.jsonl").read_text().count('"previews"'))   # nothing published again
        lines = [json.loads(x) for x in self.pipeline.read_text().splitlines()]
        self.assertEqual(1, sum(1 for x in lines if x.get("place_id") == "FX_B01"))

    def test_an_unknown_link_builds_nothing(self):
        self.seqs(("FX_B01", "Alpine Plumbing", "owner@alpineplumbing.example", "tokA1234abcd"))
        r, out = self.press(sha("guessed-token"))
        self.assertEqual((r.returncode, out["state"], out["url"]), (0, "unknown", None))
        self.assertFalse((self.t / "site.jsonl").exists())

    def test_a_suppressed_business_builds_nothing(self):
        self.seqs(("FX_B02", "Juniper Plumbing", "hi@juniperplumbing.example", "tokB1234abcd"))
        r, out = self.press("tokB1234abcd")
        self.assertEqual((r.returncode, out["state"], out["url"], out["first"]), (0, "removed", None, False))
        self.assertFalse((self.t / "site.jsonl").exists())
        r = self.run_leads("preview", "--from-press", "tokB1234abcd", "--json", env={"FAKE_SUPPRESS": ""})
        self.assertEqual((r.returncode, json.loads(r.stdout)["state"]), (2, "failed"))   # can't tell: never build

    def test_no_publish_is_never_ok(self):
        self.seqs(("FX_B01", "Alpine Plumbing", "owner@alpineplumbing.example", "tokA1234abcd"))
        r, out = self.press("tokA1234abcd", "--no-publish")
        self.assertEqual(out["state"], "ready")
        self.assertFalse(out["ok"])
        self.assertFalse(out["first"])                                     # a rehearsal records no press
        self.assertFalse((self.t / "site.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
