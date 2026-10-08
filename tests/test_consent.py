"""The consent machine (ROADMAP B139; lib/consent.py), against a throwaway store.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

The acceptance line, in order: a keyword text moves INVITED -> KEYWORD_RECEIVED
and allows exactly one reply; a second unprompted text is refused until
CONFIRMED; a YES confirms and the text past the allowance is refused with the
reason; a text at 9:30pm is refused; a STOP from ACTIVE revokes every program
at once and the next outbound is refused. The business here is fictional, as
the engine must be (plan 55 § 5.12).
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads (tests/_offline.py)
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent / "lib"))

import os  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

import consent as C  # noqa: E402

TZ = ZoneInfo("America/Denver")
OURS = "+15555550100"
THEM = "+15555550123"
TERMS = "https://example.test/sms-terms"
CTA = ("Text TIDY to (555) 555-0100 for your free site. Acme Tidy Texts: up to 3 msgs. "
       f"Msg & data rates may apply. Reply STOP to end, HELP for help. Terms: {TERMS}")


def at(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


TUE_NOON = at(2026, 10, 13, 12)          # a Tuesday, not a holiday


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.m = C.Machine(Path(self.tmp.name) / "consent.db")
        self.m.register_program("acme", "card", name="Acme Tidy Texts", business="Acme Tidy",
                                subject="your free site", max_messages=3, time_box_days=30,
                                terms_url=TERMS, contact="hello@example.test", tz="America/Denver",
                                holidays=["utah"])
        self.m.invite("acme", "card", card_id="c-001", version="1", cta_text=CTA, keyword="tidy",
                      our_number=OURS, recipient="place:abc", promise="Your site: https://example.test/p/abc",
                      now=TUE_NOON - timedelta(days=5))

    def tearDown(self):
        self.tmp.cleanup()

    def send(self, now, kind=None, text="hi"):
        v = self.m.may_send(THEM, kind=kind, now=now)
        if v.ok:
            self.m.record_sent(THEM, v, text, now=now)
        else:
            self.m.refused(THEM, v, text, now=now)
        return v

    def to_confirmed(self, now=TUE_NOON):
        d = self.m.inbound(THEM, "TIDY", to=OURS, now=now)
        self.send(now, text=d.reply)
        d = self.m.inbound(THEM, "Yes", to=OURS, now=now + timedelta(minutes=2))
        self.send(now + timedelta(minutes=2), text=d.reply)
        return d


class Acceptance(Base):
    def test_keyword_allows_exactly_one_reply(self):
        self.assertEqual(self.m.state(THEM), {})
        d = self.m.inbound(THEM, "tidy", to=OURS, now=TUE_NOON, message_id="SM1")
        self.assertTrue(d.known and d.handled)
        self.assertEqual(d.line, C.MAY_REPLY)
        self.assertEqual(self.m.state(THEM), {"acme/card": C.KEYWORD_RECEIVED})
        # the compliance message carries the carriers' lines and the card's promise
        for part in ("Acme Tidy Texts", "up to 3", "Msg & data rates may apply", "STOP", "HELP", TERMS,
                     "https://example.test/p/abc", "YES"):
            self.assertIn(part, d.reply)
        row = [r for r in self.m.history(THEM) if r["event"] == "keyword"][0]
        self.assertEqual((row["from_state"], row["card_id"], row["keyword"], row["our_number"]),
                         (C.INVITED, "c-001", "TIDY", OURS))
        self.assertEqual(row["cta_hash"], C.cta_hash(CTA))
        self.assertEqual(row["inbound_text"], "tidy")
        v = self.send(TUE_NOON + timedelta(seconds=5), text=d.reply)
        self.assertTrue(v.ok)
        self.assertEqual(v.kind, "reply")
        self.assertEqual(self.m.state(THEM), {"acme/card": C.DISCLOSED})
        # the second text, unprompted, is refused, and so is a "reply" with nothing to answer
        v2 = self.send(TUE_NOON + timedelta(minutes=1))
        self.assertFalse(v2.ok)
        self.assertEqual(v2.kind, "scoped")
        self.assertIn("haven't said YES", v2.reason)
        self.assertEqual(v2.line, C.MAY_NOT)
        self.assertFalse(self.m.may_send(THEM, kind="reply", now=TUE_NOON + timedelta(minutes=1)).ok)

    def test_unprompted_refused_until_confirmed_then_allowance(self):
        # a question before YES earns one reply, never an unprompted text
        d = self.m.inbound(THEM, "TIDY", to=OURS, now=TUE_NOON)
        self.send(TUE_NOON, text=d.reply)
        q = self.m.inbound(THEM, "is this a real person?", to=OURS, now=TUE_NOON + timedelta(minutes=1))
        self.assertFalse(q.handled)
        self.assertEqual(q.line, C.MAY_REPLY)
        self.assertTrue(self.send(TUE_NOON + timedelta(minutes=2), text="Yes, Acme's owner reads these.").ok)
        self.assertFalse(self.send(TUE_NOON + timedelta(minutes=3)).ok)
        self.assertEqual(self.m.state(THEM), {"acme/card": C.DISCLOSED})
        # YES confirms; logged verbatim
        y = self.m.inbound(THEM, "yes please!", to=OURS, now=TUE_NOON + timedelta(minutes=4))
        self.assertEqual(y.event, "confirmed")
        self.assertEqual(self.m.state(THEM), {"acme/card": C.CONFIRMED})
        self.assertEqual([r for r in self.m.history(THEM) if r["event"] == "confirmed"][0]["inbound_text"],
                         "yes please!")
        self.assertTrue(self.send(TUE_NOON + timedelta(minutes=4), text=y.reply).ok)   # the thanks: a reply
        # three scoped texts on three days, then the fourth is refused with the reason
        day = TUE_NOON + timedelta(days=1)
        v = self.send(day)
        self.assertTrue(v.ok and v.kind == "scoped")
        self.assertEqual(self.m.state(THEM), {"acme/card": C.ACTIVE})
        self.assertTrue(self.send(day + timedelta(days=1)).ok)
        self.assertTrue(self.send(day + timedelta(days=2)).ok)
        self.assertEqual(self.m.state(THEM), {"acme/card": C.EXPIRED})
        v4 = self.send(day + timedelta(days=3))
        self.assertFalse(v4.ok)
        self.assertIn("over", v4.reason)
        # a reply to a text of theirs is still allowed after the allowance is spent
        self.m.inbound(THEM, "one more question", to=OURS, now=day + timedelta(days=3, hours=1))
        self.assertTrue(self.m.may_send(THEM, now=day + timedelta(days=3, hours=1)).ok)

    def test_allowance_reason_when_checked_at_the_limit(self):
        self.to_confirmed()
        for i in range(3):
            self.assertTrue(self.send(TUE_NOON + timedelta(days=1 + i)).ok)
        v = self.m.may_send(THEM, kind="scoped", venture="acme", program="card", now=TUE_NOON + timedelta(days=5))
        self.assertFalse(v.ok)

    def test_nine_thirty_pm_refused(self):
        self.to_confirmed()
        v = self.send(at(2026, 10, 14, 21, 30))
        self.assertFalse(v.ok)
        self.assertIn("9:30pm", v.reason)
        self.assertFalse(self.send(at(2026, 10, 14, 7, 59)).ok)
        self.assertTrue(self.send(at(2026, 10, 14, 8, 0)).ok)
        self.assertTrue(self.send(at(2026, 10, 14, 20, 59)).ok)

    def test_sunday_and_holiday_refused(self):
        self.to_confirmed()
        sun = self.send(at(2026, 10, 18, 12))                 # a Sunday
        self.assertFalse(sun.ok)
        self.assertIn("Sunday", sun.reason)
        thanks = self.send(at(2026, 11, 11, 12))               # Veterans Day 2026, a Wednesday
        self.assertFalse(thanks.ok)
        self.assertIn("holiday", thanks.reason)

    def test_time_box(self):
        self.to_confirmed()
        v = self.send(TUE_NOON + timedelta(days=31))
        self.assertFalse(v.ok)
        self.assertIn("30 days", v.reason)
        self.assertEqual(self.m.state(THEM), {"acme/card": C.EXPIRED})

    def test_stop_from_active_revokes_every_program(self):
        self.m.register_program("acme", "form", kind="form", name="Acme Tidy Texts", business="Acme Tidy",
                                subject="your request", max_messages=2, time_box_days=7, terms_url=TERMS)
        self.to_confirmed()
        self.assertTrue(self.send(TUE_NOON + timedelta(days=1)).ok)
        self.m.opt_in(THEM, "acme", "form", source="form", evidence="I agree to texts.",
                      now=TUE_NOON + timedelta(days=1, hours=1))
        self.assertEqual(self.m.state(THEM)["acme/card"], C.ACTIVE)
        d = self.m.inbound(THEM, "please stop texting me", to=OURS, now=TUE_NOON + timedelta(days=1, hours=2))
        self.assertTrue(d.handled)
        self.assertEqual(d.reply, "")
        self.assertEqual(d.line, C.MAY_NOT)
        st = self.m.state(THEM)
        self.assertEqual(st, {"acme/card": C.REVOKED, "acme/form": C.REVOKED, "*": C.REVOKED})
        for kind in (None, "reply", "scoped"):
            v = self.m.may_send(THEM, kind=kind, now=TUE_NOON + timedelta(days=1, hours=2, seconds=1))
            self.assertFalse(v.ok)
            self.assertIn("asked us to stop", v.reason)
        # anything they send now gets nothing back; their own START lifts it
        for _ in range(2):      # a text from a revoked number, and its logged refusal, change nothing
            self.assertEqual(self.m.inbound(THEM, "what?", to=OURS, now=TUE_NOON + timedelta(days=2)).reply, "")
            v = self.m.may_send(THEM, now=TUE_NOON + timedelta(days=2))
            self.assertFalse(v.ok)
            self.m.refused(THEM, v, "a reply", now=TUE_NOON + timedelta(days=2))
        self.assertEqual(self.m.state(THEM)["*"], C.REVOKED)
        self.m.inbound(THEM, "START", to=OURS, now=TUE_NOON + timedelta(days=3))
        self.assertNotIn("*", self.m.state(THEM))
        self.assertFalse(self.m.may_send(THEM, kind="scoped", now=TUE_NOON + timedelta(days=3)).ok)


class Edges(Base):
    def test_unknown_number_untouched(self):
        d = self.m.inbound("+15555550199", "hello there", to=OURS, now=TUE_NOON)
        self.assertFalse(d.known)
        v = self.m.may_send("+15555550199", now=TUE_NOON)
        self.assertTrue(v.ok)
        self.assertFalse(v.governed)
        self.assertFalse(self.m.knows("+15555550199"))
        # a STOP from a stranger is the carrier's to handle; nothing is recorded here
        self.assertFalse(self.m.inbound("+15555550199", "STOP", now=TUE_NOON).known)
        self.assertEqual(self.m.history("+15555550199"), [])

    def test_keyword_to_another_number_is_not_ours(self):
        self.assertFalse(self.m.inbound(THEM, "TIDY", to="+15555550111", now=TUE_NOON).known)

    def test_help_changes_nothing(self):
        d = self.m.inbound(THEM, "TIDY", to=OURS, now=TUE_NOON)
        self.send(TUE_NOON, text=d.reply)
        h = self.m.inbound(THEM, "HELP", to=OURS, now=TUE_NOON + timedelta(minutes=1))
        self.assertTrue(h.handled)
        for part in ("Acme Tidy Texts", "hello@example.test", "STOP", "Msg & data rates may apply"):
            self.assertIn(part, h.reply)
        self.assertEqual(self.m.state(THEM), {"acme/card": C.DISCLOSED})
        self.assertTrue(self.send(TUE_NOON + timedelta(minutes=1), text=h.reply).ok)
        self.assertEqual(self.m.state(THEM), {"acme/card": C.DISCLOSED})

    def test_card_without_carrier_lines_refused(self):
        with self.assertRaises(C.ConsentError) as cm:
            self.m.invite("acme", "card", card_id="c-002", version="1", cta_text="Text TIDY to 555-0100!",
                          keyword="TIDY", our_number=OURS)
        self.assertIn("Msg & data rates may apply", str(cm.exception))
        with self.assertRaises(C.ConsentError):
            self.m.invite("acme", "card", card_id="c-001", version="1", cta_text=CTA, keyword="TIDY",
                          our_number=OURS)     # the same card twice

    def test_reply_window(self):
        d = self.m.inbound(THEM, "TIDY", to=OURS, now=TUE_NOON)
        self.assertFalse(self.m.may_send(THEM, now=TUE_NOON + timedelta(hours=25)).ok)
        self.assertTrue(d.reply)

    def test_utah_holidays(self):
        h = C.utah_holidays(2026)
        for d in ("2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19", "2026-07-03",
                  "2026-07-04", "2026-07-24", "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26",
                  "2026-12-25"):
            self.assertIn(C.date.fromisoformat(d), h, d)

    def test_cli_check_and_show(self):
        env = dict(os.environ, CONSENT_DB=str(self.m.path))
        self.m.inbound(THEM, "TIDY", to=OURS, now=datetime.now(TZ))
        tool = str(Path(__file__).resolve().parent.parent / "bin/consent")
        out = subprocess.run([tool, "check", THEM], env=env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn(C.MAY_REPLY, out.stdout)
        out = subprocess.run([tool, "check", THEM, "--kind", "scoped"], env=env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 3)
        self.assertIn(C.MAY_NOT, out.stdout)
        out = subprocess.run([tool, "show", THEM], env=env, capture_output=True, text=True)
        self.assertIn("KEYWORD_RECEIVED", out.stdout)
        out = subprocess.run([tool, "doctor"], env=env, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)


class Portable(unittest.TestCase):
    def test_no_business_literal_in_the_engine(self):
        src = (Path(__file__).resolve().parent.parent / "lib/consent.py").read_text().lower()
        for word in ("patchlamp", "remund", "provo", "american fork", "kmcmh"):
            self.assertNotIn(word, src)


if __name__ == "__main__":
    unittest.main()
