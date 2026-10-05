"""B116: where each touch went (`--channel`), so the second touch knows where the first did.

Runs on the made-up services census (fixtures/leads-services) and a pipeline in a temp dir, through
test_leads_today's Base: no Google call, no real lead.

    python3 -m unittest test_leads_channel   (from claude-tools/tests)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402

import datetime as dt  # noqa: E402
import json  # noqa: E402
import unittest  # noqa: E402

from test_leads_today import ANCHOR, Base  # noqa: E402


class ChannelTest(Base):
    def test_messaged_without_a_channel_is_refused_and_says_what_to_add(self):
        r = self.run_leads("log", "Mike's Pool Care", "messaged", "the Facebook link")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Add --channel facebook|instagram|email|text|call|form", r.stderr)
        self.assertIn("nothing was written", r.stderr)
        self.assertEqual(self.events(), [])
        r = self.run_leads("log", "Mike's Pool Care", "messaged", "x", "--channel", "carrier-pigeon")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--channel is one of", r.stderr)
        self.assertEqual(self.events(), [])

    def test_sent_needs_the_channel_too(self):
        self.run_leads("kit", "--remote", "--census-only", "--segment", "services")
        r = self.run_leads("sent", "1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("leads sent 1 --channel instagram", r.stderr)
        r = self.run_leads("sent", "1", "--channel", "facebook")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([e["channel"] for e in self.events()], ["facebook"])

    def test_show_and_brief_print_each_touchs_channel_and_an_old_line_says_not_recorded(self):
        self.messaged("Mike's Pool Care", ANCHOR - dt.timedelta(days=6), "FX_S01", source="dm")   # an old line
        r = self.run_leads("log", "Mike's Pool Care", "messaged", "the other channel", "--channel", "email")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("messaged by email", r.stdout)
        self.run_leads("log", "Mike's Pool Care", "talked", "call him Friday", "--channel", "call")
        self.run_leads("log", "Mike's Pool Care", "talked", "at the counter")            # talked: optional
        show = self.run_leads("show", "Mike's Pool Care").stdout
        self.assertIn("messaged   channel not recorded · the remote kit", show)
        self.assertIn("messaged   by email · the other channel", show)
        self.assertIn("talked     by call · call him Friday", show)
        self.assertIn("talked     channel not recorded · at the counter", show)
        brief = self.run_leads("brief", "Mike's Pool Care", now=ANCHOR).stdout
        self.assertIn("channel not recorded · the remote kit", brief)
        self.assertIn("by email · the other channel", brief)
        self.assertNotIn("instagram", brief.lower().split("strength")[0].replace("instagram.com", ""))  # no guess

    def test_week_by_channel_says_where_the_messages_went(self):
        self.messaged("Mike's Pool Care", ANCHOR, "FX_S01", source="dm")
        self.messaged("Glacier Snow Removal", ANCHOR, "FX_S08", source="dm", channel="instagram")
        self.messaged("Timp Pressure Washing", ANCHOR, None, source="dm", channel="instagram")
        r = self.run_leads("week", "--by", "channel", now=ANCHOR)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Where they went (B116): instagram 2 · channel not recorded 1", r.stdout)
        j = json.loads(self.run_leads("week", "--by", "channel", "--json", now=ANCHOR).stdout)
        self.assertEqual(j["went_by"]["instagram"]["messaged"], 2)

    def test_the_day_three_touch_is_the_other_channel_from_where_the_first_went(self):
        # source says dm (how it came), but the first message actually went by email: day 3 is the DM
        self.messaged("Mike's Pool Care", ANCHOR - dt.timedelta(days=3), "FX_S01", source="dm", channel="email",
                      email="mike@example.test", reach="facebook.com/mikespoolcare · mike@example.test")
        r = self.run_leads("cadence", now=ANCHOR)
        self.assertIn("Mike's Pool Care — day 3 by dm", r.stdout)
        self.assertIn("(first went by email)", self.run_leads("due", now=ANCHOR).stdout)

    def test_backfill_sets_the_channel_on_one_old_line_once(self):
        day = ANCHOR - dt.timedelta(days=6)
        self.messaged("Mike's Pool Care", day, "FX_S01", source="dm")
        r = self.run_leads("channel", "Mike's Pool Care", "facebook", "--date", day.isoformat(), "--by", "cowork",
                           "--dry-run")
        self.assertIn("would record by facebook", r.stdout)
        self.assertNotIn("channel", self.events()[0])
        r = self.run_leads("channel", "Mike's Pool Care", "facebook", "--date", day.isoformat(), "--by", "cowork")
        self.assertEqual(r.returncode, 0, r.stderr)
        e = self.events()[0]
        self.assertEqual(e["channel"], "facebook")
        self.assertTrue(e["channel_by"].startswith("backfill cowork "))
        self.assertEqual(e["note"], "the remote kit")                   # nothing else changed
        self.assertTrue(self.pipeline.with_name("pipeline.jsonl.bak").exists())
        r = self.run_leads("channel", "Mike's Pool Care", "instagram", "--date", day.isoformat(), "--by", "cowork")
        self.assertIn("already recorded (by facebook); nothing changed", r.stdout)
        self.assertEqual(self.events()[0]["channel"], "facebook")
        r = self.run_leads("channel", "Mike's Pool Care", "email", "--date", "2026-01-01", "--by", "cowork")
        self.assertNotEqual(r.returncode, 0)


class OwnerRepliesTest(Base):
    """B116 (c): Places carries no owner replies, so the line is a person's reading or nothing."""

    def test_brief_prints_nothing_without_a_reading_and_the_reading_with_one(self):
        self.messaged("Mike's Pool Care", ANCHOR - dt.timedelta(days=4), "FX_S01", source="dm", channel="facebook")
        brief = self.run_leads("brief", "Mike's Pool Care", now=ANCHOR).stdout
        self.assertNotIn("Owner replies", brief)
        r = self.run_leads("replies", "Mike's Pool Care", "7/10", "--newest", "2026-09-20", "--by", "cowork",
                           "--evidence", "https://maps.google.com/?cid=1", now=ANCHOR)
        self.assertEqual(r.returncode, 0, r.stderr)
        brief = self.run_leads("brief", "Mike's Pool Care", now=ANCHOR).stdout
        self.assertIn("  Owner replies: 7 of the last 10 Google reviews, newest reply 2026-09-20 "
                      "(read by cowork 28 Sep: https://maps.google.com/?cid=1)", brief)
        self.run_leads("replies", "Mike's Pool Care", "2/4", "--by", "taylor",
                       "--evidence", "https://maps.google.com/?cid=1", now=ANCHOR)
        brief = self.run_leads("brief", "Mike's Pool Care", now=ANCHOR + dt.timedelta(days=61)).stdout
        self.assertIn("Owner replies: 2 of 4 Google reviews, newest reply's date not recorded (read by taylor", brief)
        self.assertIn("over two months old, look again", brief)

    def test_a_reading_in_googles_default_order_says_so(self):
        self.messaged("Mike's Pool Care", ANCHOR - dt.timedelta(days=4), "FX_S01", source="dm", channel="facebook")
        self.run_leads("replies", "Mike's Pool Care", "8/10", "--sort", "relevant", "--by", "cowork",
                       "--evidence", "https://maps.google.com/?cid=1", now=ANCHOR)
        brief = self.run_leads("brief", "Mike's Pool Care", now=ANCHOR).stdout
        self.assertIn("Owner replies: 8 of the first 10 Google reviews in Google's default order", brief)

    def test_a_reading_needs_a_count_a_reader_and_the_listing(self):
        for args in (("11/10",), ("7/10", "--by", "cowork", "--evidence", "the listing"),
                     ("7/10", "--evidence", "https://maps.google.com/?cid=1"), ("seven",)):
            r = self.run_leads("replies", "Mike's Pool Care", *args, "--by", "x", "--evidence", "https://g.co/x"
                               ) if args in (("11/10",), ("seven",)) else self.run_leads("replies", "Mike's Pool Care", *args)
            self.assertNotEqual(r.returncode, 0, args)


if __name__ == "__main__":
    unittest.main()
