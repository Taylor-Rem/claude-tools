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
        self.env = {"LEADS_STATE": self.tmp.name, "LEADS_LEDGER": str(Path(self.tmp.name) / "ledger.jsonl"),
                    "LEADS_GROUPS_LOG": str(Path(self.tmp.name) / "leads-from-groups.md"),
                    "CLAUDE_TOOLS_ENV": str(Path(self.tmp.name) / "no-env"), "LEADS_MAIL_ADDRESS": "",
                    "GOOGLE_MAPS_API_KEY": "", "LEADS_PIPELINE": str(Path(self.tmp.name) / "pipeline.jsonl")}

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


    # -- B25: the remote lane -----------------------------------------------------------

    def test_remote_kit_is_six_messages_that_each_name_a_real_fault(self):
        r = run("kit", "--remote", "--census-only", "--json", "--no-save", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        self.assertEqual(len(rows), 6)
        for x in rows:
            self.assertTrue(x["faults"], x["name"])
            self.assertFalse(any(f.startswith(("only ", "rating ")) for f in x["faults"]), x["faults"])
        reachable = [x for x in rows if x["reach"]["instagram"] or x["reach"]["facebook"] or x["reach"]["email"]]
        self.assertEqual(len(reachable), 6, "messageable leads come first")

    def test_remote_page_fits_one_message_and_is_honest_about_email(self):
        r = run("kit", "--remote", "--census-only", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(len(r.stdout), 3901, "one Telegram message")
        self.assertIn("Remote kit —", r.stdout)
        self.assertIn("Free, no strings.", r.stdout)
        self.assertIn("don't send yet", r.stdout)                 # no postal address, no ready email
        self.assertNotIn("not their own", r.stdout.split("Email footer")[0].split('"Hi')[1])
        self.assertNotIn("$", r.stdout)                            # no price in a cold message
        log = (Path(self.tmp.name) / "leads-from-groups.md").read_text()
        self.assertEqual(log.count("| remote kit |"), 6)
        # tomorrow's kit doesn't repeat today's six
        again = json.loads(run("kit", "--remote", "--census-only", "--json", "--no-save", env=self.env).stdout)
        first = json.loads((Path(self.tmp.name) / "remote.jsonl").read_text().splitlines()[0])["place_ids"]
        self.assertFalse(set(first) & {x["place_id"] for x in again})
        env = dict(self.env, LEADS_MAIL_ADDRESS="PO Box 1, American Fork, UT 84003")
        r = run("kit", "--remote", "--census-only", "--no-save", "--allow-repeat", env=env)
        self.assertIn("PO Box 1, American Fork", r.stdout)
        self.assertNotIn("don't send yet", r.stdout)

    def test_diagnose_a_name_from_a_thread_in_three_lines_and_log_it(self):
        r = run("diagnose", "Fong Asian Dining", "--group", "Utah Small Businesses", "--fixture", str(FIXTURES), env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        para = r.stdout.split("\n\n")[0].splitlines()
        self.assertEqual(len(para), 3, r.stdout)
        self.assertTrue(para[0].startswith("Fong Asian Dining: "))
        self.assertIn("only 3 photos", para[1])
        self.assertIn("Happy to walk you through", para[2])
        self.assertNotIn("$", r.stdout)
        log = (Path(self.tmp.name) / "leads-from-groups.md").read_text()
        self.assertIn("| Fong Asian Dining | ", log)
        self.assertIn("group: Utah Small Businesses", log)

    def test_diagnose_census_only_with_a_city_and_an_unknown_name(self):
        r = run("diagnose", "Off Road Mexican, American Fork", "--no-log", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Off Road Mexican Food:", r.stdout)
        self.assertIn("no website", r.stdout)
        self.assertIn("census only", r.stdout)
        r = run("diagnose", "Zzqx Nonexistent Eatery", env=self.env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("isn't in the census", r.stderr)
        self.assertFalse((Path(self.tmp.name) / "leads-from-groups.md").exists())


    # -- B7: the pipeline ---------------------------------------------------------------

    def events(self):
        p = Path(self.tmp.name) / "pipeline.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def test_one_text_logs_a_counter_visit_and_returns_tomorrows_list(self):
        r = run("log", "Whistle Wok", "talked", "owner Mike, wants the demo", "--who", "Mike", "--next", "tomorrow", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Logged: Whistle Wok (American Fork) — talked → contacted", r.stdout)
        tomorrow = r.stdout.split("\n\n", 1)[1]
        self.assertTrue(tomorrow.startswith("Tomorrow, "), tomorrow)
        self.assertIn("1. Whistle Wok (American Fork) · contacted, talked", tomorrow)
        self.assertIn('"owner Mike, wants the demo"', tomorrow)
        self.assertIn("NEW ", tomorrow)                               # topped up to six from the census
        self.assertEqual(tomorrow.count("NEW "), 5)
        [e] = self.events()
        self.assertEqual((e["who"], e["stage"], e["via"] if "via" in e else None), ("Mike", "contacted", None))
        self.assertTrue(e["place_id"].startswith("ChIJ"))

    def test_stages_follow_ups_and_the_week(self):
        run("log", "Whistle Wok", "talked", env=self.env)
        run("log", "Whistle Wok", "interested", "wants pricing", env=self.env)       # same lead, moves on
        run("log", "Off Road Mexican, American Fork", "lost", "happy with DoorDash", env=self.env)
        run("log", "Joe's Taco Truck, Lehi", "messaged", "--next", "today", env=self.env)
        self.assertEqual(len({e["key"] for e in self.events()}), 3)
        joe = [e for e in self.events() if e["name"] == "Joe's Taco Truck"][0]
        self.assertIsNone(joe.get("place_id"), "not The Taco Truck: a wrong match is worse than none")
        due = run("due", env=self.env).stdout
        self.assertIn("Joe's Taco Truck (Lehi)", due)
        self.assertNotIn("Off Road", due)
        show = run("show", "whistle wok", env=self.env).stdout
        self.assertIn("interested", show.splitlines()[0])
        self.assertIn("wants pricing", show)
        week = run("week", env=self.env).stdout
        self.assertIn("3 conversations, 1 message sent · 1 interested", week)
        self.assertIn("0 won so far", week)
        pipe = run("pipeline", env=self.env).stdout
        self.assertIn("interested: 1", pipe)
        self.assertIn("lost: 1", pipe)
        # the kits leave a lost lead and one with a follow-up ahead alone
        kit = json.loads(run("kit", "--remote", "--census-only", "--json", "--no-save", env=self.env).stdout)
        self.assertNotIn("Off Road Mexican Food", [x["name"] for x in kit])
        self.assertNotIn("WHISTLE WOK", [x["name"] for x in kit])

    def test_sent_marks_remote_kit_picks_as_messaged(self):
        run("kit", "--remote", "--census-only", env=self.env)
        r = run("sent", "1", "3", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Logged 2 sent", r.stdout)
        self.assertEqual([e["outcome"] for e in self.events()], ["messaged", "messaged"])
        self.assertNotEqual(run("sent", "9", env=self.env).returncode, 0)

    def test_dates_a_phone_would_type(self):
        for when in ("fri", "friday", "next fri", "3d", "2w", "oct 3", "2026-10-01"):
            r = run("log", "Whistle Wok", "later", "--next", when, env=self.env)
            self.assertEqual(r.returncode, 0, f"{when}: {r.stderr}")
        r = run("log", "Whistle Wok", "later", "--next", "someday", env=self.env)
        self.assertIn("can't read the date", r.stderr)
        self.assertNotEqual(run("log", "Whistle Wok", "maybe", env=self.env).returncode, 0)


if __name__ == "__main__":
    unittest.main()
