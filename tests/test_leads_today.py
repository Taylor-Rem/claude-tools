"""The 07:30 message, the brief, the cadence (B48), the Sunday review (B52) and the reach read (B61).

Everything here runs on the made-up services census in fixtures/leads-services and a pipeline
written by hand, so no Google call is made and no real lead is touched. The clock is LEADS_NOW.

    python3 -m unittest discover -s tests -q   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent / "lib"))
from prices import letter_sha  # noqa: E402  the hash outreach keeps Taylor's approval against (lib/prices.py)

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

    def test_mondays_message_is_under_sixty_lines_and_carries_each_dm(self):
        r = self.run_leads("today", "--census-only", now=ANCHOR)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertLess(len(lines), 60, r.stdout)
        self.assertTrue(lines[0].startswith("Morning — Mon 28 Sep · services · 6 to send"), lines[0])
        six = [i for i, l in enumerate(lines) if l[:2].rstrip(".").isdigit()]
        self.assertEqual(len(six), 6)
        for i in six:
            self.assertGreaterEqual(len(lines[i].split(" · ")), 4, lines[i])   # name · category · city · how
            under = lines[i + 1]
            self.assertTrue(under.startswith("Hi, I'm Taylor. A small business owner in American Fork.") or
                            under.startswith('Say: "Hi, is this '), under)
        at = next(i for i in six if "Mike's Pool Care" in lines[i])       # B73: strong first, so not by position
        mike = lines[at]
        self.assertIn("Facebook: facebook.com/mikespoolcare", mike)
        self.assertTrue(mike.endswith("· good · 14 reviews at 4.9 · 0.4 mi"), mike)   # B73: the level and why, last
        dm = lines[at + 1]
        # 2026-09-29, the register: one fault, a question last; no preview yet, so the offer to build one
        self.assertEqual(dm, "Hi, I'm Taylor. A small business owner in American Fork. Looked Mike's Pool Care up on Google. 14 reviews "
                             "at 4.9, but the website link on your listing goes to Facebook, not a site of your own. "
                             "I can build you one in an afternoon — want to see what it'd look like?")
        self.assertEqual(lines[at + 2], '(no preview built — leads preview "Mike\'s Pool Care")')
        for i in six:
            if lines[i + 1].startswith("Hi, I'm Taylor. A small business owner in American Fork."):
                self.assertNotRegex(lines[i + 1], r"\btheir\b|\bthey\b|\[|preview|http", lines[i + 1])
        self.assertNotIn("$", r.stdout)                      # no price in the morning message
        self.assertFalse((self.t / "ledger.jsonl").exists(), "census-only costs nothing")

    def test_the_factorys_proposal_is_in_the_message_while_fresh(self):
        """B150: `infra tick` files its proposal beside the state dir; the morning message carries its line."""
        (self.t / "infra").mkdir()
        p = self.t / "infra" / "proposal.json"
        p.write_text(json.dumps({"date": ANCHOR.isoformat(), "line": "Factory: the pool outruns capacity. Taylor's go."}))
        r = self.run_leads("today", "--census-only", now=ANCHOR)
        self.assertIn("\nFactory: the pool outruns capacity. Taylor's go.\n", r.stdout)
        p.write_text(json.dumps({"date": (ANCHOR - dt.timedelta(days=5)).isoformat(), "line": "Factory: old news."}))
        self.assertNotIn("Factory:", self.run_leads("today", "--census-only", now=ANCHOR).stdout)

    def test_a_pick_with_only_a_phone_gets_the_call_and_the_opener(self):
        r = self.run_leads("today", "--census-only", now=ANCHOR)
        lines = r.stdout.splitlines()
        i = next(i for i, l in enumerate(lines) if "Timp Pressure Washing" in l)
        self.assertIn("call: (801) 555-0104 · weak", lines[i])           # B73: the strength follows the how
        # 2026-09-30: the register in the prep call frame; no preview yet, so the offer
        self.assertEqual(lines[i + 1], 'Say: "Hi, is this Timp Pressure Washing? This is Taylor, a small business owner in American Fork. Looked '
                                       'you up on Google — the website link on your listing is your Thumbtack page, not a '
                                       'site of your own. I can build you one in an afternoon — could I text you what '
                                       'it\'d look like?"')
        self.assertEqual(lines[i + 2], "")

    def test_no_reply_words_while_email_cannot_send_and_one_reason_why(self):
        r = self.run_leads("today", "--census-only", now=ANCHOR)
        self.assertNotIn("Needs a word", r.stdout)
        self.assertNotIn("go 1 3", r.stdout)
        self.assertEqual(r.stdout.splitlines()[-1],
                         "Email is off today — no postal address for the footer yet (LEADS_MAIL_ADDRESS, "
                         "TAYLOR-TODO §1) — so the six are yours to send; no word needed.")

    def test_the_word_is_not_asked_for_once_the_lane_runs_itself(self):
        r = self.run_leads("today", "--census-only", env={"OUTREACH_AUTO": "1"}, now=ANCHOR)
        self.assertNotIn("Needs a word", r.stdout)

    def test_json_carries_the_message_and_everything_in_it(self):
        r = self.run_leads("today", "--census-only", "--json", now=ANCHOR)
        d = json.loads(r.stdout)
        self.assertEqual(sorted(d), ["date", "due", "email_off", "first_call", "fresh_kit", "inbound", "lane",
                                     "message", "replies", "segment", "six", "words"])
        self.assertEqual(d["date"], ANCHOR.isoformat())
        self.assertEqual(len(d["six"]), 6)
        self.assertTrue(d["message"].startswith("Morning — Mon 28 Sep"))
        for p in d["six"]:                                    # B48's keys stay; B62's are added
            for k in ("name", "category", "city", "phone", "email", "instagram", "facebook", "faults",
                      "preview_url", "message", "how", "dm", "say"):
                self.assertIn(k, p)
            self.assertIn(p["dm"] or p["say"], d["message"])
        self.assertEqual(d["words"], [])
        self.assertIn("LEADS_MAIL_ADDRESS", d["email_off"])


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
        self.assertEqual(self.run_leads("sent", "2", "--channel", "instagram").returncode, 0)
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
        # the kit is dated by the real clock, so `today` reads it on the same day (it passed only on ANCHOR itself)
        ran = dt.date.fromisoformat(saved[0].name[:10])
        r = self.run_leads("today", "--census-only", "--json", now=ran)
        self.assertFalse(json.loads(r.stdout)["fresh_kit"], "today reads the morning's run")
        names = [p["name"] for p in json.loads(r.stdout)["six"]]
        self.assertEqual(names, [p["name"] for p in json.loads(saved[0].read_text())["picks"]])


class MorningEmailTest(Base):
    """B62: the `go` footer only when `outreach send --go` would put a letter in the post."""

    def setUp(self):
        super().setUp()
        tpl = self.t / "tpl"
        tpl.mkdir()
        first = (LEADS.parent.parent / "templates" / "outreach" / "first.md").read_text()
        (tpl / "first.md").write_text(first)
        import hashlib
        (tpl / "APPROVED").write_text(f"# test\nfirst          {letter_sha(first)}\n")
        self.open = {"LEADS_MAIL_ADDRESS": "PO Box 1, American Fork, UT", "OUTREACH_TEMPLATES": str(tpl),
                     "OUTREACH_PROVIDER": "fake", "OUTREACH_PER_DAY": "5"}
        pick = {"category": "pool service", "segment": "services", "city": "Lehi", "phone": "(801) 555-0199",
                "instagram": None, "facebook": None, "maps_url": None, "summary": "",
                "faults": ["no website on Google", "only 2 photos"]}
        picks = [dict(pick, place_id="P1", name="Ada Pools", first="Ada Pools", email="ada@example.test",
                      preview_url="https://previews.patchlamp.com/ada-pools/"),
                 dict(pick, place_id="P2", name="Bo Pools", first="Bo Pools", email="bo@example.test", preview_url=None),
                 dict(pick, place_id="P3", name="Cy Pools", first="Cy Pools", email=None,
                      facebook="https://facebook.com/cypools", preview_url="https://previews.patchlamp.com/cy-pools/")]
        folder = self.t / "state" / "remote"
        folder.mkdir(parents=True)
        (folder / f"{ANCHOR.isoformat()}-services.json").write_text(
            json.dumps({"date": ANCHOR.isoformat(), "segment": "services", "picks": picks}))

    def today(self, **env):
        return self.run_leads("today", "--census-only", env=dict(self.open, **env), now=ANCHOR).stdout

    def test_every_gate_open_asks_for_the_word(self):
        out = self.today()
        self.assertIn("Needs a word: go — send the 1 email in today's six · go 1 3 — only those · hold 4", out)
        self.assertNotIn("Email is off", out)
        self.assertIn("1. Ada Pools · pool service · Lehi · email: ada@example.test — the letter goes on `go`", out)

    def test_the_first_closed_gate_is_the_one_reason(self):
        tpl = Path(self.open["OUTREACH_TEMPLATES"])
        cases = [({"LEADS_MAIL_ADDRESS": ""}, "no postal address"),
                 ({"OUTREACH_TEMPLATES": str(self.t)}, "the first letter isn't approved yet"),
                 ({"OUTREACH_PROVIDER": "", "INSTANTLY_API_KEY": ""}, "no mailbox yet (INSTANTLY_API_KEY)"),
                 ({"OUTREACH_PER_DAY": "0"}, "OUTREACH_PER_DAY is 0")]
        for env, why in cases:
            out = self.today(**env)
            self.assertNotIn("Needs a word", out, env)
            self.assertIn(f"Email is off today — {why}", out, env)
        (tpl / "first.md").write_text((tpl / "first.md").read_text() + "\nedited\n")   # the hash is stale
        self.assertIn("the first letter isn't approved yet", self.today())

    def test_a_preview_goes_into_the_dm_and_an_address_without_a_page_waits(self):
        out = self.today(OUTREACH_PER_DAY="0").splitlines()
        cy = out.index(next(l for l in out if l.startswith("3. Cy Pools")))
        self.assertTrue(out[cy + 1].startswith("Hi, I'm Taylor. A small business owner in American Fork."), out[cy + 1])
        self.assertTrue(out[cy + 1].endswith("So I went ahead and built you one. Want to see it?"), out[cy + 1])
        self.assertNotIn("http", out[cy + 1])                            # the link is message two, under it
        self.assertEqual(out[cy + 2], "When they say yes: https://previews.patchlamp.com/cy-pools/")
        self.assertTrue(out[cy + 4].startswith("It's $20 a month, no contract, to keep this site up"))   # Codex's message two, 2026-10-05
        self.assertTrue(out[cy + 6].endswith("Want this to be your live site?"))
        bo = next(l for l in out if l.startswith("2. Bo Pools"))
        self.assertIn("call: (801) 555-0199 (the email to bo@example.test waits for the email lane)", bo)

    def test_the_picks_close_the_gate_when_the_settings_are_open(self):
        f = self.t / "state" / "remote" / f"{ANCHOR.isoformat()}-services.json"
        kit = json.loads(f.read_text())
        kit["picks"][0]["preview_url"] = None                 # Ada has an address and no page now
        f.write_text(json.dumps(kit))
        self.assertIn("Email is off today — every letter carries a preview page and none of theirs is built yet (B45)",
                      self.today())
        for pk in kit["picks"]:
            pk["email"] = None
        f.write_text(json.dumps(kit))
        self.assertIn("Email is off today — none of the six has an address (B61 is finding them)", self.today())


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
        # B102: `week --json` alone is the overview's counts now; the B52 envelope is `--by channel --json`
        d = json.loads(self.run_leads("week", "--by", "channel", "--json", now=dt.date(2026, 10, 4)).stdout)
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

    def add_reach(self, rows, judged=True):
        """Rows as B61 wrote them; `judged` gives every column value the B104 judgement `high` (as `reach.py
        --check` leaves a tied one), so these tests read the table as it is after the check."""
        conn = sqlite3.connect(self.db)
        conn.execute("""CREATE TABLE IF NOT EXISTS reach (place_id TEXT PRIMARY KEY, instagram TEXT,
                        facebook TEXT, email TEXT, source TEXT, checked TEXT, evidence TEXT, unconfirmed TEXT)""")
        out = []
        for r in rows:
            r = list(r) + [None] * (8 - len(r))
            if judged and not str(r[6] or "").startswith("{"):
                ev = {"query": "fixture", "url": r[6]}
                for i, f in ((1, "instagram"), (2, "facebook"), (3, "email")):
                    if r[i]:
                        ev[f] = {"url": r[6], "value": r[i], "confidence": "high", "place": "names Utah (fixture)",
                                 "by": "reach.py"}
                r[6] = json.dumps(ev)
            out.append(tuple(r))
        conn.executemany("INSERT OR REPLACE INTO reach VALUES (?,?,?,?,?,?,?,?)", out)
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
                         ["category", "city", "email", "email_unconfirmed", "facebook", "faults", "first", "host",
                          "instagram", "language", "maps_url", "message", "name", "paying", "phone", "place_id",
                          "preview_url", "rating", "reach_skipped", "reach_unconfirmed", "reviews", "segment",
                          "summary", "variant"])
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


PRICES_MD = """# test prices

