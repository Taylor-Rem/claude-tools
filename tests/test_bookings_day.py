"""`db bookings ls` and `db bookings open` (ROADMAP B120): the owner's day by
text and times opened in bulk, on the fake wrangler (real SQL on the real
bookings migration, in SQLite). BOOKINGS_NOW pins the site's clock. No network.

    python3 -m unittest tests.test_bookings_day -q   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402

import datetime
import importlib.machinery
import importlib.util
import json
import unittest

import test_db  # noqa: E402

NOW = "2026-10-06T21:30"          # a Tuesday evening, the site's clock


def load_db():
    loader = importlib.machinery.SourceFileLoader("db_tool_b120", str(test_db.DB))
    spec = importlib.util.spec_from_loader("db_tool_b120", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class ParseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = load_db()

    def test_days_as_the_owner_says_them(self):
        tue = datetime.date(2026, 10, 6)
        p = self.db.parse_day
        self.assertEqual(p("today", tue), tue)
        self.assertEqual(p("tomorrow", tue), datetime.date(2026, 10, 7))
        self.assertEqual(p("tuesday", tue), tue)                      # today is one
        self.assertEqual(p("my tuesday", tue), tue)
        self.assertEqual(p("next tuesday", tue), datetime.date(2026, 10, 13))
        self.assertEqual(p("thurs", tue), datetime.date(2026, 10, 8))
        self.assertEqual(p("monday", tue), datetime.date(2026, 10, 12))
        self.assertEqual(p("10/14", tue), datetime.date(2026, 10, 14))
        self.assertEqual(p("Oct 14", tue), datetime.date(2026, 10, 14))
        self.assertEqual(p("2026-11-02", tue), datetime.date(2026, 11, 2))
        self.assertEqual(p("jan 5", tue), datetime.date(2027, 1, 5))   # past this year: next year's
        self.assertIsNone(p("someday", tue))
        self.assertIsNone(p("2026-02-30", tue))

    def test_clock_times(self):
        c = self.db.parse_clock
        self.assertEqual(c("9"), (9, 0))
        self.assertEqual(c("9am"), (9, 0))
        self.assertEqual(c("3pm"), (15, 0))
        self.assertEqual(c("3"), (15, 0))                             # a bare 1-6 is the afternoon
        self.assertEqual(c("12:30pm"), (12, 30))
        self.assertEqual(c("13:30"), (13, 30))
        self.assertEqual(c("noon"), (12, 0))
        self.assertIsNone(c("25"))
        self.assertEqual(self.db.clock_text("13:05"), "1:05pm")
        self.assertEqual(self.db.clock_text("00:00"), "12:00am")


class DbBookingsDayTest(unittest.TestCase):
    setUp_ = test_db.DbTest.setUp
    tearDown = test_db.DbTest.tearDown
    row = test_db.DbTest.row
    register = test_db.DbTest.register
    make_repo = test_db.DbTest.make_repo
    db = test_db.DbTest.db

    def setUp(self):
        self.setUp_()
        self.env["BOOKINGS_NOW"] = NOW
        self.assertEqual(self.db("add", "bookings").returncode, 0)
        r = self.db("migrate")
        self.assertEqual(r.returncode, 0, r.stderr)

    def sql(self, s):
        r = self.db("exec", s)
        self.assertEqual(r.returncode, 0, r.stderr)

    def plant(self):
        self.sql("INSERT INTO booking_slots (id, starts_at, minutes, capacity) VALUES "
                 "(1, '2026-10-07T09:00', 60, 1), (2, '2026-10-07T13:00', 60, 1), (3, '2026-10-07T15:00', 60, 2), "
                 "(4, '2026-10-13T09:00', 60, 1), (5, '2026-10-06T08:00', 60, 1)")
        self.sql("INSERT INTO bookings (id, slot_id, starts_at, name, email, phone, status) VALUES "
                 "(1, 1, '2026-10-07T09:00', 'Dana Smith', 'dana@x.test', '801-555-0134', 'confirmed'), "
                 "(2, 2, '2026-10-07T13:00', 'Robin Lee', NULL, NULL, 'requested'), "
                 "(3, 3, '2026-10-07T15:00', 'Old Gone', 'g@x.test', NULL, 'cancelled'), "
                 "(4, 4, '2026-10-13T09:00', 'Pat Smithers', 'p@x.test', NULL, 'confirmed')")

    def test_tomorrow_is_one_message_with_the_open_times(self):
        self.plant()
        r = self.db("bookings", "ls", "tomorrow")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("Tomorrow, Wednesday, October 7", out)
        self.assertIn("9:00am  Dana Smith · confirmed · #1 · 801-555-0134", out)
        self.assertIn("1:00pm  Robin Lee · requested, not confirmed yet · #2", out)
        self.assertNotIn("Old Gone", out)                                 # cancelled: only with --all
        self.assertIn("open: 3:00pm (2 places)", out)                     # the cancelled one freed its place
        self.assertIn("Old Gone", self.db("bookings", "ls", "tomorrow", "--all").stdout)

    def test_json_for_the_relay_and_a_quiet_day_says_so(self):
        self.plant()
        data = json.loads(self.db("bookings", "ls", "tomorrow", "--json").stdout)
        self.assertEqual([b["id"] for b in data["bookings"]], [1, 2])
        self.assertEqual(data["bookings"][0]["email"], "dana@x.test")
        self.assertEqual(data["from"], "2026-10-07")
        self.assertEqual(data["tz"], "America/Denver")
        out = self.db("bookings", "ls", "friday").stdout
        self.assertIn("Friday, October 9: nothing booked, no open times", out)
        today = json.loads(self.db("bookings", "ls", "today", "--json").stdout)
        self.assertEqual(today["open"], [])                               # 08:00 today is past

    def test_find_by_name_for_confirm_smith(self):
        self.plant()
        out = self.db("bookings", "ls", "--name", "smith").stdout
        self.assertIn("#1", out)
        self.assertIn("#4", out)
        self.assertIn("Pat Smithers", out)
        self.assertIn("no booking with 'nobody'", self.db("bookings", "ls", "--name", "nobody").stdout)

    def test_open_tuesdays_9_to_12_through_november(self):
        self.plant()
        self.sql("UPDATE booking_slots SET status = 'closed' WHERE id = 4")      # Oct 13 9am closed
        self.sql("INSERT INTO booking_slots (starts_at) VALUES ('2026-10-20T10:00')")  # already open
        r = self.db("bookings", "open", "--on", "tuesdays", "--from", "9", "--to", "12", "--until", "november",
                    "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        res = json.loads(r.stdout)
        self.assertEqual(res["first"], "2026-10-06")
        self.assertEqual(res["last"], "2026-11-30")
        self.assertEqual(len(res["times"]), 21)                           # Oct 13 .. Nov 24, today's are past
        self.assertEqual(res["reopened"], ["2026-10-13T09:00"])
        self.assertEqual(res["already_open"], ["2026-10-20T10:00"])
        self.assertEqual(len(res["added"]), 19)
        rows = json.loads(self.db("query", "SELECT starts_at, status FROM booking_slots WHERE starts_at >= '2026-10-08' "
                                           "AND status = 'open' ORDER BY starts_at", "--json").stdout)
        self.assertEqual(len(rows), 21)
        self.assertEqual(len({r["starts_at"] for r in rows}), 21)         # nothing twice
        again = json.loads(self.db("bookings", "open", "--on", "tue", "--from", "9", "--to", "12", "--until",
                                   "2026-11-30", "--json").stdout)
        self.assertEqual(again["added"], [])                              # a second run changes nothing

    def test_open_says_it_back_and_refuses_what_it_cannot_read(self):
        r = self.db("bookings", "open", "--on", "tue,thu", "--from", "9am", "--to", "11am", "--weeks", "2", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would open 6 time(s): 9:00am, 10:00am on 3 day(s)", r.stdout)
        self.assertEqual(json.loads(self.db("query", "SELECT COUNT(*) AS n FROM booking_slots", "--json").stdout)[0]["n"], 0)
        r = self.db("bookings", "open", "--on", "tue", "--from", "9", "--to", "8am", "--weeks", "1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("before --from", r.stderr)
        r = self.db("bookings", "open", "--on", "someday", "--from", "9", "--to", "12", "--weeks", "1")
        self.assertIn("isn't a weekday", r.stderr)
        r = self.db("bookings", "open", "--on", "daily", "--from", "0", "--to", "23:59", "--every", "5", "--minutes", "5",
                    "--weeks", "1")
        self.assertIn("at most", r.stderr)


if __name__ == "__main__":
    unittest.main()
