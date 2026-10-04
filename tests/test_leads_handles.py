"""B104/B107 (plan 44): a handle or an address that belongs to a namesake never reaches Taylor as a route.

On 2026-10-02 the kit carried @valdezbrothersplumbing for an Orem plumber; the account, its Facebook page and its
domain were a Rio Rancho, NM company's. Since B104 client-leads/scripts/reach.py judges every candidate against the
place and keeps only `high` in its column; these tests are the readers' half: the kit, `kit --json` (the outreach
seam), `leads show` and `leads recheck`. Everything runs on the made-up services census (fixtures/leads-services)
with a `reach` table written by hand, and a stub reach.py through LEADS_REACH_PY; nothing is fetched.

    python3 -m unittest tests.test_leads_handles   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads

import json  # noqa: E402
import sqlite3  # noqa: E402
import unittest  # noqa: E402

from test_leads_today import ANCHOR, Base, leads_module  # noqa: E402

NM = 'another state: "Albuquerque, NM" in the result title'
UNSURE = "research: the result doesn't say where the page is (prep 2026-10-02-a/blue-canyon)"
LOW = "nothing ties it to the place (no Utah, no Lehi, no listing phone)"

# what `reach.py --check --json` prints, for the stub (the shape in its seam docstring)
CHECK_JSON = [
    {"place_id": "FX_S02", "name": "Blue Canyon Landscaping", "fields": {
        "instagram": {"value": "bluecanyonnm", "confidence": "rejected", "reason": NM, "was": "high"},
        "facebook": {"value": "https://www.facebook.com/bluecanyonut", "confidence": "high",
                     "place": "names Lehi (the page title)", "was": "high"}}},
    {"place_id": "FX_S01", "name": "Mike's Pool Care", "fields": {}},
    {"place_id": "FX_S05", "name": "Dave's Handyman Services", "fields": {
        "email": {"value": "dave@daveshandyman.example", "confidence": "low", "hidden": None,
                  "reason": LOW, "was": "high"}}},
]

STUB = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["STUB_ARGV"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if "--check" in sys.argv:
    print(open(os.environ["STUB_CHECK"]).read())
    sys.exit(0)
sys.exit(2)
'''


class Handles(Base):
    def add_reach(self):
        conn = sqlite3.connect(self.db)
        conn.execute("""CREATE TABLE IF NOT EXISTS reach (place_id TEXT PRIMARY KEY, instagram TEXT, facebook TEXT,
                        email TEXT, source TEXT, checked TEXT, evidence TEXT, unconfirmed TEXT)""")
        rows = [
            # Blue Canyon has no website: an Instagram that's another state's, a Facebook page research doubted, an
            # address nothing ties to the place. Nothing in a column.
            ("FX_S02", None, None, None, "search", "2026-10-03T21:00:00", json.dumps({
                "query": '"Blue Canyon Landscaping" Lehi Utah',
                "instagram": {"url": "https://www.instagram.com/bluecanyonnm/", "value": "bluecanyonnm",
                              "title": "Blue Canyon Landscaping | Albuquerque, NM", "confidence": "rejected",
                              "reason": NM, "by": "reach.py"},
                "facebook": {"url": "https://www.facebook.com/bluecanyonut", "value": "https://www.facebook.com/bluecanyonut",
                             "confidence": "unsure", "reason": UNSURE, "by": "prep 2026-10-02-a/blue-canyon"},
                "email": {"url": "https://brave.example/1", "value": "hello@bluecanyon.example", "confidence": "low",
                          "reason": LOW, "by": "reach.py"}}),
             f"instagram={NM}; facebook={UNSURE}; email={LOW}"),
            # Dave's address was stored before B104: no judgement yet, so it reads as low until --check
            ("FX_S05", None, None, "dave@daveshandyman.example", "search", "2026-09-28T09:00:00",
             json.dumps({"query": "x", "email": {"url": "https://brave.example/3"}}), None),
            # Canyon Air's Instagram is tied to the place: the one usable handle
            ("FX_S11", "canyonairhvac", None, None, "search", "2026-10-03T21:00:00", json.dumps({
                "instagram": {"url": "https://www.instagram.com/canyonairhvac/", "value": "canyonairhvac",
                              "confidence": "high", "place": "names Orem (instagram bio)", "by": "reach.py"}}), None),
        ]
        conn.executemany("INSERT OR REPLACE INTO reach VALUES (?,?,?,?,?,?,?,?)", rows)
        conn.commit()
        conn.close()

    def kit(self, *extra):
        return self.run_leads("kit", "--remote", "--segment", "services", "--census-only", "--no-save", "--n", "10",
                              *extra, now=ANCHOR)

    def test_the_kit_json_carries_only_high_and_says_the_rest(self):
        self.add_reach()
        r = self.kit("--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        by = {p["place_id"]: p for p in json.loads(r.stdout)["picks"]}
        blue = by["FX_S02"]
        self.assertIsNone(blue["instagram"])
        self.assertIsNone(blue["facebook"])
        self.assertIsNone(blue["email"])
        self.assertEqual(blue["email_unconfirmed"],
                         {"address": "hello@bluecanyon.example", "why": LOW, "confidence": "low"})
        self.assertIn(f"Instagram refused ({NM})", blue["reach_skipped"])
        fb = next(u for u in blue["reach_unconfirmed"] if u["field"] == "facebook")
        self.assertEqual(fb["confidence"], "unsure")
        self.assertEqual(fb["label"], f"Facebook facebook.com/bluecanyonut: unconfirmed, look before sending ({UNSURE})")
        dave = by["FX_S05"]
        self.assertIsNone(dave["email"], "an address stored before B104 is never a route until it is checked")
        self.assertEqual(dave["email_unconfirmed"]["address"], "dave@daveshandyman.example")
        self.assertIn("stored before B104", dave["email_unconfirmed"]["why"])
        self.assertEqual(by["FX_S11"]["instagram"], "canyonairhvac")
        self.assertIsNone(by["FX_S11"]["email_unconfirmed"])

    def test_the_kit_page_never_makes_an_unconfirmed_handle_the_dm_line(self):
        self.add_reach()
        r = self.kit()
        self.assertEqual(r.returncode, 0, r.stderr)
        page = r.stdout
        block = page.split("Blue Canyon Landscaping", 1)[1].split("\n\n", 1)[0]
        self.assertIn("No page to message — call (801) 555-0102", block)
        self.assertIn(f"Instagram refused ({NM})", block)
        self.assertIn(f"Facebook facebook.com/bluecanyonut: unconfirmed, look before sending ({UNSURE}) — look: "
                      "https://www.facebook.com/bluecanyonut", block)
        self.assertIn(f"email: unconfirmed, call-only ({LOW})", block)
        self.assertNotIn("instagram.com/bluecanyonnm", page)
        self.assertNotIn("Message on Facebook: facebook.com/bluecanyonut", page)
        self.assertNotIn("Email (to: hello@bluecanyon.example)", page)
        self.assertIn("DM on Instagram: instagram.com/canyonairhvac", page)

    def test_show_replaces_a_logged_handle_that_isnt_high_and_says_why(self):
        self.add_reach()
        self.messaged("Blue Canyon Landscaping", ANCHOR, place_id="FX_S02", city="Lehi",
                      reach="Instagram @bluecanyonnm · facebook.com/bluecanyonut · hello@bluecanyon.example")
        r = self.run_leads("show", "Blue Canyon Landscaping", now=ANCHOR)
        self.assertEqual(r.returncode, 0, r.stderr)
        reach = next(line for line in r.stdout.splitlines() if line.strip().startswith("reach:"))
        self.assertEqual(reach.strip(), f"reach: Instagram refused ({NM}) · Facebook unconfirmed, look before sending "
                                        f"({UNSURE}) · email unconfirmed, call-only ({LOW})")
        self.assertNotIn("bluecanyonnm", r.stdout)
        self.assertEqual(self.events()[0]["reach"],
                         "Instagram @bluecanyonnm · facebook.com/bluecanyonut · hello@bluecanyon.example",
                         "the pipeline is never rewritten")

    def test_recheck_lists_each_logged_handle_ok_or_fail_through_reach_check(self):
        self.add_reach()
        stub, argv, check = self.t / "reach-stub.py", self.t / "argv.jsonl", self.t / "check.json"
        stub.write_text(STUB)
        check.write_text(json.dumps(CHECK_JSON))
        self.messaged("Blue Canyon Landscaping", ANCHOR, place_id="FX_S02", city="Lehi",
                      reach="Instagram @bluecanyonnm · facebook.com/bluecanyonut")
        self.messaged("Mike's Pool Care", ANCHOR, place_id="FX_S01", reach="facebook.com/mikespoolcare")
        self.messaged("Dave's Handyman Services", ANCHOR, place_id="FX_S05", city="Lehi",
                      reach="dave@daveshandyman.example")
        self.messaged("Glacier Snow Removal", ANCHOR.replace(day=20), place_id="FX_S08",
                      reach="Instagram @glaciersnowut")                        # last week: not this recheck's
        env = {"LEADS_REACH_PY": str(stub), "STUB_ARGV": str(argv), "STUB_CHECK": str(check)}
        r = self.run_leads("recheck", env=env, now=ANCHOR)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.splitlines(), [
            f"FAIL Blue Canyon Landscaping  @bluecanyonnm — {NM}",
            "ok   Blue Canyon Landscaping  facebook.com/bluecanyonut — names Lehi (the page title)",
            "ok   Mike's Pool Care  facebook.com/mikespoolcare — the listing's own website link",
            f"FAIL Dave's Handyman Services  dave@daveshandyman.example — {LOW}",
            "2 of 4 fail: Blue Canyon Landscaping @bluecanyonnm; Dave's Handyman Services dave@daveshandyman.example "
            "(messaged since 2026-09-28)"])
        called = [json.loads(x) for x in argv.read_text().splitlines()]
        self.assertEqual(called, [["--check", "FX_S02", "FX_S01", "FX_S05", "--json", "--db", str(self.db)]])
        r = self.run_leads("recheck", "--dry-run", "--since", "2026-09-01", env=env, now=ANCHOR)
        self.assertIn("--dry-run", json.loads(argv.read_text().splitlines()[-1]))
        self.assertIn("FX_S08", json.loads(argv.read_text().splitlines()[-1]))

    def test_recheck_says_so_when_nothing_was_messaged(self):
        r = self.run_leads("recheck", env={"LEADS_REACH_PY": str(self.t / "none.py")}, now=ANCHOR)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("nothing to recheck", r.stdout)


class Judgement(unittest.TestCase):
    """The read itself, on a table set by hand."""

    @classmethod
    def setUpClass(cls):
        cls.m = leads_module()

    def judge(self, row, out=None, own=()):
        self.m._REACH = {"P": row}
        try:
            return self.m.reach_judge(dict(out or {}), "P", own=own), self.m.reach_judgement("P")
        finally:
            self.m._REACH = {}

    def test_the_valdez_row_as_it_was_on_2026_10_02_gives_no_route(self):
        # the live row before B104: both columns full, the evidence with titles and no judgement
        row = {"instagram": "valdezbrothersplumbing", "facebook": "facebook.com/valdezbrothersplumbingandheating",
               "email": None, "evidence": json.dumps({
                   "instagram": {"url": "https://www.instagram.com/valdezbrothersplumbing/", "visible": True,
                                 "title": "Valdez Brothers Plumbing & Re-pipe (@valdezbrothersplumbing)"},
                   "facebook": {"url": "https://m.facebook.com/valdezbrothersplumbingandheating/",
                                "title": "Valdez Brothers Plumbing & Heating llc | Rio Rancho NM", "visible": True}})}
        out, j = self.judge(row, {"instagram": "valdezbrothersplumbing",
                                  "facebook": "facebook.com/valdezbrothersplumbingandheating"})
        self.assertIsNone(out["instagram"])
        self.assertIsNone(out["facebook"])
        self.assertEqual({f: x["confidence"] for f, x in j.items()}, {"instagram": "low", "facebook": "low"})
        filled = self.m.reach_fill({"instagram": None, "facebook": None, "email": None}, "P")
        self.assertEqual(filled, {"instagram": None, "facebook": None, "email": None})

    def test_a_listing_own_handle_is_theirs_and_a_hidden_high_is_not_usable(self):
        row = {"instagram": "mikespool", "facebook": None, "email": None, "evidence": json.dumps({
            "instagram": {"value": "mikespool"}, "facebook": {
                "value": "https://www.facebook.com/mikes", "confidence": "high", "visible": False, "reason": "hidden",
                "why": "This content isn't available right now"}}),
            "unconfirmed": "facebook=hidden: This content isn't available right now"}
        out, j = self.judge(row, {"instagram": "mikespool", "facebook": None}, own=("instagram",))
        self.assertEqual(out["instagram"], "mikespool")
        self.assertEqual(j["facebook"]["confidence"], "low")
        self.assertEqual(out["unconfirmed"][0]["label"],
                         "Facebook: unconfirmed, call-only (hidden: This content isn't available right now)")

    def test_parse_unconfirmed_keeps_a_reason_with_semicolons_inside(self):
        p = self.m.parse_unconfirmed('instagram=another state: "Boise; ID" in the title; email=nothing ties it')
        self.assertEqual(p, {"instagram": 'another state: "Boise; ID" in the title', "email": "nothing ties it"})


if __name__ == "__main__":
    unittest.main()
