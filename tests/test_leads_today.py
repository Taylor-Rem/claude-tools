"""The 07:30 message, the brief, the cadence (B48), the Sunday review (B52) and the reach read (B61).

Everything here runs on the made-up services census in fixtures/leads-services and a pipeline
written by hand, so no Google call is made and no real lead is touched. The clock is LEADS_NOW.

    python3 -m unittest discover -s tests -q   (from claude-tools/)
"""
import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEADS = HERE.parent / "bin" / "leads"
SERVICES = HERE / "fixtures" / "leads-services"

ANCHOR = dt.date(2026, 9, 28)          # a Monday: the message the acceptance line asks for


def build_census(path, businesses=True):
    import importlib.util
    spec = importlib.util.spec_from_file_location("leads_services_build", SERVICES / "build.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.build(path, businesses=businesses)


def leads_module():
    import importlib.util
    from importlib.machinery import SourceFileLoader
    spec = importlib.util.spec_from_loader("leads_mod", SourceFileLoader("leads_mod", str(LEADS)))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.t = t
        self.db = build_census(t / "census.db")
        self.pipeline = t / "pipeline.jsonl"
        self.outreach = t / "outreach"
        self.env = {"LEADS_DB": str(self.db), "LEADS_STATE": str(t / "state"),
                    "LEADS_LEDGER": str(t / "ledger.jsonl"), "LEADS_GROUPS_LOG": str(t / "groups.md"),
                    "CLAUDE_TOOLS_ENV": str(t / "no-env"), "LEADS_MAIL_ADDRESS": "", "GOOGLE_MAPS_API_KEY": "",
                    "LEADS_PIPELINE": str(self.pipeline), "LEADS_PREVIEWS": str(t / "previews"),
                    "LEADS_PREVIEW_HOST": "previews.patchlamp.com", "LEADS_SEGMENT": "",
                    "OUTREACH_STATE": str(self.outreach), "OUTREACH_AUTO": "",
                    "LEADS_BOOKING_URL": "", "LEADS_KIT_PREVIEWS": ""}

    def tearDown(self):
        self.tmp.cleanup()

    def run_leads(self, *args, env=None, now=None):
        e = dict(os.environ)
        e.update(self.env)
        e.update(env or {})
        if now:
            e["LEADS_NOW"] = now.isoformat() if hasattr(now, "isoformat") else now
        return subprocess.run([sys.executable, str(LEADS), *args], capture_output=True, text=True, env=e)

    def events(self):
        return [json.loads(x) for x in self.pipeline.read_text().splitlines()] if self.pipeline.exists() else []

    def messaged(self, name, day, place_id=None, city="American Fork", **extra):
        """A `messaged` event written by hand, so the cadence's clock can be moved."""
        row = {"ts": day.isoformat() + "T11:45:00-06:00", "date": day.isoformat(),
               "key": f"place:{place_id}" if place_id else f"name:{name.lower().replace(' ', '-')}",
               "place_id": place_id, "name": name, "city": city, "outcome": "messaged", "stage": "contacted",
               "next": (day + dt.timedelta(days=4)).isoformat(), "note": "the remote kit"}
        row.update(extra)
        with open(self.pipeline, "a") as f:
            f.write(json.dumps({k: v for k, v in row.items() if v is not None}) + "\n")
        return row

    def reply(self, day, name, cls, frm="hi@example.test"):
        self.outreach.mkdir(parents=True, exist_ok=True)
        with open(self.outreach / "replies.jsonl", "a") as f:
            f.write(json.dumps({"ts": day.isoformat() + "T08:00:00-06:00", "date": day.isoformat(),
                                "from": frm, "name": name, "class": cls, "answered": False}) + "\n")


class MorningTest(Base):
    """B48: `leads today`."""

    def test_mondays_message_is_under_forty_lines_and_names_the_six(self):
        r = self.run_leads("today", "--census-only", now=ANCHOR)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertLess(len(lines), 40, r.stdout)
        self.assertTrue(lines[0].startswith("Morning — Mon 28 Sep · services · 6 to send"), lines[0])
        six = [l for l in lines if l[:2].rstrip(".").isdigit()]
        self.assertEqual(len(six), 6)
        for l in six:
            bits = l.split(" · ")
            self.assertGreaterEqual(len(bits), 5, l)        # name · category · city · fault · reach
        self.assertIn("Mike's Pool Care", six[1])
        self.assertIn("not a site of their own", six[1])
        self.assertIn("facebook.com/mikespoolcare", six[1])
        self.assertIn("Needs a word: go", r.stdout)
        self.assertIn("go 1 3", r.stdout)
        self.assertIn("hold 4", r.stdout)
        self.assertNotIn("$", r.stdout)                      # no price in the morning message
        self.assertFalse((self.t / "ledger.jsonl").exists(), "census-only costs nothing")

    def test_the_word_is_not_asked_for_once_the_lane_runs_itself(self):
        r = self.run_leads("today", "--census-only", env={"OUTREACH_AUTO": "1"}, now=ANCHOR)
        self.assertNotIn("Needs a word", r.stdout)

    def test_json_carries_the_message_and_everything_in_it(self):
        r = self.run_leads("today", "--census-only", "--json", now=ANCHOR)
        d = json.loads(r.stdout)
        self.assertEqual(sorted(d), ["date", "due", "first_call", "fresh_kit", "inbound", "lane",
                                     "message", "replies", "segment", "six", "words"])
        self.assertEqual(d["date"], ANCHOR.isoformat())
        self.assertEqual(len(d["six"]), 6)
        self.assertTrue(d["message"].startswith("Morning — Mon 28 Sep"))

    def test_yesterdays_replies_come_from_the_outreach_inbox_log(self):
        r = self.run_leads("today", "--census-only", now=ANCHOR)
        self.assertIn("the email lane isn't running yet", r.stdout)     # no state dir at all
        self.reply(ANCHOR - dt.timedelta(days=1), "Glacier Snow Removal", "interested")
        self.reply(ANCHOR - dt.timedelta(days=1), "Rosie's Florals", "question")
        self.reply(ANCHOR - dt.timedelta(days=2), "Old One", "no")      # not yesterday
        r = self.run_leads("today", "--census-only", now=ANCHOR)
        self.assertIn("Yesterday: interested — Glacier Snow Removal · question — Rosie's Florals", r.stdout)
        self.assertNotIn("Old One", r.stdout)
        self.assertIn("2 replies yesterday", r.stdout)

    def test_a_next_thu_is_chased_on_thursday_and_the_cadence_leaves_it_alone(self):
        self.run_leads("kit", "--remote", "--census-only", "--segment", "services")
        self.assertEqual(self.run_leads("sent", "2").returncode, 0)
        r = self.run_leads("log", "Mike's Pool Care", "later", "he's on a job", "--next", "thu")
        self.assertEqual(r.returncode, 0, r.stderr)
        mike = [e for e in self.events() if e["name"] == "Mike's Pool Care"][-1]
        thursday = dt.date.fromisoformat(mike["next"])
        self.assertEqual(thursday.weekday(), 3)
        self.assertEqual(mike["next_by"], "hand")
        before = self.run_leads("today", "--census-only", now=thursday - dt.timedelta(days=1)).stdout
        self.assertNotIn("Mike's Pool Care — you said", before)
        after = self.run_leads("today", "--census-only", now=thursday).stdout
        self.assertIn("Mike's Pool Care — you said Thu", after)
        cad = self.run_leads("cadence", now=thursday)
        self.assertNotIn("Mike's Pool Care", cad.stdout, "a date Taylor named beats the cadence")

    def test_the_day_three_touch_is_the_other_channel_never_a_text(self):
        day = ANCHOR - dt.timedelta(days=3)
        self.messaged("Mike's Pool Care", day, "FX_S01", source="email", email="mike@example.test",
                      reach="facebook.com/mikespoolcare · mike@example.test")
        self.messaged("Glacier Snow Removal", day, "FX_S08", source="dm",
                      reach="Instagram @glaciersnowut · snow@example.test", email="snow@example.test")
        r = self.run_leads("cadence", now=ANCHOR)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Mike's Pool Care — day 3 by dm: DM facebook.com/mikespoolcare", r.stdout)
        self.assertIn("Glacier Snow Removal — day 3 by email: outreach send --touch 3 --dry-run", r.stdout)
        self.assertNotIn("text ", r.stdout.lower().replace("text patch", ""))   # never a cold SMS
        kinds = [(e["name"], e["touch"], e["channel"]) for e in self.events() if e.get("kind") == "touch_due"]
        self.assertEqual(sorted(kinds), [("Glacier Snow Removal", 3, "email"), ("Mike's Pool Care", 3, "dm")])
        self.assertIn("day 3 touch by dm", self.run_leads("due", now=ANCHOR).stdout)

    def test_the_day_ten_preview_expiry_is_drafted_by_outreach_and_named_in_the_message(self):
        day = ANCHOR - dt.timedelta(days=10)
        self.messaged("Glacier Snow Removal", day, "FX_S08", source="dm", email="snow@example.test",
                      reach="Instagram @glaciersnowut · snow@example.test")
        r = self.run_leads("cadence", "--dry-run", now=ANCHOR)
        self.assertIn("day 10 by email: outreach send --touch 10 --dry-run", r.stdout)
        self.assertEqual([e for e in self.events() if e.get("kind") == "touch_due"], [], "--dry-run writes nothing")
        self.run_leads("cadence", now=ANCHOR)
        msg = self.run_leads("today", "--census-only", now=ANCHOR).stdout
        self.assertIn("Glacier Snow Removal — day 10, the preview expiry: "
                      "outreach send --touch 10 --dry-run", msg)
        self.assertIn("snow@example.test", msg)
        # and it is not proposed twice
        self.run_leads("cadence", now=ANCHOR)
        self.assertEqual(len([e for e in self.events() if e.get("kind") == "touch_due"]), 1)

    def test_the_day_thirty_touch_reads_the_listing_once_and_says_what_changed(self):
        day = ANCHOR - dt.timedelta(days=30)
        self.messaged("Mike's Pool Care", day, "FX_S01", source="dm",
                      reach="facebook.com/mikespoolcare", was="the website link is a Facebook page, not a site of their own")
        self.run_leads("cadence", now=ANCHOR)
        msg = self.run_leads("today", "--fixture", str(SERVICES / "details"), now=ANCHOR).stdout
        self.assertIn("Mike's Pool Care — day 30, a fresh read of the listing", msg)
        self.assertIn("the listing now: new since the message: no hours on Google", msg)
        self.assertFalse((self.t / "ledger.jsonl").exists(), "a fixture listing costs nothing")
        blind = self.run_leads("today", "--census-only", now=ANCHOR).stdout
        self.assertIn("no Places key here — read the listing by hand", blind)

    def test_what_came_to_us_is_answered_first(self):
        """Flint, 2026-09-28: the relay's inbound lane logs `leads log NAME inbound …`."""
        r = self.run_leads("log", "Mike's Pool Care", "inbound", "site form: needs a quote page",
                           "--source", "inbound", "--phone", "(801) 555-0101")
        self.assertEqual(r.returncode, 0, r.stderr)
        e = self.events()[-1]
        self.assertEqual((e["outcome"], e["stage"], e["source"]), ("inbound", "interested", "inbound"))
        self.assertEqual(dt.date.fromisoformat(e["next"]) - dt.date.fromisoformat(e["date"]),
                         dt.timedelta(days=1), "chased tomorrow")
        msg = self.run_leads("today", "--census-only", now=dt.date.fromisoformat(e["date"])).stdout
        self.assertIn("What came to us (1) — answer these first:", msg)
        self.assertIn("Mike's Pool Care · (801) 555-0101 — site form: needs a quote page", msg)
        self.assertIn("First call: Mike's Pool Care", msg)          # inbound is the warmest thing there is
        self.assertLess(len(msg.splitlines()), 40)
        week = self.run_leads("week", "--by", "channel", now=dt.date.fromisoformat(e["date"])).stdout
        self.assertIn("  inbound   0 · 0 · 1 · 0 · 0 · 0 · 0", week)

    def test_the_first_call_is_the_warmest_lead_with_one_line_why(self):
        self.messaged("Mike's Pool Care", ANCHOR - dt.timedelta(days=6), "FX_S01", source="dm")
        self.run_leads("log", "Mike's Pool Care", "interested", "wants to see it on his phone", "--who", "Mike")
        msg = self.run_leads("today", "--census-only", now=ANCHOR).stdout
        self.assertRegex(msg, r"First call: Mike's Pool Care .*interested .*wants to see it on his phone")
        self.assertIn('leads brief "Mike\'s Pool Care"', msg)

    def test_a_kit_that_already_ran_today_is_not_paid_for_twice(self):
        self.run_leads("kit", "--remote", "--census-only", "--segment", "services")
        saved = list((self.t / "state" / "remote").glob("*.json"))
        self.assertEqual(len(saved), 1, "the remote run saves the envelope beside its page")
        r = self.run_leads("today", "--census-only", "--json", now=ANCHOR)
        self.assertFalse(json.loads(r.stdout)["fresh_kit"], "today reads the morning's run")
        names = [p["name"] for p in json.loads(r.stdout)["six"]]
        self.assertEqual(names, [p["name"] for p in json.loads(saved[0].read_text())["picks"]])


class BriefTest(Base):
    """B48: `leads brief NAME`."""

    def test_the_brief_has_the_fault_the_preview_the_history_the_objection_and_the_close(self):
        self.run_leads("preview", "Mike's Pool Care", "--census-only", "--no-publish", "--hero", "none")
        self.messaged("Mike's Pool Care", ANCHOR - dt.timedelta(days=4), "FX_S01", source="dm")
        self.run_leads("log", "Mike's Pool Care", "talked", "call him back Friday", "--who", "Mike")
        r = self.run_leads("brief", "Mike's Pool Care", now=ANCHOR)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("Mike's Pool Care — American Fork · pool service", out)
        self.assertIn("Wrong: the website link is a Facebook page, not a site of their own", out)
        self.assertIn("Preview: https://previews.patchlamp.com/mikes-pool-care-american-fork/", out)
        self.assertIn("messaged", out)
        self.assertIn("call him back Friday", out)
        self.assertIn('They\'ll say "All my work is referrals', out)      # § 6.2, the services objection
        self.assertIn("Your referrals still Google you before they call", out)
        self.assertIn('They\'ll say "$99 is a lot."', out)
        self.assertIn("I'm on the hook for all of it", out)               # the close
        self.assertIn("quote requests", out)                              # the segment's ladder
        self.assertIn("Booking link: not set yet", out)
        self.assertLess(len(out.splitlines()), 30, "one screen")
        ledger = (self.t / "ledger.jsonl").read_text()
        self.assertNotIn("places_details", ledger, "read-only without --live")

    def test_a_thumbtack_lead_gets_the_directory_objection_and_the_booking_link_when_it_is_set(self):
        r = self.run_leads("brief", "Timp Pressure Washing", env={"LEADS_BOOKING_URL": "https://cal.com/taylor/15"},
                           now=ANCHOR)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('They\'ll say "I\'m on Thumbtack / Angi."', r.stdout)
        self.assertIn("stop being only on Thumbtack", r.stdout)
        self.assertIn("Stage: not in the pipeline yet — this is a cold call", r.stdout)
        self.assertIn("Book them while you're on the phone: https://cal.com/taylor/15", r.stdout)

    def test_a_name_nobody_knows_says_so(self):
        r = self.run_leads("brief", "Zzqx Nonexistent Roofing", now=ANCHOR)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("isn't in the pipeline or the census", r.stderr)


class WeekTest(Base):
    """B52: the Sunday review."""

    def week(self, sunday=dt.date(2026, 10, 4)):
        return self.run_leads("week", "--by", "channel", now=sunday)

    def test_the_first_sundays_message_is_under_twenty_five_lines_and_cuts_by_channel(self):
        mon = dt.date(2026, 9, 28)
        self.messaged("Mike's Pool Care", mon, "FX_S01", source="dm")
        self.messaged("Glacier Snow Removal", mon, "FX_S08", source="email")
        self.messaged("Blue Canyon Landscaping", mon + dt.timedelta(days=1), "FX_S02", source="email")
        for name, pid, outcome, day, src in (("Mike's Pool Care", "FX_S01", "interested", 2, "dm"),
                                             ("Glacier Snow Removal", "FX_S08", "talked", 3, "email"),
                                             ("Glacier Snow Removal", "FX_S08", "trial", 4, "email"),
                                             ("Blue Canyon Landscaping", "FX_S02", "lost", 4, "email")):
            self.messaged(name, mon + dt.timedelta(days=day), pid, outcome=outcome,
                          stage={"interested": "interested", "talked": "contacted",
                                 "trial": "trialing", "lost": "lost"}[outcome], source=src)
        r = self.week()
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertLess(len(lines), 25, r.stdout)
        self.assertTrue(lines[0].startswith("Week of 28 Sep — by channel · sent · replies · conversations"))
        self.assertIn("  email     2 · 3 · 3 · 0 · 1 · 0 · 0", r.stdout)
        self.assertIn("  dm        1 · 1 · 1 · 0 · 0 · 0 · 0", r.stdout)
        self.assertIn("  total     3 · 4 · 4 · 0 · 1 · 0 · 0", r.stdout)
        self.assertIn("messages sent 3 [15]", r.stdout)
        self.assertIn("replies 4 [3]", r.stdout)
        self.assertIn("trials 1 [1]", r.stdout)
        self.assertIn("follow-ups due", r.stdout)
        self.assertIn("One change for the week", r.stdout)

    def test_json_is_the_row_the_experiment_log_wants(self):
        self.messaged("Mike's Pool Care", dt.date(2026, 9, 29), "FX_S01", source="saturday")
        d = json.loads(self.run_leads("week", "--json", now=dt.date(2026, 10, 4)).stdout)
        self.assertEqual(d["week_of"], "2026-09-28")
        self.assertEqual(sorted(d["total"]), ["churned", "conversations", "fixes", "paid", "replies",
                                              "sent", "trials"])
        self.assertEqual(d["by_channel"]["saturday"]["sent"], 1)
        self.assertEqual(d["indicators"]["messages sent"], 1)
        self.assertIn("message", d)

    def test_week_without_the_flag_is_what_it_always_was(self):
        self.messaged("Mike's Pool Care", ANCHOR, "FX_S01", source="dm")
        r = self.run_leads("week", now=ANCHOR)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Week of 28 Sep: 0 conversations, 1 message sent · 0 interested", r.stdout)
        self.assertIn("Kits: 0 Saturday, 0 remote this week.", r.stdout)
        self.assertEqual(len(r.stdout.splitlines()), 4)


class ReachTest(Base):
    """B61's table, read here: the census's own columns first, the table second."""

    def add_reach(self, rows):
        conn = sqlite3.connect(self.db)
        conn.execute("""CREATE TABLE IF NOT EXISTS reach (place_id TEXT PRIMARY KEY, instagram TEXT,
                        facebook TEXT, email TEXT, source TEXT, checked TEXT, evidence TEXT)""")
        conn.executemany("INSERT OR REPLACE INTO reach VALUES (?,?,?,?,?,?,?)", rows)
        conn.commit()
        conn.close()

    def test_the_kit_takes_a_handle_and_an_address_from_the_table(self):
        self.add_reach([
            # Blue Canyon has no website at all: the table is the only way in
            ("FX_S02", "bluecanyonlandscaping", "https://www.facebook.com/bluecanyonut", "hello@bluecanyon.example",
             "brave", "2026-09-28T09:00:00", "https://brave.example/1"),
            # Mike's listing already links Facebook: the census's own column wins, the email is new
            ("FX_S01", None, "facebook.com/somethingelse", "mike@mikespool.example", "brave",
             "2026-09-28T09:00:00", "https://brave.example/2"),
            # Dave's listing links a free Wix site: no page to message, so the address is the way in
            ("FX_S05", None, None, "dave@daveshandyman.example", "brave", "2026-09-28T09:00:00",
             "https://brave.example/3"),
        ])
        r = self.run_leads("kit", "--remote", "--segment", "services", "--census-only", "--json", "--no-save")
        self.assertEqual(r.returncode, 0, r.stderr)
        env = json.loads(r.stdout)
        self.assertEqual(sorted(env), ["date", "picks", "segment"])
        by = {p["name"]: p for p in env["picks"]}
        self.assertEqual(sorted(by["Mike's Pool Care"]),
                         ["category", "city", "email", "facebook", "faults", "first", "instagram", "maps_url",
                          "message", "name", "phone", "place_id", "preview_url", "segment", "summary"])
        blue = by["Blue Canyon Landscaping"]
        self.assertEqual(blue["instagram"], "bluecanyonlandscaping")
        self.assertEqual(blue["facebook"], "https://facebook.com/bluecanyonut")
        self.assertEqual(blue["email"], "hello@bluecanyon.example")
        mike = by["Mike's Pool Care"]
        self.assertEqual(mike["facebook"], "https://facebook.com/mikespoolcare", "the listing's own link wins")
        self.assertEqual(mike["email"], "mike@mikespool.example")
        self.assertEqual(by["Dave's Handyman Services"]["email"], "dave@daveshandyman.example")
        page = self.run_leads("kit", "--remote", "--segment", "services", "--census-only", "--no-save").stdout
        self.assertIn("Email: dave@daveshandyman.example", page)       # the only way in, so it is the reach line
        self.assertNotIn("No page to message — call (801) 555-0105", page)

    def test_doctor_prints_the_coverage_or_says_the_table_is_not_there(self):
        r = self.run_leads("doctor")
        self.assertIn("reach: no reach table yet — B61", r.stdout)
        self.add_reach([("FX_S02", "bluecanyonlandscaping", None, "hello@bluecanyon.example", "brave",
                         "2026-09-28T09:00:00", "https://brave.example/1")])
        r = self.run_leads("doctor")
        self.assertIn("reach: 1 rows searched — 1 Instagram, 0 Facebook, 1 email", r.stdout)
        self.assertNotIn("brave.example", r.stdout)

    def test_a_post_a_group_or_a_blank_is_not_a_handle(self):
        m = leads_module()
        self.assertEqual(m.ig_handle("https://www.instagram.com/mikespoolcare/"), "mikespoolcare")
        self.assertEqual(m.ig_handle("@mikespoolcare"), "mikespoolcare")
        self.assertIsNone(m.ig_handle("https://www.instagram.com/p/abc123/"))
        self.assertIsNone(m.ig_handle(""))
        self.assertEqual(m.fb_page("https://www.facebook.com/mikespoolcare/photos"), "facebook.com/mikespoolcare")
        self.assertEqual(m.fb_page("mikespoolcare"), "facebook.com/mikespoolcare")
        self.assertIsNone(m.fb_page("https://www.facebook.com/groups/utahmoms"))
        self.assertIsNone(m.fb_page(None))
        # a real listing from the 2026-09-28 run: facebook.com/share/<id> is somebody's share link
        self.assertIsNone(m.fb_page("https://www.facebook.com/share/1AbCdEf/"))
        self.assertIsNone(m.business_reach({"presence": "page", "presence_link": "https://www.facebook.com/share/1AbCdEf/"})["facebook"])


class ListingReadTest(unittest.TestCase):
    """Two faults wick-3 found porting the rules: a 24/7 listing, and Google's bare `service` type."""

    def test_open_twenty_four_hours_is_not_closed_on_saturday(self):
        m = leads_module()
        always = {"regularOpeningHours": {"periods": [{"open": {"day": 0, "hour": 0, "minute": 0}}]}}
        self.assertEqual(m.saturday_open(always), (0, 0))
        self.assertNotIn("Google says closed Saturdays", m.faults({"name": "x"}, always, dt.date(2026, 9, 28))[0])
        self.assertEqual(m.saturday_open({"regularOpeningHours": {"periods": [{"open": {"hour": 0}}]}}), (0, 0))
        shut = {"regularOpeningHours": {"periods": [{"open": {"day": 1, "hour": 9},
                                                     "close": {"day": 1, "hour": 17}}]}}
        self.assertEqual(m.saturday_open(shut), "closed")
        self.assertIsNone(m.saturday_open({}))

    def test_googles_bare_service_type_is_a_service_business(self):
        m = leads_module()
        self.assertTrue(m.is_service({"primary_type": "service"}, None))
        self.assertEqual(m.live_segment({"primaryType": "service"}), "services")
        c = {"segment": "services", "name": "Jericho Window & Power Washing"}
        fs, _ = m.business_faults(c, {"primaryType": "service", "formattedAddress": "833 N 100 E, Lehi",
                                      "photos": [{}] * 10, "nationalPhoneNumber": "x",
                                      "regularOpeningHours": {"periods": [{"open": {"day": 1}}]}},
                                 dt.date(2026, 9, 28))
        self.assertIn("Google shows a street address, not the area they serve", fs)


if __name__ == "__main__":
    unittest.main()
