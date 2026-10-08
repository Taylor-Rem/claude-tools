"""The live checks by machine (ROADMAP B149, plan 57): `checks` — the parsers, the redaction, the report
lines and the checks that stay Taylor's. No network, no browser, no relay.

    python3 -m unittest tests.test_checks -q   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402

import importlib.machinery
import importlib.util
import io
import contextlib
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin" / "checks"


def load():
    loader = importlib.machinery.SourceFileLoader("checks_tool", str(BIN))
    spec = importlib.util.spec_from_loader("checks_tool", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


C = load()

ICS = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:booking-1@x\r\nDTSTART:20261009T150000Z\r\n"
       "SUMMARY:Sam Example · Weekly\r\n service\r\nSTATUS:CONFIRMED\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")


class Parsers(unittest.TestCase):
    def test_ics_unfolds_and_reads_events(self):
        ev = C.parse_ics(ICS)
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]["SUMMARY"], "Sam Example · Weeklyservice")
        self.assertEqual(ev[0]["STATUS"], "CONFIRMED")

    def test_ics_empty(self):
        self.assertEqual(C.parse_ics(""), [])

    def test_bad_stamp_comes_back_as_is(self):
        self.assertEqual(C.ics_local("soon"), "soon")

    def test_skip_lines(self):
        out = ("  1. A — skipped: no address on the listing\n"
               "  2. B — skipped: unconfirmed address x@y.com (no Utah), call-only\n")
        self.assertEqual(C.skip_lines(out), ["2. B — skipped: unconfirmed address x@y.com (no Utah), call-only"])

    def test_dollar_guard(self):
        self.assertTrue(C.DOLLAR.search("a visit is $ 45"))
        self.assertFalse(C.DOLLAR.search("Dana will reach you within one business day."))


class Record(unittest.TestCase):
    def test_redact_feed_key(self):
        url = "https://x.pages.dev/api/bookings.ics?key=" + "ab" * 20
        self.assertEqual(C.redact(url), "https://x.pages.dev/api/bookings.ics?key=<key>")

    def test_lines(self):
        ok = C.result("b119-feed", "checked", "feed 200", "health/checks/d/b119-feed.png")
        self.assertEqual(C.line(ok, "2026-10-08"),
                         "_(checked by machine 2026-10-08: feed 200 — screenshot health/checks/d/b119-feed.png)_")
        no = C.result("b37-workbench", "skipped", "needs a real phone")
        self.assertEqual(C.line(no, "2026-10-08"), "_(not checked by machine 2026-10-08: needs a real phone)_")

    def test_taylors_checks_say_why_and_touch_nothing(self):
        for name in ("b124-receipt", "b101-b102", "b37-workbench"):
            r = C.run_one(name, "2026-10-08")
            self.assertEqual(r["status"], "skipped")
            self.assertTrue(r["saw"])

    def test_a_crash_is_an_outcome(self):
        def boom(day):
            raise RuntimeError("no")
        old = C.CHECKS["b119-feed"]
        C.CHECKS["b119-feed"] = boom
        try:
            r = C.run_one("b119-feed", "2026-10-08")
        finally:
            C.CHECKS["b119-feed"] = old
        self.assertEqual(r["status"], "skipped")
        self.assertIn("crashed", r["saw"])

    def test_unknown_name_refused(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(C.main(["run", "nope"]), 2)

    def test_every_check_is_listed(self):
        self.assertEqual(set(C.ORDER), set(C.CHECKS) | set(C.NOT_BY_MACHINE))


if __name__ == "__main__":
    unittest.main()
