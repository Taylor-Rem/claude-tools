"""The outreach deck and the read receipt (ROADMAP B152, plan ~/projects/plans/59-outreach-deck.md).

Runs on the made-up census and a hand-written pipeline (test_leads_today.Base): no Google call, no real lead.

    python3 -m unittest tests.test_leads_deck   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent / "lib"))

import datetime as dt  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import unittest  # noqa: E402

import deck as DECK  # noqa: E402
from test_leads_today import Base  # noqa: E402

DAY = dt.date(2026, 10, 12)
NASTY = "Hi again. </script><script>alert('x')</script> <b>bold</b> & \"quotes\" it's fine."

SIX = """# Monday

## The six (picked blind)
Message one is the picked text.

**D1 · Arvo Pest Control** · Instagram @arvopest · preview https://previews.example.test/arvo/

Hi, I'm Taylor. I looked up Arvo Pest Control on Google. So I built you one. Want to see it?

_Receipt: opus · facts: every sentence supported · the judge: fine._

**D2 · Phone Only Co** · phone only today (801) 555-0101 · preview https://previews.example.test/phone/

Hi, is this Phone Only Co? Can I text you the link?

_Receipt: opus · the judge: spoken._

**Message two, after a yes (all six):**

It's a price a month. Want this to be your live site?

