"""Leads by strength (ROADMAP B73, plan ~/projects/plans/33-leads-by-strength.md).

Runs on the made-up services census (fixtures/leads-services) with one more row, West Desert Roofing,
fingerprinted as a dead Hibu site the way B71 found the real one. The clock is LEADS_NOW; the messages
go out on a Monday in January 2025 so every `next` date in the pipeline is long past on the real clock
and only LEADS_NOW decides who is held.

    python3 -m unittest tests.test_leads_strength   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import datetime as dt
import json
import sqlite3
import unittest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_leads_today import PRICES_MD, Base  # noqa: E402

WEST = "FX_S20"
D0 = dt.date(2025, 1, 6)                     # a Monday


class StrengthBase(Base):
    def setUp(self):
        super().setUp()
        prices = self.t / "vendor_prices.md"
        prices.write_text(PRICES_MD)
        self.env["LEADS_VENDOR_PRICES"] = str(prices)
        self.env["LEADS_STRENGTH"] = str(self.t / "no-strength.md")      # the defaults in bin/leads
        conn = sqlite3.connect(self.db)
        conn.execute("""INSERT INTO place_cache (place_id, name, address, phone, website, has_website, rating, reviews,
                        lat, lng, refreshed_at, locality, postal_code, primary_type, types, business_status,
                        google_maps_uri) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (WEST, "West Desert Roofing", "120 N Main St, American Fork, UT 84003, USA", "(801) 555-0120",
                      "https://westdesertroofing.example/", "yes", 4.9, 92, 40.3929, -111.7958, "2026-09-28T12:00:00",
                      "American Fork", "84003", "roofing_contractor", '["roofing_contractor"]', "OPERATIONAL",
                      f"https://maps.google.com/?cid={WEST}"))
        conn.execute("""INSERT INTO businesses (place_id, segment, category, categories, city, first_seen, source,
                        presence_class, presence_url, presence_checked, is_chain, chain_override)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (WEST, "services", "roofing", '["roofing"]', "American Fork, Utah", "2026-09-28", "scan_services",
                      "dead", "https://westdesertroofing.example/", "2026-09-28T12:00:00", 0, None))
        conn.execute("""CREATE TABLE hosts (place_id TEXT PRIMARY KEY, vendor TEXT, evidence TEXT, status TEXT,
                        checked TEXT, url TEXT, kind TEXT)""")
        conn.execute("INSERT INTO hosts VALUES (?,?,?,?,?,?,?)",
                     (WEST, "hibu", json.dumps({"why": "cname live.websites.hibu.com"}), "404", "2026-09-29T20:00:00",
                      "https://westdesertroofing.example/", "agency"))
        conn.commit()
        conn.close()

    def touches(self, name):
        return [e["touch"] for e in self.events() if e.get("kind") == "touch_due" and e["name"] == name]

    def kit_ids(self, now):
        r = self.run_leads("kit", "--remote", "--census-only", "--json", "--no-save", "--n", "20",
                           "--segment", "services", now=now)
        self.assertEqual(r.returncode, 0, r.stderr)
        return {p["place_id"] for p in json.loads(r.stdout)["picks"]}

    def cadence_on(self, *days):
        for t in days:
            r = self.run_leads("cadence", now=D0 + dt.timedelta(days=t))
            self.assertEqual(r.returncode, 0, r.stderr)


class ScoreTest(StrengthBase):
    def test_brief_says_strong_and_why(self):
        r = self.run_leads("brief", "West Desert Roofing")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("  Strength: strong · Hibu site dead · 92 reviews at 4.9 · 1.1 mi · quotes jobs", r.stdout)
        s = self.run_leads("strength", "West Desert Roofing")
        self.assertIn("West Desert Roofing (American Fork): strong", s.stdout)
        self.assertIn("  +6  Hibu site dead", s.stdout)
        self.assertIn("cadence: day 3, 10, 30, 45, 60, 90, never back in the pool without your word", s.stdout)

    def test_candidates_put_strong_first_and_every_line_says_why(self):
        r = self.run_leads("candidates", "--segment", "services", "--radius", "50")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("strong first, then good, then weak", r.stdout)
        rows = [l for l in r.stdout.splitlines() if l.startswith("  ")]
        self.assertTrue(rows[0].startswith("  strong · Hibu site dead · 92 reviews at 4.9 · quotes jobs │"), rows[0])
        self.assertTrue(rows[0].endswith("hibu ($449+/mo, 404)"), rows[0])      # B71's tag is untouched
        rank = {"strong": 0, "good": 1, "weak": 2}
        levels = [rank[l.split()[0]] for l in rows]
        self.assertEqual(levels, sorted(levels), r.stdout)
        for l in rows:
            level, _, why = l.strip().partition(" │")[0].partition(" · ")
            self.assertIn(level, rank)
            self.assertTrue(why, f"a line with no reason: {l}")
        weak = next(l for l in rows if "Timp Pressure Washing" in l)
        self.assertTrue(weak.startswith("  weak · "), weak)

    def test_the_kits_and_the_morning_say_it_too(self):
        page = self.run_leads("kit", "--segment", "services", "--census-only", "--no-save").stdout
        self.assertIn("1. West Desert Roofing — 1.1 mi", page)
        self.assertIn("   Strength: strong · Hibu site dead · 92 reviews at 4.9 · 1.1 mi", page)
        remote = self.run_leads("kit", "--remote", "--census-only", "--no-save", "--segment", "services").stdout
        # a DM kit keeps the messageable first, strong first within; the SMS-sized page keeps the level alone
        self.assertIn("5. West Desert Roofing — roofing · American Fork · 4.9★ (92)", remote)
        self.assertRegex(remote, r"(?m)^5\. West Desert Roofing .* · strong$")
        self.assertRegex(remote, r"(?m)^1\. Mike's Pool Care .* · good$")
        msg = self.run_leads("today", "--census-only", "--no-save", now="2026-09-28").stdout
        six = [l for l in msg.splitlines() if l[:2].rstrip(".").isdigit()]
        self.assertTrue(six and all(" · strong" in l or " · good" in l or " · weak" in l for l in six), msg)

    def test_the_weights_are_read_from_strength_md(self):
        doc = self.t / "strength.md"
        doc.write_text("| reason | weight |\n|---|---|\n| `paying_dead` | 1 |\n\n| level | at least |\n|---|---|\n"
                       "| strong | 6 |\n| good | 4 |\n")
        r = self.run_leads("strength", "West Desert Roofing", env={"LEADS_STRENGTH": str(doc)})
        self.assertIn(": good", r.stdout)
        self.assertIn("  +1  Hibu site dead", r.stdout)

    def test_a_chain_is_always_weak(self):
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE businesses SET chain_override = 'yes' WHERE place_id = ?", (WEST,))
        conn.commit()
        conn.close()
        r = self.run_leads("strength", "West Desert Roofing")
        self.assertIn(": weak", r.stdout)
        self.assertIn("-10  a chain", r.stdout)


class OverrideTest(StrengthBase):
    def test_taylors_word_wins_and_survives_a_rescore(self):
        self.assertIn(": weak", self.run_leads("strength", "Glacier Snow Removal").stdout)
        r = self.run_leads("strength", "Glacier Snow Removal", "strong", "the owner called back about winter")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Glacier Snow Removal (American Fork): strong — Taylor's word", r.stdout)
        self.assertIn('Taylor: "the owner called back about winter"', r.stdout)
        ev = [e for e in self.events() if e.get("kind") == "strength"]
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["strength"], ev[0]["place_id"]), ("strong", "FX_S08"))
        # the override is kept on the pipeline file but is never a lead by itself
        self.assertIn("The pipeline is empty", self.run_leads("pipeline").stdout)
        self.assertIn("FX_S08", self.kit_ids(now="2026-09-28"))
        # a re-score: the census changes under it (now in the fit band) — the word still wins
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE place_cache SET reviews = 60, rating = 4.9 WHERE place_id = 'FX_S08'")
        conn.commit()
        conn.close()
        self.assertIn(": strong — Taylor's word", self.run_leads("strength", "Glacier Snow Removal").stdout)
        line = next(l for l in self.run_leads("candidates", "--segment", "services").stdout.splitlines()
                    if "Glacier" in l)
        self.assertTrue(line.startswith('  strong · Taylor: "the owner called back about winter"'), line)
        # `auto` hands it back to the score, which is the re-scored one
        r = self.run_leads("strength", "Glacier Snow Removal", "auto")
        self.assertIn("Glacier Snow Removal (American Fork): good", r.stdout)
        self.assertIn("60 reviews at 4.9", r.stdout)

    def test_the_cadence_changes_only_when_the_strength_does(self):
        self.messaged("Mike's Pool Care", D0, "FX_S01", source="dm", reach="facebook.com/mikespoolcare")
        self.cadence_on(3, 10, 30, 45)
        self.assertEqual(self.touches("Mike's Pool Care"), [3, 10, 30])       # good: exactly what it always was
        self.run_leads("strength", "Mike's Pool Care", "strong", "he asked twice about pricing")
        self.cadence_on(45)
        self.assertEqual(self.touches("Mike's Pool Care"), [3, 10, 30, 45])


class CadenceTest(StrengthBase):
    def test_strong_gets_six_touches_then_the_sunday_list_weak_gets_two_then_the_pool(self):
        self.messaged("West Desert Roofing", D0, WEST, source="dm", phone="(801) 555-0120",
                      reach="facebook.com/westdesertroofing", email="info@westdesert.example")
        self.messaged("Glacier Snow Removal", D0, "FX_S08", source="dm", reach="Instagram @glaciersnowut")
        self.messaged("Mike's Pool Care", D0, "FX_S01", source="dm", reach="facebook.com/mikespoolcare")
        self.cadence_on(3, 10, 30, 45, 60, 90, 120)
        self.assertEqual(self.touches("West Desert Roofing"), [3, 10, 30, 45, 60, 90])
        self.assertEqual(self.touches("Glacier Snow Removal"), [3, 10])
        self.assertEqual(self.touches("Mike's Pool Care"), [3, 10, 30])
        chans = {e["touch"]: e["channel"] for e in self.events()
                 if e.get("kind") == "touch_due" and e["name"] == "West Desert Roofing"}
        self.assertEqual(chans[60], "call")                                    # the call in the follow-up list
        self.assertEqual(chans[45], "email")                                   # the channel the first one wasn't
        touch = [e for e in self.events() if e.get("kind") == "touch_due" and e["touch"] == 90][0]
        self.assertEqual(touch["strength"], "strong")
        self.assertIn("paying_dead", touch["reasons"])
        # the pool: weak back at 30, good at 90, strong never without the word
        at31 = self.kit_ids(now=D0 + dt.timedelta(days=31))
        self.assertIn("FX_S08", at31)
        self.assertNotIn("FX_S01", at31)
        self.assertNotIn(WEST, at31)
        at91 = self.kit_ids(now=D0 + dt.timedelta(days=91))
        self.assertIn("FX_S01", at91)
        self.assertNotIn(WEST, at91)
        # the Sunday review: strong, silent, for Taylor's call
        week = self.run_leads("week", now=D0 + dt.timedelta(days=97))
        self.assertIn("Strong, silent (1)", week.stdout)
        self.assertIn("West Desert Roofing (American Fork) — messaged 2025-01-06, six touches", week.stdout)
        self.assertNotIn("Glacier", week.stdout)
        byc = self.run_leads("week", "--by", "channel", now=D0 + dt.timedelta(days=97)).stdout
        self.assertIn("Strong, silent (1)", byc)
        self.assertLess(len(byc.splitlines()), 25, byc)
        # `later` keeps it: off the silent list, still out of the pool
        self.run_leads("log", "West Desert Roofing", "later", "call in November")
        self.assertNotIn("Strong, silent", self.run_leads("week", now=D0 + dt.timedelta(days=97)).stdout)
        self.assertNotIn(WEST, self.kit_ids(now=D0 + dt.timedelta(days=97)))

    def test_the_day_sixty_call_is_on_the_due_list(self):
        self.messaged("West Desert Roofing", D0, WEST, source="dm", phone="(801) 555-0120",
                      reach="facebook.com/westdesertroofing")
        self.cadence_on(60)
        due = self.run_leads("due", now=D0 + dt.timedelta(days=60)).stdout
        self.assertIn("West Desert Roofing (American Fork) · contacted, day 60 touch by call", due)
        cad = self.run_leads("cadence", "--dry-run", now=D0 + dt.timedelta(days=60)).stdout
        self.assertNotIn("West Desert", cad)                                   # filed once


class LogAndWeekTest(StrengthBase):
    def test_a_logged_row_carries_its_strength_and_reasons(self):
        r = self.run_leads("log", "West Desert Roofing", "messaged", "the Hibu 404", "--channel", "facebook")
        self.assertEqual(r.returncode, 0, r.stderr)
        e = self.events()[-1]
        self.assertEqual(e["strength"], "strong")
        self.assertEqual(e["reasons"][0], "paying_dead")
        self.assertIn("fit", e["reasons"])
        r = self.run_leads("log", "Some Guy Nobody Knows", "talked", "at the counter")
        self.assertEqual(self.events()[-1]["strength"], "good")                 # unscored: today's cadence

    def test_week_by_strength_prints_outcomes_by_strength_and_reason(self):
        self.messaged("West Desert Roofing", D0, WEST, source="dm", strength="strong",
                      reasons=["paying_dead", "fit", "near", "ladder"])
        self.messaged("Glacier Snow Removal", D0, "FX_S08", source="dm", strength="weak",
                      reasons=["near", "reach", "ladder"])
        self.messaged("Glacier Snow Removal", D0 + dt.timedelta(days=2), "FX_S08", outcome="talked", source="dm")
        self.messaged("Mike's Pool Care", D0, "FX_S01", source="dm")           # before B73: scored now
        r = self.run_leads("week", "--by", "strength", now=D0 + dt.timedelta(days=6))
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("Leads by strength", out)
        self.assertIn("  strong  1 · 0 · 0 · 0 · 0 · 0", out)
        self.assertIn("  good    1 · 0 · 0 · 0 · 0 · 0", out)
        self.assertIn("  weak    1 · 1 · 1 · 0 · 0 · 0 · 100% replied", out)
        self.assertRegex(out, r"(?m)^  paying_dead\s+\+6  1 messaged · 0 replied · 0 won")
        self.assertRegex(out, r"(?m)^  ladder\s+\+1  3 messaged · 1 replied · 0 won")
        j = json.loads(self.run_leads("week", "--by", "strength", "--json", now=D0 + dt.timedelta(days=6)).stdout)
        self.assertEqual(j["by_strength"]["weak"]["replied"], 1)
        self.assertEqual(j["by_reason"]["near"]["messaged"], 3)

    def test_pipeline_strong_lists_only_the_strong_with_why(self):
        self.messaged("West Desert Roofing", D0, WEST, source="dm")
        self.messaged("Glacier Snow Removal", D0, "FX_S08", source="dm")
        r = self.run_leads("pipeline", "--strong")
        self.assertIn("strong: 1", r.stdout)
        self.assertIn("West Desert Roofing (American Fork) · contacted", r.stdout)
        self.assertIn("strong · Hibu site dead", r.stdout)
        self.assertNotIn("Glacier", r.stdout)


if __name__ == "__main__":
    unittest.main()