| vendor | says | kind | price | from | to | page | brief | note |
|---|---|---|---|---|---|---|---|---|
| hibu | Hibu | agency | reported | 449 | 1500 | https://www.flashcrafter.ai/blog/hibu-review-2026 | 2026-09-28-growth/competition.md:35 | |
| wix | Wix | builder | published | 17 | 46 | https://www.wix.com/plans | 2026-09-28-growth/pricing-and-economics.md:15 | |
| duda | Duda | builder | unpublished | 149 |  | https://www.duda.co/pricing | x | a number typed by mistake is never printed |
| thryv | Thryv | agency | published | 99 | 399 | https://www.thryv.com/pricing/ | x | |
| angi | Angi | directory | free |  |  |  |  | |
"""


class HostsTest(Base):
    """B71's `hosts` table and client-leads/vendor_prices.md, read here: the tag, the sort, the sentence, `{paying}`."""

    def setUp(self):
        super().setUp()
        prices = self.t / "vendor_prices.md"
        prices.write_text(PRICES_MD)
        self.env["LEADS_VENDOR_PRICES"] = str(prices)

    def add_hosts(self, rows):
        conn = sqlite3.connect(self.db)
        conn.execute("""CREATE TABLE IF NOT EXISTS hosts (place_id TEXT PRIMARY KEY, vendor TEXT, evidence TEXT,
                        status TEXT, checked TEXT, url TEXT, kind TEXT)""")
        conn.executemany("INSERT OR REPLACE INTO hosts VALUES (?,?,?,?,?,?,?)",
                         [(pid, v, json.dumps(ev), st, "2026-09-29T20:00:00", url, kind)
                          for pid, v, kind, st, url, ev in rows])
        conn.commit()
        conn.close()

    def seed(self):
        self.add_hosts([
            ("FX_S03", "hibu", "agency", "404", "https://wasatch-pest-pros.example/",
             {"why": "cname live.websites.hibu.com", "dns": {"ns": ["ns29.domaincontrol.com"]}}),
            ("FX_S05", "wix", "builder", "200", "https://daveshandyman.wixsite.com/home",
             {"why": "header x-wix-request-id", "url_host": "wixsite.com"}),
            ("FX_S12", "angi", "directory", "page", "https://www.angi.com/x", {"url_host": "angi.com"}),
            ("FX_S01", "facebook", "social", "page", "https://www.facebook.com/mikespoolcare", {"url_host": "facebook.com"}),
            ("FX_S04", "unknown", "unknown", "nodns", "https://timp.example/", {"why": "no platform marker"}),
            ("FX_S08", "duda", "builder", "404", "https://glacier.example/", {"why": "cname s.multiscreensite.com"}),
        ])

    def test_candidates_carry_the_vendor_its_band_and_whether_it_answers(self):
        self.seed()
        out = self.run_leads("candidates", "--segment", "services", "--n", "20", "--radius", "50").stdout
        line = next(l for l in out.splitlines() if "Wasatch Pest Pros" in l)
        self.assertTrue(line.endswith("hibu ($449+/mo, 404)"), line)
        dave = next(l for l in out.splitlines() if "Dave's Handyman" in l)
        self.assertTrue(dave.endswith("wix (200)"), dave)           # a free address: no band to compare
        glacier = next(l for l in out.splitlines() if "Glacier" in l)
        self.assertTrue(glacier.endswith("duda (price unpublished, 404)"), glacier)
        self.assertNotIn("149", out)                                 # an unpublished row's typo never prints
        for name in ("Timp Pressure", "Lehi Lawn Bros", "Mike's Pool Care"):
            ln = next(l for l in out.splitlines() if name in l)
            self.assertNotRegex(ln, r"(unknown|angi|facebook) \(", ln)

    def test_paying_puts_the_agency_hosted_dead_site_first(self):
        self.seed()
        r = self.run_leads("candidates", "--segment", "services", "--paying")
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = [l for l in r.stdout.splitlines() if l.startswith("  ")]
        self.assertIn("Wasatch Pest Pros", rows[0])
        self.assertIn("hibu ($449+/mo, 404)", rows[0])
        self.assertIn("Glacier", rows[1])                           # dead, unpriced builder
        self.assertIn("Dave's Handyman", rows[2])                   # live
        self.assertEqual(3, len(rows), r.stdout)                    # unknown, free and directory rows are left out

    def test_no_table_means_no_fingerprint_and_nothing_breaks(self):
        r = self.run_leads("candidates", "--segment", "services", "--paying")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("No host fingerprint yet", r.stdout)
        r = self.run_leads("candidates", "--segment", "services")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("/mo", r.stdout)
        self.assertIn("hosts: no hosts table yet — B71", self.run_leads("doctor").stdout)

    def test_brief_prints_the_sentence_in_the_vendors_own_price(self):
        self.seed()
        r = self.run_leads("brief", "Wasatch Pest Pros", now=ANCHOR)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("  Hosting: Hibu's plans start at $449 a month (reported — Hibu quotes only; flashcrafter.ai); "
                      "their site for you returns a 404.", r.stdout)
        r = self.run_leads("brief", "Timp Pressure Washing", now=ANCHOR)
        self.assertNotIn("Hosting:", r.stdout)                      # unknown: no sentence at all

    def test_the_kit_json_carries_paying_for_a_hibu_row_and_null_otherwise(self):
        self.seed()
        r = self.run_leads("kit", "--remote", "--segment", "services", "--census-only", "--json", "--no-save",
                           "--n", "12", "--radius", "50")
        self.assertEqual(r.returncode, 0, r.stderr)
        by = {p["name"]: p for p in json.loads(r.stdout)["picks"]}
        self.assertEqual(by["Wasatch Pest Pros"]["paying"],
                         "Your site's address is set up with Hibu, whose plans are reported to start at $449 a month.")
        self.assertEqual(by["Wasatch Pest Pros"]["host"]["vendor"], "hibu")
        self.assertIsNone(by["Dave's Handyman Services"]["paying"])  # a free wixsite address: never "your bill"
        for name, p in by.items():
            if name not in ("Wasatch Pest Pros",):
                self.assertIsNone(p["paying"], name)

    def test_a_published_price_says_so_and_a_reported_one_says_reported(self):
        self.seed()
        self.add_hosts([("FX_S03", "thryv", "agency", "parked", "https://wasatch-pest-pros.example/", {})])
        m_out = self.run_leads("brief", "Wasatch Pest Pros", now=ANCHOR).stdout
        self.assertIn("Hosting: Thryv's plans start at $99 a month (its own pricing page); their domain shows a "
                      "parked page.", m_out)


