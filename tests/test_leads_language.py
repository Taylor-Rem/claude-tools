"""B74's `language` table, read here: the tag on the kit, `today` and `candidates` lines, the remote kit's
JSON, `brief`, and `doctor` — and nothing at all when client-leads/scripts/language.py hasn't run.

Runs on the made-up services census in fixtures/leads-services (the same one test_leads_today.py uses), with
a `language` table written by hand. No Google call, no real lead.

    python3 -m unittest discover -s tests -q   (from claude-tools/)
"""
import json
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_leads_today import ANCHOR, Base, leads_module


def add_language(db, rows):
    conn = sqlite3.connect(db)
    conn.execute("""CREATE TABLE IF NOT EXISTS language (place_id TEXT PRIMARY KEY, language TEXT, evidence TEXT,
                    checked TEXT, basis TEXT)""")
    conn.executemany("INSERT OR REPLACE INTO language VALUES (?,?,?,?,?)",
                     [(pid, lang, json.dumps({"why": why}), "2026-09-29T21:00:00", basis)
                      for pid, lang, basis, why in rows])
    conn.commit()
    conn.close()


SEED = [
    ("FX_S01", "es", "reviews", "4 of 5 reviews in Spanish"),                          # Mike's Pool Care
    ("FX_S02", "both", "site", "English site with \"se habla español\" (0 Spanish / 199 English words)"),
    ("FX_S04", "es", "name", "name only: Spanish name (limpieza) — no website on the listing, no cached listing"),
    ("FX_S05", "en", "site", "site in English (0 Spanish / 182 English words)"),       # Dave's Handyman
    ("FX_S12", "unknown", "none", "nothing to read but an English or neutral name"),
]


class LanguageTest(Base):
    def seed(self):
        add_language(self.db, SEED)

    def line(self, out, name):
        return next(l for l in out.splitlines() if name in l)

    def test_the_tag_helper(self):
        self.seed()
        m = leads_module()
        m.CENSUS = self.db
        self.assertEqual("lang: es", m.language_tag("FX_S01"))
        self.assertEqual("lang: es+en", m.language_tag({"place_id": "FX_S02"}))
        self.assertEqual("lang: es (name only)", m.language_tag("FX_S04"))
        for pid in ("FX_S05", "FX_S12", "FX_S03", None):                 # English, unknown, no row, no id
            self.assertIsNone(m.language_tag(pid), pid)
        self.assertEqual({"language": "both", "basis": "site", "checked": "2026-09-29T21:00:00",
                          "why": "English site with \"se habla español\" (0 Spanish / 199 English words)"},
                         m.language_info("FX_S02"))

    def test_candidates_lines_carry_the_tag_and_only_for_spanish(self):
        self.seed()
        out = self.run_leads("candidates", "--segment", "services", "--n", "20", "--radius", "50").stdout
        self.assertTrue(self.line(out, "Mike's Pool Care").endswith("· lang: es"), out)
        self.assertTrue(self.line(out, "Blue Canyon Landscaping").endswith("· lang: es+en"), out)
        self.assertTrue(self.line(out, "Timp Pressure Washing").endswith("· lang: es (name only)"), out)
        for name in ("Dave's Handyman", "Lehi Lawn Bros", "Wasatch Pest Pros"):
            self.assertNotIn("lang:", self.line(out, name), name)

    def test_the_kits_line_carries_it(self):
        self.seed()
        r = self.run_leads("kit", "--segment", "services", "--census-only", "--radius", "50", "--n", "12", "--no-save")
        self.assertEqual(r.returncode, 0, r.stderr)
        head = self.line(r.stdout, "Mike's Pool Care")
        self.assertRegex(head, r"^\d+\. Mike's Pool Care — .* · lang: es$")
        self.assertNotIn("lang:", self.line(r.stdout, "Dave's Handyman"))

    def test_the_remote_kit_line_and_its_json(self):
        self.seed()
        r = self.run_leads("kit", "--remote", "--segment", "services", "--census-only", "--no-save",
                           "--n", "12", "--radius", "50")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.line(r.stdout, "Mike's Pool Care").endswith("· lang: es"))
        r = self.run_leads("kit", "--remote", "--segment", "services", "--census-only", "--json", "--no-save",
                           "--n", "12", "--radius", "50")
        by = {p["name"]: p for p in json.loads(r.stdout)["picks"]}
        self.assertEqual("es", by["Mike's Pool Care"]["language"]["language"])
        self.assertEqual("reviews", by["Mike's Pool Care"]["language"]["basis"])
        self.assertEqual("en", by["Dave's Handyman Services"]["language"]["language"])
        self.assertIsNone(by["Wasatch Pest Pros"]["language"])            # no row: null, the key still there

    def test_todays_line_carries_it(self):
        self.seed()
        r = self.run_leads("today", "--census-only", now=ANCHOR)
        self.assertEqual(r.returncode, 0, r.stderr)
        mike = self.line(r.stdout, "Mike's Pool Care")
        self.assertTrue(mike.endswith(" · lang: es"), mike)
        dave = [l for l in r.stdout.splitlines() if "Dave's Handyman" in l and l[:1].isdigit()]
        for l in dave:
            self.assertNotIn("lang:", l)

    def test_brief_prints_the_evidence(self):
        self.seed()
        out = self.run_leads("brief", "Mike's Pool Care", now=ANCHOR).stdout
        self.assertIn("  Language: es — 4 of 5 reviews in Spanish", out)
        out = self.run_leads("brief", "Lehi Lawn Bros", now=ANCHOR).stdout
        self.assertNotIn("Language:", out)                                # unknown says nothing

    def test_doctor_counts_the_table(self):
        self.seed()
        self.assertIn("language: 5 rows judged — es 2, both 1, en 1, unknown 1; newest check 2026-09-29",
                      self.run_leads("doctor").stdout)

    def test_restaurant_candidates_carry_it_too(self):
        conn = sqlite3.connect(self.db)
        conn.execute("""INSERT INTO place_cache (place_id, name, address, phone, website, has_website, rating, reviews,
                        lat, lng, refreshed_at, locality, primary_type, business_status)
                        VALUES ('FX_T01', 'Taquería La Prueba', '1 Main St, American Fork, UT', '(801) 555-0199', '',
                                'no', 4.7, 80, 40.381, -111.79, '2026-09-28T12:00:00', 'American Fork',
                                'mexican_restaurant', 'OPERATIONAL')""")
        conn.execute("""INSERT INTO restaurants (place_id, city, status, channel_class, is_chain, on_doordash)
                        VALUES ('FX_T01', 'American Fork, Utah', 'Open', 'marketplace-only', 0, 1)""")
        conn.commit()
        conn.close()
        add_language(self.db, [("FX_T01", "es", "name", "name only: Spanish name (taqueria)")])
        r = self.run_leads("candidates", "--segment", "restaurant", "--radius", "50")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.line(r.stdout, "Taquería La Prueba").endswith("· lang: es (name only)"), r.stdout)

    def test_no_table_means_no_tag_and_nothing_breaks(self):
        out = self.run_leads("candidates", "--segment", "services", "--n", "20", "--radius", "50").stdout
        self.assertNotIn("lang:", out)
        r = self.run_leads("kit", "--remote", "--segment", "services", "--census-only", "--json", "--no-save",
                           "--n", "12", "--radius", "50")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(all(p["language"] is None for p in json.loads(r.stdout)["picks"]))
        self.assertNotIn("lang:", self.run_leads("today", "--census-only", now=ANCHOR).stdout)
        self.assertIn("language: no language table yet — B74", self.run_leads("doctor").stdout)


if __name__ == "__main__":
    unittest.main()
