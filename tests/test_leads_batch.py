"""`leads batch` — the email lane's batch and its facts packet (ROADMAP B90, plan 37 § Contract).

    python3 -m unittest discover -s tests -q   (from claude-tools/)

Offline: the census is B44's fixture census (tests/fixtures/leads-services/build.py) with B89's three tables
added here and sixteen made-up plumbers and roofers (FX_B ids, 555 numbers, .example domains). The suppression
list comes from a stand-in `outreach`, the clients from a throwaway clients/ tree, and nothing reaches Google, a
site or a mail server.

What's pinned: the JSON is § Contract's shape key for key; every pick has exactly two entries, a fault first, the
second a fault or a plain fact, and a business with no fault (or one and nothing true beside it) is left out, not
padded; own-domain beats free-mail and a free-mail address tied only by the page title is never used; MX must be
ok; the three rules spot checks proved false (no contact form, not secure, the phone that differs) are never said;
no batch is made when `outreach suppress ls --json` can't be read; held, pipeline, client, chain and suppressed
businesses never appear; a batched business is held out of
the next batch and the kits; `leads candidates` is unchanged; `--stats` counts; `preview --place --json` is one
object with the URL, for a business with a site of its own.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import datetime as dt  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from importlib.machinery import SourceFileLoader  # noqa: E402
from pathlib import Path  # noqa: E402

import test_leads_preview as tp  # noqa: E402  (its stand-in `site`, `client` and `img`)

HERE = Path(__file__).resolve().parent
LEADS = HERE.parent / "bin" / "leads"
SERVICES = HERE / "fixtures" / "leads-services"
YEAR = dt.date.today().year


def host_of_url(url):
    return re.sub(r"^https?://(?:www\.)?", "", url or "").split("/")[0]

# B89's DDL (client-leads/scripts/emails.py SCHEMA), the columns `leads` reads.
B89_DDL = """
CREATE TABLE emails (place_id TEXT NOT NULL, address TEXT NOT NULL, source TEXT, kind TEXT, why TEXT, how TEXT,
    evidence_url TEXT NOT NULL, page_title TEXT, syntax_ok INTEGER, mx TEXT, mx_hosts TEXT, mx_checked TEXT,
    found TEXT, confidence TEXT, place TEXT, PRIMARY KEY (place_id, address));
CREATE TABLE email_pass (place_id TEXT PRIMARY KEY, crawled TEXT, crawl_status TEXT, crawl_why TEXT, pages TEXT,
    requests INTEGER, seconds REAL, searched TEXT, query TEXT, search_status TEXT, search_why TEXT, rejected TEXT,
    notice TEXT);
CREATE TABLE site_facts (place_id TEXT PRIMARY KEY, url TEXT, final_url TEXT, https INTEGER, viewport INTEGER,
    copyright_year INTEGER, builder TEXT, contact_form INTEGER, phones TEXT, phone_matches INTEGER, checked TEXT,
    evidence TEXT);
