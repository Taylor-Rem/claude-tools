"""gbp against recorded Google responses: no network, nothing written anywhere.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

GBP_FIXTURES serves tests/fixtures/gbp/routes.json; GBP_RECORD logs every
request the tool would send, which is what these assert on — the request
body is the contract with Google, the printed text is what the owner hears.
"""

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
GBP = HERE.parent / "bin" / "gbp"
FIXTURES = HERE / "fixtures" / "gbp"
FIXTURES_403 = HERE / "fixtures" / "gbp-403"
CREDS = {"GBP_ACCESS_TOKEN": "ya29.fake", "GBP_LOCATION": "locations/129",
         "GBP_ACCOUNT": "accounts/104", "GBP_LOCATION_TITLE": "Fong Asian Dining"}


def thanksgiving(year):
    first = dt.date(year, 11, 1)
    return first + dt.timedelta(days=(3 - first.weekday()) % 7 + 21)


class GbpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.record = Path(self.tmp.name) / "requests.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_gbp(self, *args, fixtures=FIXTURES, creds=True, extra=None):
        env = dict(os.environ, GBP_FIXTURES=str(fixtures), GBP_RECORD=str(self.record),
                   CLAUDE_TOOLS_ENV=str(Path(self.tmp.name) / "no-env"))
        for k in ("GBP_ACCESS_TOKEN", "GBP_LOCATION", "GBP_ACCOUNT", "GBP_LOCATION_TITLE"):
            env.pop(k, None)
        if creds:
            env.update(CREDS)
        env.update(extra or {})
        return subprocess.run([sys.executable, str(GBP), *args], capture_output=True, text=True, env=env, cwd=self.tmp.name)

    def sent(self, method=None):
        if not self.record.exists():
            return []
        rows = [json.loads(line) for line in self.record.read_text().splitlines()]
        return [r for r in rows if method is None or r["method"] == method]

    # -- the acceptance line ------------------------------------------------------

    def test_closed_thanksgiving_sets_one_special_day_and_keeps_the_others(self):
        r = self.run_gbp("hours", "holiday", "thanksgiving", "closed")
        self.assertEqual(r.returncode, 0, r.stderr)
        patch = self.sent("PATCH")
        self.assertEqual(len(patch), 1)
        self.assertEqual(patch[0]["params"], {"updateMask": "specialHours"})
        periods = patch[0]["body"]["specialHours"]["specialHourPeriods"]
        want = thanksgiving(2026 if dt.date.today() <= thanksgiving(2026) else 2027)
        self.assertIn({"startDate": {"year": want.year, "month": want.month, "day": want.day},
                       "endDate": {"year": want.year, "month": want.month, "day": want.day}, "closed": True}, periods)
        # the Christmas Day the listing already had is still there
        self.assertIn({"year": 2026, "month": 12, "day": 25}, [p["startDate"] for p in periods])
        self.assertIn("(thanksgiving)", r.stdout)
        self.assertIn(want.strftime("%a %-d %b %Y"), r.stdout)
        self.assertIn("Google now has", r.stdout)

    def test_a_holiday_they_are_open_but_different_hours(self):
        r = self.run_gbp("hours", "holiday", "2026-12-24", "09:00-14:00")
        self.assertEqual(r.returncode, 0, r.stderr)
        periods = self.sent("PATCH")[0]["body"]["specialHours"]["specialHourPeriods"]
        eve = next(p for p in periods if p["startDate"] == {"year": 2026, "month": 12, "day": 24})
        self.assertEqual(eve, {"startDate": {"year": 2026, "month": 12, "day": 24},
                               "endDate": {"year": 2026, "month": 12, "day": 24},
                               "closed": False, "openTime": {"hours": 9}, "closeTime": {"hours": 14}})
        self.assertEqual([p["startDate"]["month"] for p in periods], [12, 12], "sorted by date")

    def test_clearing_a_special_day_and_clearing_one_that_was_never_set(self):
        r = self.run_gbp("hours", "clear", "christmas-2026")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.sent("PATCH")[0]["body"]["specialHours"]["specialHourPeriods"], [])
        self.setUp()
        r = self.run_gbp("hours", "clear", "2026-07-04")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Nothing special was set", r.stdout)
        self.assertEqual(self.sent("PATCH"), [], "nothing to change, nothing sent")

    # -- regular hours --------------------------------------------------------------

    def test_setting_weekly_hours_merges_with_the_days_it_was_not_told_about(self):
        r = self.run_gbp("hours", "set", "sun", "closed", "mon-fri", "11:00-21:30")
        self.assertEqual(r.returncode, 0, r.stderr)
        patch = self.sent("PATCH")[0]
        self.assertEqual(patch["params"], {"updateMask": "regularHours"})
        periods = patch["body"]["regularHours"]["periods"]
        days = [p["openDay"] for p in periods]
        self.assertNotIn("SUNDAY", days, "closed means no period at all")
        self.assertEqual(days, ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"])
        self.assertEqual(periods[0], {"openDay": "MONDAY", "openTime": {"hours": 11},
                                      "closeDay": "MONDAY", "closeTime": {"hours": 21, "minutes": 30}})
        self.assertEqual(periods[-1]["closeTime"], {"hours": 22}, "Saturday was left as it was")
        self.assertIn("Mon, Tue, Wed, Thu, Fri, Sun", r.stdout)

    def test_late_night_and_am_pm_and_a_bad_time(self):
        r = self.run_gbp("hours", "set", "fri", "5pm-1am")
        self.assertEqual(r.returncode, 0, r.stderr)
        fri = next(p for p in self.sent("PATCH")[0]["body"]["regularHours"]["periods"] if p["openDay"] == "FRIDAY")
        self.assertEqual(fri, {"openDay": "FRIDAY", "openTime": {"hours": 17},
                               "closeDay": "SATURDAY", "closeTime": {"hours": 1}}, "past midnight closes the next day")
        self.setUp()
        r = self.run_gbp("hours", "set", "fri", "elevenish")
        self.assertEqual(r.returncode, 1)
        self.assertIn("couldn't read the hours", r.stderr)
        self.assertEqual(self.sent("PATCH"), [])

    def test_holiday_names_resolve_and_an_unknown_one_is_refused(self):
        r = self.run_gbp("hours", "holidays")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("thanksgiving", r.stdout)
        self.assertIn("pioneer-day", r.stdout)
        self.assertIn("Google stores the date and open/closed", r.stdout)
        r = self.run_gbp("hours", "holiday", "st-swithins-day", "closed")
        self.assertEqual(r.returncode, 1)
        self.assertIn("I don't know the date", r.stderr)

    # -- posts, photos, reviews --------------------------------------------------------

    def test_a_post_with_a_photo_url_and_a_button(self):
        r = self.run_gbp("post", "Fresh pho every Saturday.", "--photo", "https://example.com/pho.jpg",
                         "--url", "https://fong.example.com", "--cta", "ORDER")
        self.assertEqual(r.returncode, 0, r.stderr)
        body = self.sent("POST")[0]["body"]
        self.assertEqual(body["summary"], "Fresh pho every Saturday.")
        self.assertEqual(body["topicType"], "STANDARD")
        self.assertEqual(body["callToAction"], {"actionType": "ORDER", "url": "https://fong.example.com"})
        self.assertEqual(body["media"], [{"mediaFormat": "PHOTO", "sourceUrl": "https://example.com/pho.jpg"}])
        self.assertIn("about a week", r.stdout)

    def test_a_photo_from_the_workspace_goes_through_the_upload_flow(self):
        photo = Path(self.tmp.name) / "pho.jpg"
        photo.write_bytes(b"\xff\xd8\xff" + b"0" * 2048)
        r = self.run_gbp("photo", str(photo), "--category", "FOOD_AND_DRINK")
        self.assertEqual(r.returncode, 0, r.stderr)
        urls = [x["url"] for x in self.sent()]
        self.assertTrue(any(u.endswith("/media:startUpload") for u in urls), urls)
        self.assertTrue(any("upload/v1/media/uploads/AbCd1234" in u for u in urls), urls)
        create = [x for x in self.sent("POST") if x["url"].endswith("/media")][0]["body"]
        self.assertEqual(create, {"mediaFormat": "PHOTO", "locationAssociation": {"category": "FOOD_AND_DRINK"},
                                  "dataRef": {"resourceName": "uploads/AbCd1234"}})
        self.assertIn("Photo added to Google (food and drink)", r.stdout)

    def test_reviews_unanswered_then_a_reply_to_the_newest(self):
        r = self.run_gbp("reviews", "--unanswered")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Maria S.", r.stdout)
        self.assertNotIn("Dev P.", r.stdout, "that one already has an owner reply")
        self.assertIn("★★★★★", r.stdout)
        self.setUp()
        r = self.run_gbp("reply", "1", "Thanks Maria — see you Saturday.")
        self.assertEqual(r.returncode, 0, r.stderr)
        put = self.sent("PUT")[0]
        self.assertTrue(put["url"].endswith("/reviews/AbC1/reply"), put["url"])
        self.assertEqual(put["body"], {"comment": "Thanks Maria — see you Saturday."})
        self.assertIn("Replied to Maria S.", r.stdout)
        self.setUp()
        self.assertEqual(self.run_gbp("reply", "9", "hi").returncode, 1, "there is no review 9")

    # -- reading, dry runs, and the two ways it can't work ------------------------------

    def test_show_reads_the_listing_back_in_plain_words(self):
        r = self.run_gbp("show")
        self.assertEqual(r.returncode, 0, r.stderr)
        for want in ("Fong Asian Dining", "456 E State St #1200, American Fork", "(801) 701-0762",
                     "Asian restaurant", "Mon  11am–9pm", "Sat  11am–10pm"):
            self.assertIn(want, r.stdout)
        self.assertEqual(self.sent("PATCH"), [])
        self.assertNotIn("ya29", r.stdout, "never print the token")

    def test_dry_run_sends_nothing(self):
        r = self.run_gbp("--dry-run", "hours", "holiday", "2026-11-26", "closed")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would PATCH", r.stdout)
        self.assertTrue(all(x["dry"] for x in self.sent("PATCH")))

    def test_without_a_connection_it_says_how_to_get_one(self):
        r = self.run_gbp("show", creds=False, fixtures=FIXTURES)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no Google listing in this run's environment", r.stderr)
        r = self.run_gbp("doctor", creds=False)
        self.assertEqual(r.returncode, 1)
        self.assertIn("connections google invite", r.stdout)

    def test_doctor_says_quota_is_zero_honestly_until_google_approves(self):
        r = self.run_gbp("doctor", fixtures=FIXTURES_403)
        self.assertEqual(r.returncode, 1)
        self.assertIn("quota is 0", r.stderr)
        self.assertIn("TAYLOR-TODO", r.stderr)
        self.assertIn("Nothing was changed", r.stderr)
        self.setUp()
        r = self.run_gbp("doctor")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("read ok: Fong Asian Dining", r.stdout)
        self.assertIn("menus: not here", r.stdout)


if __name__ == "__main__":
    unittest.main()