class RegisterTest(unittest.TestCase):
    """2026-09-29, Taylor's register: one fault, a thing already built, a question last; message two holds the
    link, the AI line and the price. Pure functions, so the module is loaded and called directly."""

    HELLO = "Hi, I'm Taylor. A small business owner in American Fork. "

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.saved_previews = os.environ.get("LEADS_PREVIEWS")
        os.environ["LEADS_PREVIEWS"] = str(Path(cls.tmp.name) / "previews")
        cls.m = leads_module()
        cls.m.PREVIEWS = Path(cls.tmp.name) / "previews"
        cls.m.host_info = lambda pid: None               # no hosts table unless a test hangs one on
        cls.m._REACH = {}

    @classmethod
    def tearDownClass(cls):
        os.environ.pop("LEADS_PREVIEWS", None)
        if cls.saved_previews is not None:
            os.environ["LEADS_PREVIEWS"] = cls.saved_previews
        cls.tmp.cleanup()

    def pick(self, **kw):
        c = {"name": "Summit Roofing", "place_id": None, "reviews": 92, "rating": 4.9, "preview_url": "https://p.example/x/"}
        c.update(kw)
        return c

    def test_the_example_taylor_wrote_word_for_word(self):
        self.m.host_info = lambda pid: {"vendor": "hibu", "kind": "agency", "says": "Hibu", "status": "404"}
        try:
            dm = self.m.segment_dm_text(self.pick(place_id="X"), ["the website link (summitroofing.com) doesn't load",
                                                                  "no photos"])
        finally:
            self.m.host_info = lambda pid: None
        self.assertEqual(dm, self.HELLO + "Looked you up on Google. 92 reviews at 4.9, but the website link on your "
                             "listing goes to a Hibu page that doesn't load anymore. So I went ahead and built you one. "
                             "Want to see it?")

    def test_each_site_fault_said_once_to_the_owner(self):
        cases = {
            "no website on Google": ("there's no website on your listing", "one"),
            "no website — Google sends people to DoorDash": ("there's no website on your listing", "one"),
            "the website link (x.com) doesn't load": ("the website link on your listing (x.com) doesn't load anymore", "one"),
            "the website link is a business.site page, and Google shut those down in 2024: it's a dead link":
                ("the website link on your listing is a business.site page, which Google shut down in 2024, so it "
                 "goes nowhere", "one"),
            "the website is a free Wix address (dave.wixsite.com)":
                ("the website on your listing is a free Wix address (dave.wixsite.com)", "one of your own"),
            "the website link is a Facebook page, not a site of their own":
                ("the website link on your listing goes to Facebook, not a site of your own", "one"),
            "the website link is a DoorDash Storefront page, not their own":
                ("the website link on your listing goes to DoorDash Storefront, not a site of your own", "one"),
            "the website link is their Thumbtack profile, not a site of their own":
                ("the website link on your listing is your Thumbtack page, not a site of your own", "one"),
        }
        for fault, (said, one) in cases.items():
            dm = self.m.segment_dm_text(self.pick(), ["no photos", fault])     # the site fault, wherever it sits
            self.assertEqual(dm, self.HELLO + f"Looked you up on Google. 92 reviews at 4.9, but {said}. So I went "
                                              f"ahead and built you {one}. Want to see it?", fault)
            self.assertNotIn("photos", dm)                                      # one fault, not two

    def test_the_reviews_clause_only_when_it_is_worth_saying(self):
        for reviews, rating in ((9, 5.0), (40, 4.4), (None, None)):
            dm = self.m.segment_dm_text(self.pick(reviews=reviews, rating=rating), ["no website on Google"])
            self.assertEqual(dm, self.HELLO + "Looked you up on Google, and there's no website on your listing. "
                                              "So I went ahead and built you one. Want to see it?", (reviews, rating))
        dm = self.m.segment_dm_text(self.pick(reviews=10, rating=4.5), ["no website on Google"])
        self.assertIn("10 reviews at 4.5, but there's no website", dm)

    def test_looked_up_by_name_when_the_greeting_is_a_person(self):
        dm = self.m.segment_dm_text(self.pick(name="Mike's Pool Care LLC"), ["no website on Google"])
        self.assertIn("Looked Mike's Pool Care up on Google.", dm)

    def test_without_a_preview_the_offer_not_the_claim(self):
        dm = self.m.segment_dm_text(self.pick(preview_url=None), ["the website is a free Wix address (d.wixsite.com)"])
        self.assertTrue(dm.endswith("(d.wixsite.com). I can build you one of your own in an afternoon — want to see "
                                    "what it'd look like?"), dm)
        self.assertNotIn("built you", dm)

    def test_no_site_fault_names_the_first_fault(self):
        dm = self.m.segment_dm_text(self.pick(), ["no photos", "no hours on Google"])
        self.assertIn("but there are no photos on it. I went ahead and built you a website too. Want to see it?", dm)

    def test_restaurants_get_the_identical_register(self):
        for fs in (["no website — Google sends people to DoorDash"], ["the website link (a.com) doesn't load"]):
            self.assertEqual(self.m.dm_text(self.pick(), fs), self.m.segment_dm_text(self.pick(), fs))

    def test_message_one_has_no_price_no_link_no_intro(self):
        dm = self.m.segment_dm_text(self.pick(), ["no website on Google"])
        for word in ("$", "http", "I fix", "Free, no strings", "AI", "Patch"):
            self.assertNotIn(word, dm)

    def test_message_two_is_the_link_the_ai_line_and_hosting(self):
        two = self.m.then_text("https://p.example/x/")
        self.assertTrue(two.startswith("https://p.example/x/\n\nIt's $20 a month, no contract, to keep this site up on your own web address. "))
        for said in ("like changing your hours", "Bigger changes need a bigger plan", "my AI operator; I'm on the hook for it",
                     "You buy the web address if you need one; I help connect it", "Your Google listing can link to the site"):
            self.assertIn(said, two)
        self.assertTrue(two.endswith("Want this to be your live site?"))   # ends on a question, never on the exit
        self.assertNotIn("take it down", two)                              # the takedown promise is message one's only
        self.assertNotIn("—", two)                                         # Taylor doesn't type em dashes
        mp = self.m.morning_pick({"name": "Summit Roofing", "segment": "services", "faults": ["no website on Google"],
                                  "reviews": 92, "rating": 4.9, "preview_url": "https://p.example/x/",
                                  "facebook": "https://facebook.com/summitroofing"}, email_on=False)
        self.assertEqual(mp["then"], self.m.then_text("https://p.example/x/"))
        self.assertTrue(mp["dm"].endswith("built you one. Want to see it?"))
        mp = self.m.morning_pick({"name": "Summit Roofing", "segment": "services", "faults": ["no website on Google"],
                                  "facebook": "https://facebook.com/summitroofing"}, email_on=False)
        self.assertIsNone(mp["then"])

    def test_the_email_carries_the_link_and_message_two(self):
        subject, body = self.m.segment_email(self.pick(), ["no website on Google"])
        self.assertEqual(subject, "A website for Summit Roofing")
        self.assertTrue(body.startswith("Hi Summit Roofing,\n\nI'm Taylor Remund, a small business owner in American Fork. Looked you up"))
        self.assertTrue(body.endswith("So I went ahead and built you one. Here it is: " + self.m.then_text(
            "https://p.example/x/")), body)
        subject, body = self.m.segment_email(self.pick(preview_url=None), ["no website on Google"])
        self.assertEqual(subject, "Summit Roofing on Google")
        self.assertNotIn("http", body)

    def test_a_facebook_p_page_keeps_its_whole_path(self):
        fb = self.m.fb_page
        self.assertEqual(fb("https://www.facebook.com/p/PyneCo-Services-100090734772685"),
                         "facebook.com/p/PyneCo-Services-100090734772685")
        self.assertEqual(fb("https://www.facebook.com/pages/Foo-Bar/1234"), "facebook.com/pages/Foo-Bar/1234")
        self.assertIsNone(fb("https://facebook.com/p"))
        self.assertEqual(fb("https://facebook.com/SBPCU/"), "facebook.com/SBPCU")
        self.assertIsNone(self.m.fb_from_url("pynecoservices.com"))
        # a kit saved before the fix: the reach table's full page replaces the cut one
        self.m._REACH = {"PY": {"facebook": "facebook.com/p/PyneCo-Services-100090734772685", "instagram": None,
                                "evidence": json.dumps({"facebook": {
                                    "value": "https://www.facebook.com/p/PyneCo-Services-100090734772685",
                                    "confidence": "high", "place": "names Utah (the page title)"}})}}
        try:
            ig, page, skipped = self.m.pick_handles({"place_id": "PY", "name": "PyneCo Services",
                                                     "facebook": "https://facebook.com/p"})
        finally:
            self.m._REACH = {}
        self.assertEqual(page, "facebook.com/p/PyneCo-Services-100090734772685")

    def test_another_citys_instagram_is_refused_and_falls_through(self):
        # ProSlat Garage Store (American Fork), 2026-09-30: B61 found the Dallas franchise's account
        self.m._REACH = {"PS": {"instagram": "proslatgaragestore.dallas", "facebook": None,
                                "email": "info@lifetime-coatings.com", "evidence": json.dumps({
                                    "query": "\"ProSlat Garage Store\" American Fork Utah",
                                    # judged high by a slip (say): the city list behind it still refuses it
                                    "instagram": {"url": "https://www.instagram.com/proslatgaragestore.dallas/",
                                                  "title": "Proslat Garage Store Dallas (@proslatgaragestore.dallas)",
                                                  "value": "proslatgaragestore.dallas", "confidence": "high",
                                                  "place": "names Utah (fixture)"}})}}
        try:
            p = {"place_id": "PS", "name": "ProSlat Garage Store", "city": "American Fork", "segment": "services",
                 "instagram": "proslatgaragestore.dallas", "email": "info@lifetime-coatings.com",
                 "phone": "(801) 203-4466", "faults": ["the website link (lifetime-coatings.com) doesn't load"]}
            mp = self.m.morning_pick(p, email_on=False)
            out = self.m.reach_guard({"instagram": "proslatgaragestore.dallas", "facebook": None}, p)
        finally:
            self.m._REACH = {}
        self.assertTrue(mp["how"].startswith("call: (801) 203-4466"), mp["how"])
        self.assertEqual(mp["skipped"][0], "Instagram skipped: another city's account (Dallas)")
        # B104: the address B61 stored has no judgement yet, so it is said and not used
        self.assertEqual(mp["skipped"][1:], ["email: unconfirmed, call-only (not checked against the place yet "
                                             "(stored before B104; reach.py --check))"])
        self.assertIsNone(out["instagram"])
        # a Utah business named for the place keeps its own handle; a word inside another word is not a place
        self.assertIsNone(self.m.foreign_place("phoenixplumbingutah", {"name": "Phoenix Plumbing"}))
        self.assertIsNone(self.m.foreign_place("mesamovers", {"name": "Big Movers"}))
        self.assertEqual(self.m.foreign_place("sbpcdenver"), "Denver")

    def test_today_builds_previews_once_the_project_is_published(self):
        root = self.m.PREVIEWS
        root.mkdir(parents=True, exist_ok=True)
        saved = os.environ.pop("LEADS_KIT_PREVIEWS", None)
        env_file, self.m.ENV_FILE = self.m.ENV_FILE, root / "no-env"
        try:
            self.assertFalse(self.m.previews_on(), "no project.json yet")
            (root / "project.json").write_text(json.dumps({"pages_host": "patchlamp-previews.pages.dev"}))
            self.assertTrue(self.m.previews_on())
            os.environ["LEADS_KIT_PREVIEWS"] = "0"
            self.assertFalse(self.m.previews_on())
            os.environ["LEADS_KIT_PREVIEWS"] = "1"
            (root / "project.json").unlink()
            self.assertTrue(self.m.previews_on())
        finally:
            os.environ.pop("LEADS_KIT_PREVIEWS", None)
            if saved is not None:
                os.environ["LEADS_KIT_PREVIEWS"] = saved
            self.m.ENV_FILE = env_file

    def test_the_call_opener_names_the_same_fault_and_asks_to_text_the_link(self):
        p = dict(self.pick(), faults=["no photos", "the website is a free Wix address (d.wixsite.com)"])
        self.assertEqual(self.m.call_opener(p),
                         'Say: "Hi, is this Summit Roofing? This is Taylor, a small business owner in American Fork. Looked you up on Google — '
                         'the website on your listing is a free Wix address (d.wixsite.com), so I went ahead and built '
                         'you one of your own. Could I text you the link? Nothing to sign, and I\'ll take it down the '
                         'moment you say so."')
        said = self.m.site_fault_words(p, p["faults"][1])[0]
        self.assertIn(said, self.m.segment_dm_text(p, p["faults"]))           # the DM names the same fault
        self.assertEqual(self.m.call_opener(dict(p, preview_url=None)),
                         'Say: "Hi, is this Summit Roofing? This is Taylor, a small business owner in American Fork. Looked you up on Google — '
                         'the website on your listing is a free Wix address (d.wixsite.com). I can build you one of your '
                         'own in an afternoon — could I text you what it\'d look like?"')
        for text in (self.m.call_opener(p), self.m.call_opener(dict(p, preview_url=None))):
            self.assertNotIn("$", text)
            self.assertNotIn("http", text)

    def test_a_preview_build_that_breaks_is_the_offer_not_a_crash(self):
        def boom(*a, **k):
            raise RuntimeError("site previews fell over")
        real, self.m.make_previews = self.m.make_previews, boom
        try:
            c = dict(self.pick(preview_url=None), place_id="B1", faults=["no website on Google"], variant="listing",
                     message="old")
            self.m.kit_previews([c], build=True)
        finally:
            self.m.make_previews = real
        self.assertIsNone(c["preview_url"])
        self.assertTrue(c["message"].endswith("want to see what it'd look like?"), c["message"])