"""
OWN = "on the site's own domain, published on their own site"
NAMED = "a free-mail address on their own site, the business named beside it"
TITLED = "a free-mail address on their own site, titled with the business's name"

# id, name, category, locality, address, kind, why, mx, facts {https, viewport, year, phone_matches, phones, url, final, form}
B = [
    ("FX_B01", "Alpine Plumbing", "plumber", "Lehi", "hello@alpineplumbing.example", "own-domain", OWN, "ok",
     dict(viewport=0, year=YEAR - 7)),
    ("FX_B02", "Bonneville Plumbing", "plumber", "Lehi", "bonnevilleplumbing@gmail.com", "free-mail", NAMED, "ok",
     dict(year=YEAR - 6, phone_matches=0, phones=["8015550999"])),
    ("FX_B03", "Cedar Plumbing", "plumber", "Lehi", "info@cedarplumbing.example", "own-domain", OWN, "ok",
     dict(year=YEAR - 1)),
    ("FX_B04", "Delta Plumbing", "plumber", "Lehi", "deltapipes@gmail.com", "free-mail", TITLED, "ok",
     dict(viewport=0, year=YEAR - 8)),
    ("FX_B05", "Echo Plumbing", "plumber", "Lehi", "office@echoplumbing.example", "own-domain", OWN, "none",
     dict(viewport=0, year=YEAR - 8)),
    ("FX_B06", "Falcon Plumbing", "plumber", "Lehi", "office@falconplumbing.example", "own-domain", OWN, "ok",
     dict(year=YEAR - 8, phone_matches=0, phones=["8015550888"],
          url="https://falconplumbing.example/?utm_source=google&utm_medium=gbp")),
    ("FX_B07", "Granite Plumbing", "plumber", "Lehi", "info@graniteplumbing.example", "own-domain", OWN, "ok",
     dict(viewport=0, https=0, url="http://graniteplumbing.example/", final="http://graniteplumbing.example/")),
    ("FX_B08", "Harbor Plumbing", "plumber", "Lehi", "info@harborplumbing.example", "own-domain", OWN, "ok",
     dict(viewport=0, https=0, url="http://harborplumbing.example/", final="http://harborplumbing.example/")),
    ("FX_B09", "Iron Plumbing", "plumber", "Lehi", "info@ironplumbing.example", "own-domain", OWN, "ok",
     dict(viewport=0, year=YEAR - 5)),
    ("FX_B10", "Juniper Plumbing", "plumber", "Lehi", "info@juniperplumbing.example", "own-domain", OWN, "ok",
     dict(viewport=0, year=YEAR - 5)),
    ("FX_B11", "Kestrel Plumbing", "plumber", "Lehi", "owner@kestrelplumbing.example", "own-domain", OWN, "ok",
     dict(viewport=0, year=YEAR - 5)),
    ("FX_B12", "Lark Plumbing", "plumber", "Lehi", "info@larkplumbing.example", "own-domain", OWN, "ok",
     dict(viewport=0, year=YEAR - 5), ),
    ("FX_B13", "Moab Roofing", "roofing", "Lehi", "info@moabroofing.example", "own-domain", OWN, "ok",
     dict(viewport=0, year=YEAR - 5)),
    ("FX_B14", "Nephi Plumbing", "plumber", "Orem", "info@nephiplumbing.example", "own-domain", OWN, "ok",
     dict(viewport=0, year=YEAR - 5)),
    ("FX_B15", "Alpine Plumbing South", "plumber", "Lehi", "hello@alpineplumbing.example", "own-domain", OWN, "ok",
     dict(viewport=0, year=YEAR - 5)),
    ("FX_B16", "Quail Plumbing", "plumber", "Lehi", "info@quailplumbing.example", "own-domain", OWN, "ok",
     dict(year=YEAR - 9, form=0)),
]
# Quail qualifies on the stored facts (© nine years back) but its page now reads "© <then>-<yy>": out on a second look
IN_LEHI_PLUMBERS = {"FX_B01", "FX_B02", "FX_B06", "FX_B07", "FX_B08"}
CONTRACT_TOP = {"batch_id", "date", "segment", "category", "city", "picks"}
CONTRACT_PICK = {"place_id", "name", "category", "segment", "city", "phone", "site_url", "maps_url", "rating",
                 "reviews", "email", "email_kind", "email_evidence", "email_why", "faults",
                 "email_confidence", "email_place"}           # B104: added, never renamed; only `high` is picked
CONTRACT_FAULT = {"key", "kind", "sentence", "evidence"}

FAKE_OUTREACH = '''#!/usr/bin/env python3
import json, os, sys
if sys.argv[1:] == ["suppress", "ls", "--json"] and os.environ.get("FAKE_SUPPRESS"):   # unset: as if no --json yet
    print(os.environ["FAKE_SUPPRESS"])
    sys.exit(0)
print("usage: outreach suppress add|ls", file=sys.stderr)
sys.exit(2)
'''


def page_fixture(path):
    """Each fixture site's home page as a batch re-reads it: the stored year, except Quail's range to this year."""
    pages = {}
    for pid, name, cat, loc, addr, kind, why, mx, f in B:
        dom = addr.split("@")[1] if kind == "own-domain" else f"{pid.lower()}.example"
        home = f.get("final") or f"https://{dom}/"
        yr = f.get("year")
        foot = (f"Copyright © {yr}-{YEAR % 100:02d} {name}" if pid == "FX_B16" else
                f"<footer>&copy; {yr} {name}. All rights reserved.</footer>" if yr else "<footer>Thanks</footer>")
        pages.setdefault(home, f"<html><body><h1>{name}</h1>{foot}</body></html>")
    path.write_text(json.dumps(pages))
    return path


def build_census(path):
    spec = importlib.util.spec_from_file_location("leads_services_build", SERVICES / "build.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    db = m.build(path)
    conn = sqlite3.connect(db)
    conn.executescript(B89_DDL)
    for i, (pid, name, cat, loc, addr, kind, why, mx, f) in enumerate(B):
        dom = addr.split("@")[1] if kind == "own-domain" else f"{pid.lower()}.example"
        home = f.get("final") or f"https://{dom}/"
        conn.execute("""INSERT INTO place_cache (place_id, name, address, phone, website, has_website, rating, reviews,
                        lat, lng, refreshed_at, locality, postal_code, primary_type, types, business_status,
                        google_maps_uri) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (pid, name, f"{200 + i} W Main St, {loc}, UT 84043, USA", f"(801) 555-{1000 + i}",
                      f.get("url") or home, "yes", 4.8, 5 if pid == "FX_B15" else 40 + i, 40.39, -111.85, dt.date.today().isoformat() + "T12:00:00", loc, "84043",
                      "plumber", "[]", "OPERATIONAL", f"https://maps.google.com/?cid={pid}&g_mp=x"))
        conn.execute("""INSERT INTO businesses (place_id, segment, category, categories, city, first_seen, source,
                        presence_class, presence_url, presence_checked, is_chain, chain_override)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (pid, "services", cat, json.dumps([cat]), f"{loc}, Utah", "2026-09-28", "scan_services", "own",
                      f.get("url") or home, "2026-09-28T12:00:00", 1 if pid == "FX_B12" else 0, None))
        conn.execute("INSERT INTO emails VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (pid, addr, "site", kind, why, "mailto", home + "contact", name, 1, mx, "[]", "2026-10-01",
                      "2026-10-01", "high", "read on the listing's own website " + host_of_url(home)))
        pages = [f.get("url") or home, home + "contact-us/"]
        conn.execute("INSERT INTO email_pass (place_id, crawled, crawl_status, pages) VALUES (?,?,?,?)",
                     (pid, "2026-10-01", "ok", json.dumps(pages)))
        conn.execute("INSERT INTO site_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (pid, f.get("url") or home, home, f.get("https", 1), f.get("viewport", 1), f.get("year"), None,
                      f.get("form", 1), json.dumps(f.get("phones") or [f"801555{1000 + i}"]),
                      f.get("phone_matches", 1), "2026-10-01", "{}"))
    conn.commit()
    conn.close()
    return db


def leads_module(env):
    """`leads` as a module with these paths baked in; the process env is put back after, so nothing leaks into the
    suites that run after this one."""
    saved = dict(os.environ)
    os.environ.update(env)
    try:
        spec = importlib.util.spec_from_loader("leads_batch_mod", SourceFileLoader("leads_batch_mod", str(LEADS)))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return m


class BatchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.t = Path(self.tmp.name)
        self.db = build_census(t / "census.db")
        (t / "bin").mkdir()
        for name, body in (("site", tp.FAKE_SITE), ("client", tp.FAKE_CLIENT), ("img", tp.FAKE_IMG),
                           ("outreach", FAKE_OUTREACH)):
            (t / "bin" / name).write_text(body)
            (t / "bin" / name).chmod(0o755)
        (t / "clients" / "kestrel").mkdir(parents=True)
        (t / "clients" / "kestrel" / "NOTES.md").write_text("Owner: Kay (owner@kestrelplumbing.example).\n")
        self.pipeline = t / "pipeline.jsonl"
        self.pipeline.write_text(json.dumps({"ts": "2026-09-30T10:00:00-06:00", "date": "2026-09-30",
                                             "key": "place:FX_B09", "place_id": "FX_B09", "name": "Iron Plumbing",
                                             "outcome": "messaged", "stage": "messaged"}) + "\n")
        self.env = {"LEADS_DB": str(self.db), "LEADS_STATE": str(t / "state"), "LEADS_LEDGER": str(t / "ledger.jsonl"),
                    "LEADS_PIPELINE": str(self.pipeline), "LEADS_GROUPS_LOG": str(t / "groups.md"),
                    "LEADS_PREVIEWS": str(t / "previews"), "LEADS_PREVIEW_HOST": "previews.patchlamp.com",
                    "LEADS_PREVIEW_BIN": str(t / "bin"), "LEADS_IMG_BIN": str(t / "bin" / "img"),
                    "FAKE_SITE_LOG": str(t / "site.jsonl"), "FAKE_IMG_LOG": str(t / "img.jsonl"),
                    "CLAUDE_TOOLS_ENV": str(t / "no-env"), "GOOGLE_MAPS_API_KEY": "", "LEADS_MAIL_ADDRESS": "",
                    "LEADS_SEGMENT": "services", "PROJECTS_DIR": str(t / "projects"),
                    "LEADS_CLIENTS_DIR": str(t / "clients"), "LEADS_OUTREACH_BIN": str(t / "bin" / "outreach"),
                    "OUTREACH_STATE": str(t / "outreach"),
                    "LEADS_PAGE_FIXTURE": str(page_fixture(t / "pages.json")),
                    "FAKE_SUPPRESS": json.dumps([{"value": "juniperplumbing.example", "kind": "domain"}]),
                    "LEADS_KIT_PREVIEWS": ""}

    def tearDown(self):
        self.tmp.cleanup()

    def run_leads(self, *args, env=None):
        e = {**os.environ, **self.env, **(env or {})}
        return subprocess.run([sys.executable, str(LEADS), *args], capture_output=True, text=True, env=e)

    def batch(self, *extra, ok=True, env=None):
        r = self.run_leads("batch", "--segment", "services", "--city", "Lehi", *extra, env=env)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_json_is_the_contract_and_two_faults_each(self):
        b = json.loads(self.batch("--json").stdout)
        self.assertEqual(set(b), CONTRACT_TOP)
        self.assertEqual((b["segment"], b["city"], b["category"]), ("services", "Lehi", "plumber"))
        self.assertRegex(b["batch_id"], r"^\d{4}-\d\d-\d\d-services-lehi-plumber-1$")
        self.assertEqual({p["place_id"] for p in b["picks"]}, IN_LEHI_PLUMBERS)
        for p in b["picks"]:
            self.assertEqual(set(p), CONTRACT_PICK)
            self.assertEqual(len(p["faults"]), 2, p)
            self.assertEqual(p["faults"][0]["kind"], "fault")            # at least one fault, always first
            for f in p["faults"]:
                self.assertEqual(set(f), CONTRACT_FAULT)
                self.assertTrue(f["evidence"])
                self.assertNotRegex(f["sentence"].lower(), r"outdated|unprofessional|old-fashioned|bad|poor")
            self.assertIn(p["email_kind"], ("own-domain", "free-mail"))
            self.assertRegex(p["email_evidence"], r"^https?://")
        by = {p["place_id"]: p for p in b["picks"]}
        self.assertEqual([f["key"] for f in by["FX_B01"]["faults"]], ["old_copyright", "no_viewport"])
        self.assertIn(f"© {YEAR - 7}", by["FX_B01"]["faults"][0]["sentence"])
        self.assertEqual(by["FX_B02"]["email_kind"], "free-mail")
        # the site's phone differs from the listing's and Granite's link is http: neither is said (proved false)
        self.assertEqual([f["key"] for f in by["FX_B02"]["faults"]], ["old_copyright", "google_standing"])
        self.assertEqual([f["key"] for f in by["FX_B07"]["faults"]], ["no_viewport", "google_standing"])
        # one fault and a fact: their Google standing, rounded down so it stays true (47 reviews → "more than 40")
        self.assertEqual([(f["key"], f["kind"]) for f in by["FX_B08"]["faults"]],
                         [("no_viewport", "fault"), ("google_standing", "fact")])
        self.assertEqual(by["FX_B08"]["faults"][1]["sentence"], "you have more than 40 Google reviews, averaging 4.8 stars")
        self.assertEqual([f["key"] for f in by["FX_B06"]["faults"]], ["old_copyright", "google_standing"])

    def test_an_address_that_isnt_high_is_never_in_a_batch_and_is_said_as_call_only(self):
        # B104 (plan 44 § 7): only an address emails.py tied to the place (`high`) is ever written to
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE emails SET confidence = 'low', place = 'nothing ties it to the place (no Utah, no Lehi)' "
                     "WHERE place_id = 'FX_B01'")
        conn.commit()
        conn.close()
        b = json.loads(self.batch("--json", "--no-save").stdout)
        self.assertNotIn("FX_B01", {p["place_id"] for p in b["picks"]})
        self.assertTrue(all(p["email_confidence"] == "high" for p in b["picks"]))
        r = self.batch("--no-save")
        line = next(x for x in r.stdout.splitlines() if "call-only, address unconfirmed" in x)
        self.assertIn("(nothing ties it to the place (no Utah, no Lehi))", line)

    def test_left_out_never_padded(self):
        r = self.batch("--no-save")
        for name in ("Cedar", "Delta", "Echo", "Iron", "Juniper", "Kestrel", "Lark",
                     "Alpine Plumbing South", "Moab", "Nephi"):
            self.assertNotIn(name, r.stdout, name)
        self.assertIn("no fault to name", r.stdout)
        self.assertNotIn("Quail", r.stdout)
        self.assertIn("1 left out on a second look", r.stdout)
        self.assertIn("in the pipeline", r.stdout)
        self.assertIn("suppressed", r.stdout)
        self.assertIn("a client", r.stdout)
        self.assertIn("a chain", r.stdout)
        for line in r.stdout.splitlines():
            if re.match(r"^\d+\. ", line):
                self.assertEqual(line.count(";"), 1, line)       # one line, two faults

    def test_suppression_from_outreach_json(self):
        r = self.batch("--json", "--no-save", env={"FAKE_SUPPRESS": json.dumps(
            [{"value": "hello@alpineplumbing.example", "kind": "address"}, "graniteplumbing.example"])})
        ids = {p["place_id"] for p in json.loads(r.stdout)["picks"]}
        # by address and by domain; and the command's list is the whole list (Juniper isn't on this one)
        self.assertEqual(ids, IN_LEHI_PLUMBERS - {"FX_B01", "FX_B07"} | {"FX_B10"})

    def test_no_batch_without_the_suppression_list(self):
        # `outreach` without --json (today's main), one that isn't there, one that prints junk: a refusal, no file
        for env in ({"FAKE_SUPPRESS": ""}, {"LEADS_OUTREACH_BIN": str(self.t / "bin" / "missing")},
                    {"FAKE_SUPPRESS": "not json"}):
            r = self.batch("--json", ok=False, env=env)
            self.assertNotEqual(r.returncode, 0, env)
            self.assertIn("suppression list can't be read", r.stderr)
            self.assertEqual(r.stdout, "")
            self.assertFalse((self.t / "state" / "batches.jsonl").exists())
        m = leads_module(dict(self.env, FAKE_SUPPRESS=""))
        vals, src = m.suppressed()
        self.assertIsNone(vals)
        self.assertIn("suppress ls --json", src)
        s = self.run_leads("batch", "--stats", env={"FAKE_SUPPRESS": ""})   # sizing still works, and says so
        self.assertEqual(s.returncode, 0, s.stderr)
        self.assertIn("suppressed addresses not subtracted", s.stdout)
        self.assertIn("unreadable", self.run_leads("doctor", env={"FAKE_SUPPRESS": ""}).stdout)

    def test_held_once_batched_and_out_of_the_kits(self):
        before = self.run_leads("candidates", "--segment", "services", "--n", "100").stdout
        b = json.loads(self.batch("--json").stdout)
        self.assertEqual(self.run_leads("candidates", "--segment", "services", "--n", "100").stdout, before)
        again = self.batch("--category", "plumber", ok=False)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn("held", again.stderr)
        log = [json.loads(x) for x in (self.t / "state" / "batches.jsonl").read_text().splitlines()]
        self.assertEqual(set(log[0]["place_ids"]), IN_LEHI_PLUMBERS)
        m = leads_module(self.env)
        self.assertTrue(IN_LEHI_PLUMBERS <= set(m.contacted()))      # the kits' 56-day hold reads it
        last = json.loads(self.run_leads("batch", "--last", "--json").stdout)
        self.assertEqual(last, b)

    def test_no_save_holds_nothing(self):
        self.batch("--no-save")
        self.assertFalse((self.t / "state" / "batches.jsonl").exists())
        self.batch("--no-save")

    def test_other_city_and_trade(self):
        r = self.run_leads("batch", "--segment", "services", "--city", "Orem", "--json", "--no-save")
        self.assertEqual([p["place_id"] for p in json.loads(r.stdout)["picks"]], ["FX_B14"])
        r = self.run_leads("batch", "--segment", "services", "--city", "Lehi", "--category", "roofing", "--json",
                           "--no-save")
        self.assertEqual([p["place_id"] for p in json.loads(r.stdout)["picks"]], ["FX_B13"])
        r = self.run_leads("batch", "--segment", "services", "--json", "--no-save")      # one trade, the corridor
        b = json.loads(r.stdout)
        self.assertEqual((b["city"], b["category"]), ("corridor", "plumber"))
        self.assertRegex(b["batch_id"], r"-services-corridor-plumber-1$")
        self.assertEqual({p["place_id"] for p in b["picks"]}, IN_LEHI_PLUMBERS | {"FX_B14"})

    def test_site_faults_only_on_their_own_home_page(self):
        m = leads_module(self.env)
        ok = m.own_home_page
        self.assertTrue(ok("https://alpine.example/?utm_source=google", "https://www.alpine.example/"))
        self.assertTrue(ok("http://alpine.example/home", None))
        self.assertFalse(ok("https://planetbeach.com/spa/layton/", "https://www.sol-spa.net/spa-locator"))
        self.assertFalse(ok("https://www.discoverstrength.com/draper", "https://www.discoverstrength.com/draper"))
        self.assertFalse(ok("https://old.example/", "https://new.example/"))

    def test_copyright_read_again(self):
        m = leads_module(self.env)
        for html, want in (("© 2019-26 Bullett", None), ("Copyright 2019 – 2026", None), ("© 2019", 2019),
                           ("&copy; 2018 a &copy; 2021 b", 2021),
                           ("© <script>document.write(new Date().getFullYear())</script> 2015", None),
                           ("no line at all", None)):
            y, _ = m._copyright_in(html)
            self.assertEqual(y if (y and y <= YEAR - 3) else None, want, html)

    def test_stats(self):
        r = self.run_leads("batch", "--stats", "--segment", "services", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = json.loads(r.stdout)
        self.assertEqual(s["with_address"], 14)                      # Delta (titled) and Echo (no MX) aren't
        # qualify: the six Lehi plumbers, Moab, Nephi; not Iron (pipeline), Juniper (suppressed), Kestrel (client),
        # Lark (chain), Alpine South (Alpine's inbox), Cedar (no fault)
        self.assertEqual(s["qualify"], 8)
        self.assertEqual(s["two_faults"], 3)                          # Alpine, Moab, Nephi
        self.assertEqual(s["with_a_fault"], 13)                       # all with an address but Cedar
        for dropped in ("no_contact_form", "no_https", "phone_mismatch"):
            self.assertNotIn(dropped, s["keys"])
        self.assertEqual({t["category"]: t["n"] for t in s["trades"]}, {"plumber": 7, "roofing": 1})
        self.assertFalse((self.t / "state" / "batches.jsonl").exists())
        self.assertIn("qualify", self.run_leads("batch", "--stats").stdout)

    def test_a_website_on_three_listings_is_a_chain(self):
        conn = sqlite3.connect(self.db)
        for i in (1, 2):                                             # Quail's site on two more listings
            conn.execute("INSERT INTO place_cache (place_id, name, website) VALUES (?,?,?)",
                         (f"FX_Q{i}", f"Quail Plumbing {i}", "https://www.quailplumbing.example/locations"))
        conn.commit()
        conn.close()
        r = self.batch("--json", "--no-save")
        self.assertNotIn("FX_B16", {p["place_id"] for p in json.loads(r.stdout)["picks"]})
        self.assertIn("a chain by its website", self.batch("--no-save").stdout)

    def test_listing_rules_reused(self):
        m = leads_module(self.env)
        c = {"place_id": "FX_B03", "segment": "services", "category": "plumber", "reviews": 40, "rating": 4.8,
             "presence_class": "own", "website": "https://cedarplumbing.example/",
             "google_maps_uri": "https://maps.google.com/?cid=1"}
        details = {"websiteUri": "https://cedarplumbing.example/", "formattedAddress": "200 W Main St, Lehi",
                   "photos": [{}, {}], "nationalPhoneNumber": "(801) 555-1003", "userRatingCount": 40,
                   "reviews": [{"rating": 2, "relativePublishTimeDescription": "3 weeks ago",
                                "publishTime": "2026-09-10T00:00:00Z"}]}
        items = m.listing_fault_items(c, details, dt.date(2026, 10, 1))
        said = {i["key"]: i["sentence"] for i in items}
        self.assertEqual(said["no_hours"], "your Google listing shows no hours")
        self.assertEqual(said["few_photos"], "your Google listing has only 2 photos")
        self.assertEqual(said["low_review"], "there's a 2★ review on your Google listing from 3 weeks ago")
        self.assertNotIn("street_address", said)                     # a shop's address is not a fault
        details["userRatingCount"] = 900
        self.assertNotIn("low_review", {i["key"] for i in m.listing_fault_items(c, details, dt.date(2026, 10, 1))})

    def test_preview_by_place_json(self):
        r = self.run_leads("preview", "--place", "FX_B01", "--json", "--hero", "none")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)                                   # stdout is exactly one object
        self.assertTrue(out["ok"])
        self.assertEqual(out["place_id"], "FX_B01")
        self.assertEqual(out["url"], f"https://previews.patchlamp.com/{out['slug']}/")
        self.assertTrue(out["published"])
        self.assertIn("alpine-plumbing", out["slug"])
        again = json.loads(self.run_leads("preview", "--place", "FX_B01", "--json", "--hero", "none").stdout)
        self.assertEqual(again["url"], out["url"])                   # a link already sent keeps working
        r = self.run_leads("preview", "--place", "NOPE", "--json", "--hero", "none")
        self.assertEqual(r.returncode, 2)
        self.assertFalse(json.loads(r.stdout)["ok"])

    def test_doctor_has_the_batch(self):
        r = self.run_leads("doctor")
        self.assertIn("batch: ", r.stdout)
        self.assertIn("suppression:", r.stdout)
        self.assertIn("clients kept out: 1 addresses", r.stdout)


# ---- B99: the faults `site_checks` stores, said in code (client-leads/scripts/site_checks.py, spot-checks/b99-*.md) ----
SITE_CHECKS_DDL = """
CREATE TABLE site_checks (place_id TEXT PRIMARY KEY, url TEXT, checked TEXT, form TEXT, form_pages TEXT,
    form_evidence TEXT, https TEXT, https_url TEXT, https_why TEXT, psi_score INTEGER, psi_date TEXT, psi_why TEXT,
    psi_evidence TEXT, sideways INTEGER, sideways_evidence TEXT, broken_images INTEGER, broken_images_evidence TEXT,
    broken_links INTEGER, links_checked INTEGER, broken_links_evidence TEXT, render_why TEXT, requests INTEGER,
    seconds REAL);
"""
TODAY = dt.date.today()
FRESH = (TODAY - dt.timedelta(days=2)).isoformat() + "T21:00:00"
STALE = (TODAY - dt.timedelta(days=45)).isoformat() + "T21:00:00"


def links_ev(page, *links):
    return json.dumps({"page": page, "links": [{"href": h, "text": t, "status": 404} for h, t in links]})


# id, name, listing website, checks {column: value}, copyright year on the site
C = [
    ("FX_E01", "Arc Electric", "http://arcelectric.example/",
     dict(https="fails", https_url="https://arcelectric.example/",
          https_why="ERR_CERT_COMMON_NAME_INVALID in Chromium; python: tls",
          broken_links=1, broken_links_evidence=links_ev("http://arcelectric.example/",
                                                         ("http://arcelectric.example/about", "ABOUT"))), None),
    ("FX_E02", "Bolt Electric", "https://www.boltelectric.example/",
     dict(https="fails", https_url="https://www.boltelectric.example/",
          https_why="ERR_SSL_PROTOCOL_ERROR in Chromium; python: tls"), YEAR - 6),
    ("FX_E03", "Circuit Electric", "https://circuitelectric.example/",
     dict(broken_links=1, broken_links_evidence=links_ev("https://circuitelectric.example/",
                                                         ("https://circuitelectric.example/home", "(801)"))), None),
    ("FX_E04", "Dynamo Electric", "https://dynamoelectric.example/",
     dict(broken_links=1, broken_links_evidence=links_ev("https://dynamoelectric.example/",
                                                         ("https://dynamoelectric.example/team", "Our Team"))), None),
    ("FX_E05", "Edison Electric", "https://edisonelectric.example/",
     dict(sideways=120, sideways_evidence=json.dumps({"vw": 390, "sw": 510, "scrollX": 120}), broken_images=1,
          broken_images_evidence=json.dumps({"images": [{"src": "https://cdn.example/e.jpg", "status": 404}]}),
          psi_score=34, psi_date=TODAY.isoformat()), None),
    ("FX_E06", "Flux Electric", "https://fluxelectric.example/",
     dict(broken_links=1, broken_links_evidence=links_ev("https://fluxelectric.example/",
                                                         ("https://fluxelectric.example/gallery/1", "")),
          https="fails", https_url="https://fluxelectric.example/", https_why="x", checked=STALE), None),
    ("FX_E07", "Grid Electric", "https://gridelectric.example/",
     dict(https="to-http", https_url="https://gridelectric.example/",
          https_why="https://gridelectric.example/ redirects to http://gridelectric.example/"), None),
    ("FX_E08", "Hertz Electric", "https://hertzelectric.example/locations/draper",
     dict(https="fails", https_url="https://hertzelectric.example/", https_why="nothing answers on 443",
          broken_links=1, broken_links_evidence=links_ev("https://hertzelectric.example/locations/draper",
                                                         ("https://hertzelectric.example/x", "Contact"))), None),
]
STATUS = {"https://arcelectric.example/": "tls", "http://arcelectric.example/about": 404,
          "https://www.boltelectric.example/": "tls", "https://circuitelectric.example/home": 410,
          "https://dynamoelectric.example/team": 200,               # fixed since the crawl: not said
          "https://cdn.example/e.jpg": 404, "https://gridelectric.example/": "http",
          "https://hertzelectric.example/": "refused", "https://hertzelectric.example/x": 404}


def add_check_businesses(db, pages_json):
    conn = sqlite3.connect(db)
    conn.executescript(SITE_CHECKS_DDL)
    pages = json.loads(Path(pages_json).read_text())
    for i, (pid, name, site, chk, yr) in enumerate(C):
        dom = host = re.sub(r"^https?://(www\.)?", "", site).split("/")[0]
        conn.execute("""INSERT INTO place_cache (place_id, name, address, phone, website, has_website, rating, reviews,
                        lat, lng, refreshed_at, locality, postal_code, primary_type, types, business_status,
                        google_maps_uri) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (pid, name, f"{300 + i} S State St, Draper, UT 84020, USA", f"(801) 555-{2000 + i}", site, "yes",
                      4.8, 50 + i, 40.52, -111.86, TODAY.isoformat() + "T12:00:00", "Draper", "84020", "electrician",
                      "[]", "OPERATIONAL", f"https://maps.google.com/?cid={pid}"))
        conn.execute("""INSERT INTO businesses (place_id, segment, category, categories, city, first_seen, source,
                        presence_class, presence_url, presence_checked, is_chain, chain_override)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (pid, "services", "electrician", '["electrician"]', "Draper, Utah", "2026-09-28", "scan",
                      "own", site, "2026-09-28T12:00:00", 0, None))
        conn.execute("INSERT INTO emails VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (pid, f"office@{dom}", "site", "own-domain", OWN, "mailto", site, name, 1, "ok", "[]",
                      "2026-10-01", "2026-10-01", "high", f"read on the listing's own website {dom}"))
        conn.execute("INSERT INTO site_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (pid, site, site, 1, 1, yr, None, 1, "[]", 1, "2026-10-01", "{}"))
        pages[site] = f"<footer>&copy; {yr} {name}</footer>" if yr else "<footer>hi</footer>"
        row = dict(place_id=pid, url=site, checked=FRESH, form="none", https="serves", sideways=0, broken_images=0,
                   broken_links=0)
        row.update(chk)
        cols = ",".join(row)
        conn.execute(f"INSERT INTO site_checks ({cols}) VALUES ({','.join('?' * len(row))})", list(row.values()))
    conn.commit()
    conn.close()
    Path(pages_json).write_text(json.dumps(pages))


class CheckFaultsTest(unittest.TestCase):
    """B99's sentences: the two proven faults said, re-checked the day of the batch; the waiting ones never said
    but counted; "no form" never a fault; a pick still exactly two entries, a fault first."""
    setUp0, tearDown, run_leads = BatchTest.setUp, BatchTest.tearDown, BatchTest.run_leads

    def setUp(self):
        self.setUp0()
        add_check_businesses(self.db, self.env["LEADS_PAGE_FIXTURE"])
        st = self.t / "status.json"
        st.write_text(json.dumps(STATUS))
        self.env["LEADS_STATUS_FIXTURE"] = str(st)

    def draper(self, *extra, env=None):
        r = self.run_leads("batch", "--segment", "services", "--city", "Draper", "--category", "electrician",
                           "--json", "--no-save", *extra, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return {p["place_id"]: p for p in json.loads(r.stdout)["picks"]}

    def test_the_sentences(self):
        by = self.draper()
        self.assertEqual(set(by), {"FX_E01", "FX_E02", "FX_E03", "FX_E07", "FX_E08"})
        for p in by.values():
            self.assertEqual(len(p["faults"]), 2, p)
            self.assertEqual(p["faults"][0]["kind"], "fault")
            for f in p["faults"]:
                self.assertEqual(set(f), CONTRACT_FAULT)
                self.assertNotRegex(f["sentence"], r"[.!?]$|https?://|\.example")   # no link, one sentence
        arc = by["FX_E01"]["faults"]
        self.assertEqual([f["key"] for f in arc], ["https_fails", "broken_link"])   # the order of preference
        self.assertEqual(arc[0]["sentence"], 'the website on your Google listing has no working secure (https) '
                                             'version, so Chrome marks it "Not secure"')
        self.assertIn("https://arcelectric.example/", arc[0]["evidence"])
        self.assertIn(f"checked {FRESH[:10]}", arc[0]["evidence"])
        self.assertIn(f"asked again {TODAY.isoformat()}: tls", arc[0]["evidence"])
        self.assertEqual(arc[1]["sentence"], "the \"About\" link on your site's home page goes to a page that "
                                             "isn't there")
        self.assertIn("http://arcelectric.example/about answered 404", arc[1]["evidence"])
        bolt = by["FX_E02"]["faults"]            # the listing links the https address: Chrome's error page
        self.assertEqual([f["key"] for f in bolt], ["https_fails", "old_copyright"])
        self.assertEqual(bolt[0]["sentence"],
                         "the website link on your Google listing opens a browser error page instead of your site")
        circ = by["FX_E03"]["faults"]            # "(801)" isn't quoted: a count instead, and a fact beside it
        self.assertEqual([(f["key"], f["kind"]) for f in circ], [("broken_link", "fault"), ("google_standing", "fact")])
        self.assertEqual(circ[0]["sentence"], "a link on your site's home page goes to a page that isn't there")
        grid = by["FX_E07"]["faults"]            # https sends them to http: it loads, marked
        self.assertIn('"Not secure"', grid[0]["sentence"])
        hertz = by["FX_E08"]["faults"]           # a location page: its links aren't "your site", the listing link is
        self.assertEqual([f["key"] for f in hertz], ["https_fails", "google_standing"])

    def test_left_out(self):
        r = self.run_leads("batch", "--segment", "services", "--city", "Draper", "--category", "electrician",
                           "--no-save")
        self.assertEqual(r.returncode, 0, r.stderr)
        for name in ("Dynamo", "Edison", "Flux"):
            self.assertNotIn(name, r.stdout)
        self.assertIn("1 left out on a second look", r.stdout)      # Dynamo's link answers now

    def test_nothing_rechecked_is_said_when_reads_are_off(self):
        env = {"LEADS_STATUS_FIXTURE": str(self.t / "missing.json")}
        r = self.run_leads("batch", "--segment", "services", "--city", "Draper", "--category", "electrician",
                           "--json", "--no-save", env=env)
        if r.returncode == 0:
            for p in json.loads(r.stdout)["picks"]:
                for f in p["faults"]:
                    self.assertNotIn(f["key"], ("https_fails", "broken_link"))
        else:
            self.assertIn("second look", r.stderr)

    def test_waiting_faults_are_never_said(self):
        m = leads_module(self.env)
        self.assertEqual(m.CHECK_FAULTS_PROVEN, ("https_fails", "broken_link"))
        for k in ("sideways", "broken_image", "psi_poor", "form_none", "no_contact_form"):
            self.assertNotIn(k, m.CHECK_FAULTS_PROVEN)
        c = {"website": "https://edisonelectric.example/", "checks": {
            "url": "https://edisonelectric.example/", "checked": FRESH, "form": "none", "sideways": 120,
            "sideways_evidence": json.dumps({"vw": 390, "sw": 510}), "broken_images": 1,
            "broken_images_evidence": json.dumps({"images": [{"src": "https://cdn.example/e.jpg", "status": 404}]}),
            "psi_score": 34, "psi_date": TODAY.isoformat()}}
        said = {i["key"]: i for i in m.check_fault_items(c, TODAY)}
        self.assertEqual(set(said), {"sideways", "broken_image", "psi_poor"})   # written, and form isn't a fault
        self.assertEqual(said["sideways"]["sentence"],
                         "on a phone, your site's home page slides sideways, part of it off the screen")
        self.assertEqual(said["broken_image"]["sentence"], "on a phone, an image on your site's home page doesn't load")
        self.assertEqual(said["psi_poor"]["sentence"], "Google's PageSpeed test scored your site's home page 34 out "
                                                       f"of 100 on a phone on {TODAY:%B} {TODAY.day}")
        self.assertEqual(m.facts_packet(dict(c, segment="services"), None, TODAY), [])
        c["checks"]["psi_score"] = 50                                # 50 is not Google's poor band
        self.assertNotIn("psi_poor", {i["key"] for i in m.check_fault_items(c, TODAY)})

    def test_stale_and_missing_rows_say_nothing(self):
        m = leads_module(self.env)
        row = {"url": "https://x.example/", "https": "fails", "https_url": "https://x.example/", "https_why": "x",
               "broken_links": 1, "broken_links_evidence": links_ev("https://x.example/", ("https://x.example/a", "A b"))}
        c = {"website": "https://x.example/", "checks": dict(row, checked=STALE)}
        self.assertEqual(m.check_fault_items(c, TODAY), [])
        self.assertEqual(m.check_fault_items({"website": "https://x.example/", "checks": None}, TODAY), [])
        edge = (TODAY - dt.timedelta(days=m.SITE_CHECK_MAX_DAYS)).isoformat()
        self.assertEqual(len(m.check_fault_items(dict(c, checks=dict(row, checked=edge)), TODAY)), 2)
        # an https address on another host than the listing's is not said of their listing
        self.assertEqual(m.check_fault_items({"website": "https://other.example/",
                                              "checks": dict(row, checked=FRESH, broken_links=0)}, TODAY), [])

    def test_quotable(self):
        m = leads_module(self.env)
        for text, want in (("About", "About"), ("ABOUT", "About"), ("Terms & Conditons", "Terms & Conditons"),
                           ("URBAN ARROW BUY NOW", "Urban Arrow Buy Now"), ("Contact Us", "Contact Us"),
                           ("(801)", None), ("", None), ("0 items", None), ("SEE MORE...", None),
                           ("LEARN MORE", None), ("Read more", None), ("Click here", None), ("Shop Now", None),
                           ("www.festivalderua.com", None), ("Click here for Tea Party Info & Reservat", None),
                           ("Entrusting anyone with your celebration", None), ("<b>x</b>", None)):
            self.assertEqual(m.quotable(text), want, text)

    def test_recheck(self):
        m = leads_module(self.env)
        f = {"key": "broken_link", "sentence": "s", "evidence": "e", "recheck": {
            "kind": "links", "page": "https://x.example/", "on": "2026-10-01",
            "links": [{"href": "https://dynamoelectric.example/team", "text": "Our Team", "status": 404},
                      {"href": "https://circuitelectric.example/home", "text": "(801)", "status": 404},
                      {"href": "http://arcelectric.example/about", "text": "About", "status": 404}]}}
        saved = dict(os.environ)
        os.environ["LEADS_STATUS_FIXTURE"] = self.env["LEADS_STATUS_FIXTURE"]
        try:
            g = m.recheck(f, TODAY)
            self.assertEqual(g["sentence"], "the \"About\" link on your site's home page goes to a page that "
                                            "isn't there")
            self.assertNotIn("dynamoelectric", g["evidence"])        # it answers 200 now: not part of what's said
            h = m.recheck({"key": "https_fails", "evidence": "e", "recheck": {
                "kind": "https", "url": "https://dynamoelectric.example/team", "listed": ""}}, TODAY)
            self.assertIsNone(h)                                      # serves now: dropped
            self.assertEqual(m.ask_again("https://never.example/", TODAY), "unsure")
            # a 404 that shows a whole page (Nepali Chulo's Squarespace shows its About page) is not a broken link
            st = json.loads(Path(os.environ["LEADS_STATUS_FIXTURE"]).read_text())
            st["https://shown.example/menu"] = "404-page"
            Path(os.environ["LEADS_STATUS_FIXTURE"]).write_text(json.dumps(st))
            self.assertIsNone(m.recheck(dict(f, recheck=dict(f["recheck"], links=[
                {"href": "https://shown.example/menu", "text": "Menu", "status": 404}])), TODAY))
        finally:
            os.environ.clear()
            os.environ.update(saved)

    def test_a_404_page_must_say_so(self):
        m = leads_module(self.env)
        for body in ("<title>Page not found | Alta Air</title>", "<h1>404</h1><p>Oops</p>",
                     "<p>We couldn&#39;t find the page you were looking for.</p>",
                     "<div>4 04</div><p>The page you are looking for<br>can not be found</p>",
                     "<p>Sorry, but the page you are trying to view does not exist.</p>"):
            self.assertTrue(m.reads_gone(body), body)
        for body in ("<title>About — Nepali Chulo</title><p>Chulo is a traditional Nepali wood stove</p>"
                     "<p>801 987-8404, UT 84120</p>",
                     "", "<script>var e = 'not found 404';</script><p>Our menu</p>"):
            self.assertFalse(m.reads_gone(body), body)

    def test_stats_counts_the_waiting(self):
        r = self.run_leads("batch", "--stats", "--segment", "services", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        s = json.loads(r.stdout)
        self.assertEqual(s["faults_on"], ["https_fails", "broken_link"])
        self.assertEqual(s["site_checks"], len(C))
        self.assertEqual(s["keys"]["https_fails"], 4)                 # Arc, Bolt, Grid, Hertz (Flux's is stale)
        self.assertEqual(s["keys"]["broken_link"], 3)                 # Arc, Circuit, Dynamo (stored; asked again later)
        self.assertEqual(s["waiting"]["sideways"], {"true_of": 1, "would_add": 1})       # Edison, alone
        self.assertEqual(s["waiting"]["broken_image"], {"true_of": 1, "would_add": 1})
        self.assertEqual(s["waiting"]["psi_poor"], {"true_of": 1, "would_add": 1})
        self.assertNotIn("form_none", s["keys"])
        txt = self.run_leads("batch", "--stats", "--segment", "services").stdout
        self.assertIn("sideways 1 (waiting)", txt)
        self.assertIn("Waiting on thirty spot checks, never said", txt)


if __name__ == "__main__":
    unittest.main()
