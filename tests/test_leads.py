"""leads kit against the Place Details fixtures: no network, no census writes.
    python3 -m unittest discover -s tests -q   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEADS = HERE.parent / "bin" / "leads"
FIXTURES = HERE / "fixtures" / "leads"


def run(*args, env=None):
    e = dict(os.environ, **(env or {}))
    return subprocess.run([sys.executable, str(LEADS), *args], capture_output=True, text=True, env=e)


def picks(result):
    """`kit --remote --json` is B45's envelope: {date, segment, picks: [...]} (bin/leads docstring).
    `kit --json` without --remote is still the plain list."""
    return json.loads(result.stdout)["picks"]


@unittest.skipUnless((Path.home() / "projects/client-leads/wasatch.db").exists(), "needs the census")
class KitTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = {"LEADS_STATE": self.tmp.name, "LEADS_LEDGER": str(Path(self.tmp.name) / "ledger.jsonl"),
                    "LEADS_GROUPS_LOG": str(Path(self.tmp.name) / "leads-from-groups.md"),
                    "CLAUDE_TOOLS_ENV": str(Path(self.tmp.name) / "no-env"), "LEADS_MAIL_ADDRESS": "",
                    "GOOGLE_MAPS_API_KEY": "", "LEADS_PIPELINE": str(Path(self.tmp.name) / "pipeline.jsonl"),
                    "LEADS_PREVIEWS": str(Path(self.tmp.name) / "previews"),
                    "LEADS_SEGMENT": "restaurant"}     # these are the restaurant kit's tests; B44's segments are below

    def tearDown(self):
        self.tmp.cleanup()

    def test_fixture_kit_picks_six_open_saturday(self):
        r = run("kit", "--fixture", str(FIXTURES), "--for", "2026-09-26", "--json", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        names = [x["name"] for x in rows]
        self.assertEqual(len(rows), 6)
        self.assertNotIn("China Isle Restaurant", names)      # opens Sat 4pm
        self.assertNotIn("Off Road Mexican Food", names)      # closed Saturdays
        self.assertNotIn("Kahi Sushi", names)                 # CLOSED_TEMPORARILY
        self.assertEqual(names[0], "Whistle Wok")             # nearest first
        fong = next(x for x in rows if x["name"] == "Fong Asian Dining")
        self.assertIn("only 3 photos", " · ".join(fong["faults"]))
        self.assertTrue(any("2★" in f for f in fong["faults"]))
        jal = next(x for x in rows if "Jalisco" in x["name"])
        self.assertIn("no hours on Google", jal["faults"])
        self.assertIn("no website", " ".join(jal["faults"]))
        self.assertFalse((Path(self.tmp.name) / "ledger.jsonl").exists(), "fixtures cost nothing")

    def test_page_and_census_only(self):
        r = run("kit", "--fixture", str(FIXTURES), "--for", "2026-09-26", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Saturday kit — Sat 26 Sep", r.stdout)
        self.assertIn("Skipped: China Isle Restaurant (opens Sat 4pm)", r.stdout)
        self.assertIn("Text me the fix", r.stdout)
        self.assertLess(len(r.stdout), 4000, "one Telegram message")
        r = run("kit", "--census-only", "--no-save", "--for", "2026-09-26", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("census", r.stdout.splitlines()[1])
        self.assertNotIn("g_mp=", r.stdout)

    def test_candidates_and_doctor_run(self):
        r = run("candidates", "--n", "3", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.strip().splitlines()), 4)
        r = run("doctor", env=self.env)
        self.assertIn("census:", r.stdout)


    # -- B25: the remote lane -----------------------------------------------------------

    def test_remote_kit_is_six_messages_that_each_name_a_real_fault(self):
        r = run("kit", "--remote", "--census-only", "--json", "--no-save", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        envelope = json.loads(r.stdout)
        self.assertEqual(sorted(envelope), ["date", "picks", "segment"])
        self.assertEqual(envelope["segment"], "restaurant")
        rows = envelope["picks"]
        self.assertEqual(len(rows), 6)
        for x in rows:
            self.assertTrue(x["faults"], x["name"])
            self.assertFalse(any(f.startswith(("only ", "rating ")) for f in x["faults"]), x["faults"])
            self.assertIsNone(x["preview_url"], "no preview without --previews")
        reachable = [x for x in rows if x["instagram"] or x["facebook"] or x["email"]]
        self.assertEqual(len(reachable), 6, "messageable leads come first")

    def test_remote_page_fits_one_message_and_is_honest_about_email(self):
        r = run("kit", "--remote", "--census-only", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(len(r.stdout), 3901, "one Telegram message")
        self.assertIn("Remote kit —", r.stdout)
        self.assertIn("Hi, I'm Taylor. A small business owner in American Fork. Looked you up on Google", r.stdout)   # the register
        self.assertIn("don't send yet", r.stdout)                 # no postal address, no ready email
        self.assertNotIn("not their own", r.stdout.split("Email footer")[0].split('"Hi')[1])
        self.assertNotIn("$", r.stdout)                            # no price in a cold message
        log = (Path(self.tmp.name) / "leads-from-groups.md").read_text()
        self.assertEqual(log.count("| remote kit |"), 6)
        # tomorrow's kit doesn't repeat today's six
        again = picks(run("kit", "--remote", "--census-only", "--json", "--no-save", env=self.env))
        first = json.loads((Path(self.tmp.name) / "remote.jsonl").read_text().splitlines()[0])["place_ids"]
        self.assertFalse(set(first) & {x["place_id"] for x in again})
        env = dict(self.env, LEADS_MAIL_ADDRESS="PO Box 1, American Fork, UT 84003")
        r = run("kit", "--remote", "--census-only", "--no-save", "--allow-repeat", env=env)
        self.assertIn("PO Box 1, American Fork", r.stdout)
        self.assertNotIn("don't send yet", r.stdout)

    def test_diagnose_a_name_from_a_thread_in_three_lines_and_log_it(self):
        r = run("diagnose", "Fong Asian Dining", "--group", "Utah Small Businesses", "--fixture", str(FIXTURES), env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        para = r.stdout.split("\n\n")[0].splitlines()
        self.assertEqual(len(para), 3, r.stdout)
        self.assertTrue(para[0].startswith("Fong Asian Dining: "))
        self.assertIn("only 3 photos", para[1])
        self.assertIn("Happy to walk you through", para[2])
        self.assertNotIn("$", r.stdout)
        log = (Path(self.tmp.name) / "leads-from-groups.md").read_text()
        self.assertIn("| Fong Asian Dining | ", log)
        self.assertIn("group: Utah Small Businesses", log)

    def test_diagnose_census_only_with_a_city_and_an_unknown_name(self):
        r = run("diagnose", "Off Road Mexican, American Fork", "--no-log", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Off Road Mexican Food:", r.stdout)
        self.assertIn("no website", r.stdout)
        self.assertIn("census only", r.stdout)
        r = run("diagnose", "Zzqx Nonexistent Eatery", env=self.env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("isn't in the census", r.stderr)
        self.assertFalse((Path(self.tmp.name) / "leads-from-groups.md").exists())


    # -- B40: the tool line -------------------------------------------------------------

    def test_kit_prints_the_tool_line_for_a_listing_with_no_booking_link(self):
        r = run("kit", "--fixture", str(FIXTURES), "--for", "2026-09-26", "--json", env=self.env)
        rows = {x["name"]: x for x in json.loads(r.stdout)}
        self.assertEqual(rows["Avenue Bakery"]["booking"], "reservations on Google")     # the fixture is reservable
        self.assertIsNone(rows["Whistle Wok"]["booking"])                                # order.online is ordering, not booking
        r = run("kit", "--fixture", str(FIXTURES), "--for", "2026-09-26", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        blocks = {b.split(" — ")[0].split(". ", 1)[1]: b for b in r.stdout.split("\n\n") if b[:2].rstrip(".").isdigit()}
        self.assertIn("No booking link → the tool line", blocks["Whistle Wok"])
        self.assertNotIn("No booking link", blocks["Avenue Bakery"])
        self.assertEqual(r.stdout.count("No booking link → the tool line"), 5)
        self.assertIn("The tool line", r.stdout)
        self.assertIn("patchlamp.com/tools", r.stdout)
        self.assertIn("Send him the sheet you keep", r.stdout)
        self.assertLess(len(r.stdout), 4000, "still one Telegram message")
        tool = [l for l in r.stdout.splitlines() if l.startswith("The tool line")][0]
        self.assertNotIn("$", tool)
        self.assertNotIn("order", tool.replace("catering orders", ""), "ordering is not on offer")

    def test_booking_link_and_the_service_variant(self):
        import importlib.util
        from importlib.machinery import SourceFileLoader
        spec = importlib.util.spec_from_loader("leads_mod", SourceFileLoader("leads_mod", str(LEADS)))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.assertEqual(m.booking_link({}, {"websiteUri": "https://www.opentable.com/r/x"}), "books on opentable.com")
        self.assertEqual(m.booking_link({"website": "https://juniper.square.site/"}, None), "books on juniper.square.site")
        self.assertIsNone(m.booking_link({}, {"websiteUri": "https://order.online/business/x"}))
        pool = {"name": "Juniper Flats Pool & Spa", "primary_type": "pool_cleaning_service", "faults": ["no hours on Google"]}
        food = {"name": "Whistle Wok", "primary_type": "chinese_restaurant", "faults": ["no hours on Google"]}
        self.assertTrue(m.is_service(pool, None))
        self.assertFalse(m.is_service(food, None))
        self.assertFalse(m.is_service({"primary_type": "catering_service"}, None))
        self.assertFalse(m.is_service({"primary_type": "restaurant"}, None))
        variant, text = m.message_for(dict(pool, booking=None))
        self.assertEqual(variant, "tool")
        self.assertIn("no way to book you online", text)
        self.assertIn("no hours on Google", text)
        self.assertIn("patchlamp.com/tools", text)
        self.assertNotIn("$", text)
        self.assertEqual(m.message_for(dict(pool, booking="books on vagaro.com"))[0], "listing")
        self.assertEqual(m.message_for(dict(food, booking=None))[0], "listing")
        subject, body = m.email_draft(dict(pool, variant="tool"), pool["faults"])
        self.assertEqual(subject, "Juniper Flats Pool & Spa: booking online")
        self.assertTrue(body.startswith("Hi Juniper Flats Pool & Spa team,\n\nI'm Taylor Remund —"))


    # -- B7: the pipeline ---------------------------------------------------------------

    def events(self):
        p = Path(self.tmp.name) / "pipeline.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def test_one_text_logs_a_counter_visit_and_returns_tomorrows_list(self):
        r = run("log", "Whistle Wok", "talked", "owner Mike, wants the demo", "--who", "Mike", "--next", "tomorrow", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Logged: Whistle Wok (American Fork) — talked → contacted", r.stdout)
        tomorrow = r.stdout.split("\n\n", 1)[1]
        self.assertTrue(tomorrow.startswith("Tomorrow, "), tomorrow)
        self.assertIn("1. Whistle Wok (American Fork) · contacted, talked", tomorrow)
        self.assertIn('"owner Mike, wants the demo"', tomorrow)
        self.assertIn("NEW ", tomorrow)                               # topped up to six from the census
        self.assertEqual(tomorrow.count("NEW "), 5)
        [e] = self.events()
        self.assertEqual((e["who"], e["stage"], e["via"] if "via" in e else None), ("Mike", "contacted", None))
        self.assertTrue(e["place_id"].startswith("ChIJ"))

    def test_stages_follow_ups_and_the_week(self):
        run("log", "Whistle Wok", "talked", env=self.env)
        run("log", "Whistle Wok", "interested", "wants pricing", env=self.env)       # same lead, moves on
        run("log", "Off Road Mexican, American Fork", "lost", "happy with DoorDash", env=self.env)
        run("log", "Joe's Taco Truck, Lehi", "messaged", "--next", "today", "--channel", "instagram", env=self.env)
        self.assertEqual(len({e["key"] for e in self.events()}), 3)
        joe = [e for e in self.events() if e["name"] == "Joe's Taco Truck"][0]
        self.assertIsNone(joe.get("place_id"), "not The Taco Truck: a wrong match is worse than none")
        due = run("due", env=self.env).stdout
        self.assertIn("Joe's Taco Truck (Lehi)", due)
        self.assertNotIn("Off Road", due)
        show = run("show", "whistle wok", env=self.env).stdout
        self.assertIn("interested", show.splitlines()[0])
        self.assertIn("wants pricing", show)
        week = run("week", env=self.env).stdout
        self.assertIn("3 conversations, 1 message sent · 1 interested", week)
        self.assertIn("0 won so far", week)
        pipe = run("pipeline", env=self.env).stdout
        self.assertIn("interested: 1", pipe)
        self.assertIn("lost: 1", pipe)
        # the kits leave a lost lead and one with a follow-up ahead alone
        kit = picks(run("kit", "--remote", "--census-only", "--json", "--no-save", env=self.env))
        self.assertNotIn("Off Road Mexican Food", [x["name"] for x in kit])
        self.assertNotIn("WHISTLE WOK", [x["name"] for x in kit])

    def test_sent_marks_remote_kit_picks_as_messaged(self):
        run("kit", "--remote", "--census-only", env=self.env)
        r = run("sent", "1", "3", "--channel", "instagram", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Logged 2 sent", r.stdout)
        self.assertEqual([e["outcome"] for e in self.events()], ["messaged", "messaged"])
        self.assertNotEqual(run("sent", "9", env=self.env).returncode, 0)

    def test_dates_a_phone_would_type(self):
        for when in ("fri", "friday", "next fri", "3d", "2w", "oct 3", "2026-10-01"):
            r = run("log", "Whistle Wok", "later", "--next", when, env=self.env)
            self.assertEqual(r.returncode, 0, f"{when}: {r.stderr}")
        r = run("log", "Whistle Wok", "later", "--next", "someday", env=self.env)
        self.assertIn("can't read the date", r.stderr)
        self.assertNotEqual(run("log", "Whistle Wok", "maybe", env=self.env).returncode, 0)

    def test_segment_restaurant_is_the_restaurant_kit_unchanged(self):
        """B44: --segment restaurant prints what `leads kit` printed before segments existed."""
        env = {k: v for k, v in self.env.items() if k != "LEADS_SEGMENT"}
        for extra in ([], ["--remote"]):
            pinned = run("kit", *extra, "--census-only", "--no-save", env=self.env)            # LEADS_SEGMENT=restaurant
            flag = run("kit", *extra, "--census-only", "--no-save", "--segment", "restaurant", env=env)
            self.assertEqual(flag.returncode, 0, flag.stderr)
            self.assertEqual(pinned.stdout, flag.stdout)
        self.assertEqual(run("candidates", env=self.env).stdout, run("candidates", "--segment", "restaurant", env=env).stdout)


# -- B44: the kit and the diagnose for any segment, on a made-up services census ----------------

SERVICES = HERE / "fixtures" / "leads-services"


def fixture_census(path, businesses=True):
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


class SegmentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.db = fixture_census(t / "census.db")
        self.env = {"LEADS_DB": str(self.db), "LEADS_STATE": str(t / "state"), "LEADS_LEDGER": str(t / "ledger.jsonl"),
                    "LEADS_GROUPS_LOG": str(t / "leads-from-groups.md"), "CLAUDE_TOOLS_ENV": str(t / "no-env"),
                    "LEADS_MAIL_ADDRESS": "", "GOOGLE_MAPS_API_KEY": "", "LEADS_PIPELINE": str(t / "pipeline.jsonl"),
                    "LEADS_PREVIEWS": str(t / "previews"), "LEADS_SEGMENT": ""}

    def tearDown(self):
        self.tmp.cleanup()

    def test_services_kit_is_six_nearest_with_presence_and_faults(self):
        r = run("kit", "--segment", "services", "--census-only", "--json", "--no-save", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        names = [x["name"] for x in rows]
        # B73: strong first (a dead business.site of their own), then good by score, then weak; nearest within
        self.assertEqual(names, ["Wasatch Pest Pros", "Mike's Pool Care", "Blue Canyon Landscaping",
                                 "Canyon Air HVAC", "Dave's Handyman Services", "Glacier Snow Removal"])
        for gone in ("Summit Plumbing & Drain", "Sparkle Home Cleaning", "ProCoat Painters", "Elite Garage Doors"):
            self.assertNotIn(gone, names)            # own site, no phone, a chain, closed
        by = {x["name"]: x for x in rows}
        self.assertEqual(by["Glacier Snow Removal"]["presence"], "page")        # unknown in the census, read from the link
        self.assertEqual(by["Wasatch Pest Pros"]["presence"], "dead")
        self.assertIn("business.site", by["Wasatch Pest Pros"]["faults"][0])
        whole = {x["name"]: x for x in json.loads(run("kit", "--segment", "services", "--census-only", "--json",
                                                      "--no-save", "--n", "20", env=self.env).stdout)}
        self.assertIn("Thumbtack profile", whole["Timp Pressure Washing"]["faults"][0])
        self.assertIn("free Wix address", by["Dave's Handyman Services"]["faults"][0])
        self.assertEqual(by["Blue Canyon Landscaping"]["faults"], ["no website on Google"])
        page = run("kit", "--segment", "services", "--census-only", "--no-save", env=self.env).stdout
        self.assertTrue(page.startswith("Services kit — "))
        self.assertIn("Presence: page — facebook.com/mikespoolcare", page)
        self.assertIn("$99 a month and I'm on the hook", page)
        self.assertIn("quote requests", page)
        self.assertNotRegex(page.lower(), r"\border(ing|s)?\b")
        self.assertLess(len(page), 4000)

    def test_services_is_the_default_once_the_census_has_rows(self):
        self.assertEqual(run("kit", "--census-only", "--no-save", env=self.env).stdout,
                         run("kit", "--census-only", "--no-save", "--segment", "services", env=self.env).stdout)
        pre = fixture_census(Path(self.tmp.name) / "pre.db", businesses=False)
        env = dict(self.env, LEADS_DB=str(pre))
        r = run("kit", "--segment", "services", "--census-only", "--no-save", env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no services census yet", r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        r = run("candidates", env=env)                              # the default falls back to restaurants
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("marketplace-only", r.stdout)
        doc = run("doctor", env=env).stdout
        self.assertIn("services census: not yet", doc)
        self.assertIn("default segment: restaurant", doc)

    def test_fixture_listings_add_hours_photos_and_the_service_area(self):
        r = run("kit", "--segment", "services", "--fixture", str(SERVICES / "details"), "--json", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        by = {x["name"]: x for x in json.loads(r.stdout)}
        mike = by["Mike's Pool Care"]["faults"]
        for f in ("no hours on Google", "only 2 photos", "Google shows a street address, not the area they serve"):
            self.assertIn(f, mike)
        self.assertTrue(any("2★" in f for f in mike))
        blue = by["Blue Canyon Landscaping"]["faults"]
        self.assertEqual(blue, ["no website on Google"])             # hours, ten photos, a service area
        self.assertFalse((Path(self.tmp.name) / "ledger.jsonl").exists(), "fixtures cost nothing")

    def test_remote_creatives_is_six_messages_greeted_by_name(self):
        r = run("kit", "--remote", "--segment", "creatives", "--census-only", "--json", "--no-save", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = picks(r)
        self.assertEqual(len(rows), 6)
        msgs = {x["name"]: x["message"] for x in rows}
        # 2026-09-30, the register: no greeting by name any more; "Looked you up" when the business is the greeting
        self.assertIn("Looked Photography by Jenna up on Google", msgs["Photography by Jenna"])
        self.assertIn("Looked Rosie's Florals up on Google", msgs["Rosie's Florals"])
        self.assertIn("Looked you up on Google", msgs["Beat Drop DJs"])
        self.assertIn("there's no website on your listing.", msgs["Beat Drop DJs"])
        for m in msgs.values():
            self.assertTrue(m.startswith("Hi, I'm Taylor. A small business owner in American Fork. Looked "), m)
            self.assertNotIn("team", m)
            self.assertNotIn("$", m)
            self.assertNotIn("their", m)
            self.assertNotIn("http", m)                                  # the link is message two
            self.assertTrue(m.endswith("want to see what it'd look like?"), m)   # no preview built: the offer
        self.assertNotIn("Lens & Light Studio", msgs)                 # an own site isn't a lead
        page = run("kit", "--remote", "--segment", "creatives", "--census-only", env=self.env)
        self.assertEqual(page.returncode, 0, page.stderr)
        self.assertLess(len(page.stdout), 3901)
        self.assertIn("DM on Instagram: instagram.com/photosbyjenna.ut", page.stdout)
        self.assertIn("Message on Facebook: facebook.com/rosiesfloralsutah", page.stdout)
        log = (Path(self.tmp.name) / "leads-from-groups.md").read_text()
        self.assertEqual(log.count("| remote kit ("), 6)
        again = run("kit", "--remote", "--segment", "creatives", "--census-only", "--json", "--no-save", env=self.env)
        self.assertEqual(again.returncode, 1)                      # the fixture has six; tomorrow doesn't repeat them
        self.assertIn("left to message", again.stderr)
        r = run("sent", "1", "2", "--channel", "facebook", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Logged 2 sent", r.stdout)

    def test_diagnose_answers_a_services_name_from_the_census(self):
        env = dict(self.env, GOOGLE_MAPS_API_KEY="not-a-key", HTTPS_PROXY="http://127.0.0.1:9", https_proxy="http://127.0.0.1:9")
        r = run("diagnose", "Mike's Pool Care, American Fork", "--group", "Utah County Moms",
                "--fixture", str(SERVICES / "details"), env=env)          # the listing is right there; it isn't read
        self.assertEqual(r.returncode, 0, r.stderr)
        para = r.stdout.split("\n\n")[0].splitlines()
        self.assertEqual(len(para), 3, r.stdout)
        self.assertTrue(para[0].startswith("Mike's Pool Care: 4.9★ from 14 reviews"))
        self.assertIn("Facebook page", para[1])
        self.assertIn("A site of your own", para[2])
        self.assertIn("from the services census", r.stdout)
        self.assertNotIn("only 2 photos", r.stdout)
        self.assertNotIn("Places", r.stdout + r.stderr)                  # no call was tried
        self.assertFalse((Path(self.tmp.name) / "ledger.jsonl").exists())
        self.assertNotIn("$", r.stdout)
        log = (Path(self.tmp.name) / "leads-from-groups.md").read_text()
        self.assertIn("| Mike's Pool Care | American Fork | group: Utah County Moms |", log)
        r = run("diagnose", "Mike's Pool Care", "--live", "--fixture", str(SERVICES / "details"), "--no-log", env=self.env)
        self.assertIn("only 2 photos", r.stdout)
        r = run("diagnose", "Zzqx Nonexistent Roofing", "--no-log", env=self.env)       # unknown, no key: says so
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("isn't in the census", r.stderr)

    def test_all_candidates_doctor_and_next(self):
        # B73: the kit is strong first now, so the whole pool (--n 20) to see every segment in it
        r = run("kit", "--segment", "all", "--census-only", "--no-save", "--json", "--n", "20", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        segs = {x["segment"] for x in json.loads(r.stdout)}
        self.assertTrue({"services", "creatives", "retail"} <= segs, segs)
        page = run("kit", "--segment", "all", "--census-only", "--no-save", "--n", "20", env=self.env).stdout
        self.assertIn("Then the shop:", page)
        self.assertIn("Then the site:", page)
        r = run("candidates", "--segment", "nonprofit", env=self.env)
        self.assertIn("Lehi Youth Soccer League", r.stdout)
        self.assertNotIn("Grace Community Church", r.stdout)
        doc = run("doctor", env=self.env).stdout
        self.assertIn("services census: 23 rows (creatives 7, nonprofit 2, retail 2, services 12)", doc)
        self.assertIn("presence: none 8", doc)
        self.assertIn("default segment: services", doc)
        r = run("next", env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("NEW Glacier Snow Removal (snow removal, American Fork", r.stdout)
        r = run("log", "Mike's Pool Care", "talked", "wants a site", env=self.env)
        self.assertIn("Logged: Mike's Pool Care (American Fork) — talked", r.stdout)

    def test_presence_from_the_link(self):
        m = leads_module()
        cases = {None: "none", "": "none", "https://www.facebook.com/x": "page", "https://instagram.com/x": "page",
                 "https://linktr.ee/x": "page", "https://sites.google.com/view/x": "page",
                 "https://www.thumbtack.com/ut/x": "directory", "https://www.yelp.com/biz/x": "directory",
                 "https://x.business.site/": "dead", "https://x.wixsite.com/home": "builder",
                 "https://x.godaddysites.com": "builder", "https://x.square.site": "builder",
                 "https://x.webnode.page": "builder", "https://x.com/": "own", "https://notfacebook.com": "own"}
        for url, cls in cases.items():
            self.assertEqual(m.presence_from_url(url)[0], cls, url)
        self.assertEqual(m.first_name("Mike's Pool Care"), "Mike")
        self.assertEqual(m.first_name("Photography by Jenna"), "Jenna")
        self.assertIsNone(m.first_name("Utah's Best Lawn Care"))
        self.assertIsNone(m.first_name("Blue Canyon Landscaping"))
        self.assertIsNone(m.first_name("Timp's Pest Control"))
        self.assertIsNone(m.live_segment({"primaryType": "chinese_restaurant"}))
        self.assertEqual(m.live_segment({"primaryType": "pest_control_service"}), "services")
        self.assertEqual(m.live_segment({"primaryType": "store"}), "retail")        # a storefront: no service-area fault
        shop = {"segment": "retail", "name": "Lehi Mills", "website": "https://lehimills.com"}
        fs, _ = m.business_faults(shop, {"websiteUri": "https://lehimills.com", "formattedAddress": "833 N 100 E, Lehi",
                                         "photos": [{}] * 10, "nationalPhoneNumber": "x",
                                         "regularOpeningHours": {"periods": [{"open": {"day": 1}}]}}, None)
        self.assertEqual(fs, [])


if __name__ == "__main__":
    unittest.main()