## Cowork
nothing
"""


def data_of(html_):
    m = re.search(r'<script type="application/json" id="deck-data">(.*?)</script>', html_, re.S)
    return json.loads(m.group(1))


class RendererTest(unittest.TestCase):
    def test_every_string_reaches_the_page_as_data_never_markup(self):
        data = {"title": "A <Deck> & co", "storage_key": "k", "headline": "h", "sections": [
            {"id": "f", "title": "t", "cards": [{"key": "f-x", "name": "Mike's <Pool>", "message": NASTY, "log": "log X"}]}]}
        out = DECK.render(data)
        self.assertTrue(out.startswith("<title>A &lt;Deck&gt; &amp; co</title>"))
        self.assertNotIn("<script>alert", out)
        self.assertNotIn("<b>bold", out)
        self.assertNotIn("<html", out.lower())
        self.assertNotIn("<!doctype", out.lower())
        self.assertIn(":root[data-theme=\"dark\"]", out)
        self.assertIn("prefers-color-scheme: dark", out)
        self.assertEqual(data_of(out)["sections"][0]["cards"][0]["message"], NASTY)   # read back exactly

    def test_drafts_parse_and_refuse_a_typo(self):
        f, body = DECK.parse_draft("---\nname: Halo\nchannel: Facebook\nsend: 2026-10-13\n---\nLine one.\n\n\n\nLine two.\n")
        self.assertEqual((f["channel"], f["send"], body), ("facebook", "2026-10-13", "Line one.\n\nLine two."))
        with self.assertRaises(DECK.DraftError):
            DECK.parse_draft("---\nchanel: facebook\n---\nx")

    def test_the_day_files_six(self):
        six = DECK.parse_six(SIX)
        self.assertEqual([p["name"] for p in six["picks"]], ["Arvo Pest Control", "Phone Only Co"])
        self.assertEqual(six["picks"][0]["instagram"], "arvopest")
        self.assertTrue(six["picks"][0]["message"].endswith("Want to see it?"))
        self.assertTrue(six["picks"][0]["receipt"].startswith("opus"))
        self.assertEqual(six["picks"][1]["phone"], "(801) 555-0101")
        self.assertEqual(six["message_two"], "It's a price a month. Want this to be your live site?")

    def test_messenger_links(self):
        self.assertEqual(DECK.fb_target("facebook.com/p/Lakeside-Roofing-Utah-61568277063379"), "61568277063379")
        self.assertEqual(DECK.fb_target("https://www.facebook.com/legendaryelectric"), "legendaryelectric")
        self.assertEqual(DECK.fb_target("facebook.com/profile.php?id=123456789"), "123456789")
        self.assertEqual(DECK.tel_href("(801) 842-5672"), "tel:+18018425672")


class DeckTest(Base):
    def setUp(self):
        super().setUp()
        self.drafts = self.t / "drafts"
        self.drafts.mkdir()
        self.days = self.t / "days"
        self.days.mkdir()
        self.env.update({"LEADS_DRAFTS": str(self.drafts), "LEADS_DAYS": str(self.days)})
        day0 = DAY - dt.timedelta(days=5)
        self.messaged("Silent Ig", day0, city="Lehi", channel="instagram", reach="Instagram @silentig",
                      next=DAY.isoformat())
        self.messaged("Draft Fb", day0, city="Orem", channel="facebook", reach="facebook.com/p/Draft-Fb-1234567890",
                      next=DAY.isoformat())
        self.messaged("Warm Venue", day0, city="Orem", channel="facebook", reach="facebook.com/warmvenue",
                      outcome="interested", stage="interested", next=(DAY + dt.timedelta(days=1)).isoformat())
        (self.drafts / "draft-fb-orem.md").write_text(
            f"---\nchannel: facebook\nwhy: Steel: short.\nlog: log Draft Fb messaged \"x\" --channel facebook\n"
            f"written: {(DAY - dt.timedelta(days=1)).isoformat()}T09:00\n---\n{NASTY} https://previews.example.test/d/\n")
        (self.drafts / "warm-venue-orem.md").write_text(
            "---\nname: Warm Venue\nsend: 2026-10-13\nwhy: Steel: a time.\n"
            f"written: {(DAY - dt.timedelta(days=1)).isoformat()}T09:00\n---\nHi again, it's Taylor. Tuesday or Thursday?\n")
        (self.days / f"{DAY.isoformat()}.md").write_text(SIX)

    def deck(self, *extra):
        r = self.run_leads("deck", "--date", DAY.isoformat(), "--json", *extra, now=DAY)
        self.assertEqual(r.returncode, 0, r.stderr)
        d = json.loads(r.stdout)
        return d, {c["name"]: (s["id"], c) for s in d["sections"] for c in s["cards"]}

    def test_warm_first_checked_text_only_and_the_ask(self):
        d, cards = self.deck()
        self.assertEqual([s["id"] for s in d["sections"]][0], "warm")
        sec, warm = cards["Warm Venue"]
        self.assertEqual(sec, "warm")
        self.assertEqual(warm["when"], "Tuesday 13 Oct")
        self.assertEqual(warm["open"]["href"], "https://m.me/warmvenue")
        sec, fb = cards["Draft Fb"]
        self.assertEqual(sec, "follow")
        self.assertTrue(fb["message"].startswith(NASTY))            # carried as written, nothing re-drafted
        self.assertEqual(fb["open"]["href"], "https://m.me/1234567890")
        self.assertEqual(fb["log"], 'log Draft Fb messaged "x" --channel facebook')
        sec, ig = cards["Silent Ig"]
        self.assertEqual(sec, "asks")
        self.assertIsNone(ig["message"])                            # never an unchecked draft
        self.assertEqual(ig["ask"], 'No draft yet: say "Steel, Silent Ig".')
        self.assertEqual(ig["channel"], "instagram")
        self.assertIn("isn't tappable", ig["hint"])
        sec, arvo = cards["Arvo Pest Control"]                      # the kit, from the day file
        self.assertEqual(sec, "kit")
        self.assertTrue(arvo["why"].startswith("Receipt: opus"))
        self.assertEqual(arvo["open"]["href"], "https://ig.me/m/arvopest")
        self.assertFalse(arvo["warnings"])                          # message one has no link
        self.assertTrue(cards["Phone Only Co"][1]["script"])
        self.assertEqual(d["message_two"]["text"], "It's a price a month. Want this to be your live site?")
        self.assertNotIn("Silent Ig", json.dumps(d["footer"]))

    def test_the_page_file_escapes_and_the_kit_can_be_left_off(self):
        out = self.t / "deck.html"
        r = self.run_leads("deck", "--date", DAY.isoformat(), "--out", str(out), now=DAY)
        self.assertEqual(r.returncode, 0, r.stderr)
        html_ = out.read_text()
        self.assertNotIn("<script>alert", html_)
        self.assertNotIn("<b>bold", html_)
        self.assertIn("Draft Fb", html_)
        _, cards = self.deck("--no-kit")
        self.assertNotIn("Arvo Pest Control", cards)

    def test_a_hold_goes_to_the_footer_and_a_spent_draft_drops_off(self):
        (self.drafts / "silent-ig-lehi.md").write_text("---\nhold: Tuesday is its date\n---\n")
        self.messaged("Draft Fb", DAY - dt.timedelta(days=1), city="Orem", channel="facebook",
                      reach="facebook.com/p/Draft-Fb-1234567890", next=DAY.isoformat(),
                      ts=(DAY - dt.timedelta(days=1)).isoformat() + "T12:00:00-06:00")
        d, cards = self.deck("--no-kit")
        self.assertNotIn("Silent Ig", cards)
        self.assertIn({"name": "Silent Ig", "text": "Tuesday is its date"}, d["footer"])
        self.assertIsNone(cards["Draft Fb"][1]["message"])          # sent after the draft: back to the ask

    def test_an_instagram_draft_with_a_link_and_a_reintroduction_is_flagged_not_edited(self):
        (self.drafts / "silent-ig-lehi.md").write_text("---\nchannel: instagram\n---\nHi, I'm Taylor. https://x.test/a\n")
        _, cards = self.deck("--no-kit")
        c = cards["Silent Ig"][1]
        self.assertEqual(c["message"], "Hi, I'm Taylor. https://x.test/a")
        self.assertEqual(len(c["warnings"]), 2, c["warnings"])

    def test_seen_sets_nothing_and_shows_everywhere(self):
        before = self.events()
        r = self.run_leads("seen", "Silent Ig", "--at", "Mon 12:50", now=DAY)
        self.assertEqual(r.returncode, 0, r.stderr)
        ev = self.events()[-1]
        self.assertEqual(len(self.events()), len(before) + 1)
        self.assertEqual((ev["outcome"], ev["channel"], ev["at"]), ("seen", "instagram", "Mon 12:50"))
        self.assertNotIn("stage", ev)
        self.assertNotIn("next", ev)
        self.assertIn("Stage and date unchanged (contacted", r.stdout)
        show = self.run_leads("show", "Silent Ig", now=DAY).stdout
        self.assertIn("seen       by instagram Mon 12:50", show)
        self.assertIn("follow up 2026-10-12", show)                 # the date is the messaged line's
        _, cards = self.deck("--no-kit")
        self.assertEqual(cards["Silent Ig"][1]["seen"], "seen Mon 12:50 on Instagram, no reply")
        week = self.run_leads("week", "--by", "channel", now=DAY).stdout
        self.assertIn("Seen, no reply (B152): instagram 1", week)
        # `log NAME seen` by text writes the same event
        self.run_leads("log", "Draft Fb", "seen", "Mon 9:00", now=DAY)
        self.assertEqual(self.events()[-1]["outcome"], "seen")
        self.assertEqual(self.events()[-1]["at"], "Mon 9:00")
        # a reply after it: no longer "no reply"
        self.messaged("Silent Ig", DAY, city="Lehi", outcome="talked", stage="contacted", channel="instagram",
                      reach="Instagram @silentig", next=DAY.isoformat(), ts=DAY.isoformat() + "T23:59:00-06:00")
        _, cards = self.deck("--no-kit")
        self.assertIsNone(cards["Silent Ig"][1]["seen"])

    def test_seen_needs_a_lead(self):
        n = len(self.events())
        r = self.run_leads("seen", "Nobody At All", now=DAY)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(len(self.events()), n)


if __name__ == "__main__":
    unittest.main()
