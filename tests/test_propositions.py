"""Six propositions, six letter sets (ROADMAP B135, plan ~/projects/plans/55-autonomous-acquisition.md § 1.1, § 5.6).

    python3 -m unittest tests.test_propositions   (from claude-tools/)

Offline. What's pinned:
  - the venture's rules (ventures/patchlamp/propositions.py): the order P0, P1, P2, P3, P4, P5; P6 dealt from P5's
    pool by sha256("E1:"+place_id), stable and about even on a fixture pool of 2,000; the tooling signals change
    nothing (VISION § Decided "Autonomous acquisition" #13); a vendor's name with a domain in it is never said;
  - the engine reads them through lib/venture.py only (a venture with no file has none; another venture's file is
    its own);
  - `leads batch --stats --json` counts every proposition; `leads batch --proposition P4` picks only P4, each with
    the builder and one fact, every one with its source; the letters `outreach send --dry-run` renders from that
    batch say nothing that isn't the approved text or a traced fact (the trace test);
  - `outreach status --by proposition` has a row per proposition and E1's two arms side by side, too few to decide
    under a hundred delivered; a P5/P6 send carries its proposition and arm on the send row and the pipeline line,
    and sits outside the AI-line test;
  - the twelve letters are the picked text, verbatim.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent / "lib"))

import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

import venture  # noqa: E402
import test_leads_batch as tlb  # noqa: E402
import test_outreach_batch as tob  # noqa: E402

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
LEADS = TOOLS / "bin" / "leads"
OUTREACH = TOOLS / "bin" / "outreach"
TEMPLATES = TOOLS / "templates" / "outreach"
PICKED = Path.home() / "projects" / "marketing" / "copy" / "2026-10-08-proposition-letters.picked.json"


def props():
    venture._cache.clear()
    return venture.venture("patchlamp").propositions()


def prospect(**kw):
    p = {"place_id": "ChIJx", "excluded": None, "presence": "own", "own_home": True, "host": None, "packet": [],
         "faults": [], "signals": [],
         "facts": [{"key": "google_standing", "sentence": "you have more than 40 Google reviews, averaging 4.8 stars",
                    "evidence": "https://maps.google.com/?cid=1 (census read 2026-10-01: 44 reviews, 4.8)"},
                   {"key": "phone_matches", "sentence": "the phone number on your site matches your Google listing",
                    "evidence": "https://x.example/ (site read 2026-10-01)"}]}
    p.update(kw)
    return p


def host(vendor, kind, says, status="200"):
    return {"vendor": vendor, "kind": kind, "says": says, "status": status, "url": "https://x.example/",
            "why": "cname", "checked": "2026-10-01T00:00:00"}


class VentureRules(unittest.TestCase):
    def setUp(self):
        self.P = props()

    def test_the_order(self):
        c = self.P.classify
        self.assertEqual(c(prospect(excluded="a chain", packet=[1, 2])), "P0")
        self.assertEqual(c(prospect(packet=[1, 2], presence="dead")), "P1")
        self.assertEqual(c(prospect(presence="none")), "P2")
        self.assertEqual(c(prospect(host=host("hibu", "agency", "Hibu"))), "P3")
        self.assertEqual(c(prospect(host=host("duda", "builder", "Duda"))), "P3")
        self.assertEqual(c(prospect(host=host("agency:x.example", "agency", "Walt & Gordon"))), "P3")
        self.assertEqual(c(prospect(host=host("wix", "builder", "Wix"), faults=["old_copyright"])), "P4")
        self.assertEqual(c(prospect(host=host("jobber", "builder", "Jobber"))), "P5")       # Jobber made it, not them
        self.assertEqual(c(prospect(host=host("wordpress", "wordpress", "WordPress"))), "P5")
        self.assertEqual(c(prospect(faults=["no_viewport"])), "P0")      # a fault, nothing else true: not "fine"
        self.assertEqual(c(prospect(own_home=False)), "P0")
        self.assertEqual(c(prospect(host=host("wix", "builder", "Wix", status="nodns"))), "P0")

    def test_e1_deals_p5_evenly_and_stably_and_nothing_else(self):
        pool = [f"ChIJfixture{i:06d}" for i in range(2000)]
        arms = [self.P.deal(pid, "P5") for pid in pool]
        self.assertEqual({a[1] for a in arms}, {"E1"})
        share = sum(a[0] == "P6" for a in arms) / len(arms)
        self.assertTrue(0.46 <= share <= 0.54, share)
        self.assertEqual(arms, [self.P.deal(pid, "P5") for pid in pool])
        for pid, (prop, exp, arm) in zip(pool, arms):
            self.assertEqual(prop, arm)
            import hashlib
            self.assertEqual(arm, ("P5", "P6")[int(hashlib.sha256(f"E1:{pid}".encode()).hexdigest()[:8], 16) % 2])
        for prop in ("P1", "P3", "P4", "P2", "P0"):
            self.assertEqual(self.P.deal("ChIJfixture000001", prop), (prop, None, None))
        e = self.P.EXPERIMENTS["E1"]
        for k in ("population", "varied", "arms", "deal", "primary_endpoint", "floor_delivered", "kill_rule",
                  "decision_owner"):
            self.assertIn(k, e)

    def test_signals_are_used_for_nothing(self):
        sigs = [{"signal": "booking_widget", "value": "calendly", "evidence": "x"},
                {"signal": "ai_receptionist", "value": "y", "evidence": "x"},
                {"signal": "field_service", "value": "jobber", "evidence": "x"}]
        for pid in (f"ChIJsig{i}" for i in range(200)):
            for h in (None, host("wix", "builder", "Wix"), host("hibu", "agency", "Hibu")):
                bare, rich = prospect(place_id=pid, host=h), prospect(place_id=pid, host=h, signals=sigs)
                a, b = self.P.classify(bare), self.P.classify(rich)
                self.assertEqual(a, b)
                self.assertEqual(self.P.deal(pid, a), self.P.deal(pid, b))
                self.assertEqual(self.P.letter(a, bare), self.P.letter(b, rich))

    def test_letter_facts_carry_their_source_and_a_domain_is_never_said(self):
        got = self.P.letter("P4", prospect(host=host("wix", "builder", "Wix")))
        self.assertEqual([g["slot"] for g in got], ["builder", "fact"])
        self.assertEqual(got[0]["sentence"], "Wix")
        self.assertTrue(all(g["evidence"] for g in got))
        self.assertEqual([g["slot"] for g in self.P.letter("P5", prospect())], ["fact_one", "fact_two"])
        self.assertEqual(self.P.letter("P5", prospect(facts=prospect()["facts"][:1])), [])
        self.assertEqual(self.P.letter("P3", prospect(host=host("webcom", "agency", "Network Solutions (Web.com)"))), [])
        self.assertEqual(self.P.letter("P1", prospect()), [])

    def test_the_engine_reads_them_through_the_venture_only(self):
        venture._cache.clear()
        self.assertIsNone(venture.load(HERE / "fixtures" / "ventures" / "example" / "venture.toml").propositions())
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "other"
            d.mkdir()
            shutil.copy(HERE / "fixtures" / "ventures" / "example" / "venture.toml", d / "venture.toml")
            (d / "propositions.py").write_text(
                "PROPOSITIONS = {'Q1': {'label': 'their own', 'lane': 'email', 'packet': 'slots', "
                "'letters': ('q1-first', 'q1-second', 'q1-third'), 'slots': ('fact',), 'ai_test': True}}\n"
                "EXPERIMENTS = {}\n"
                "def classify(p): return 'Q1'\n"
                "def deal(pid, prop): return prop, None, None\n"
                "def letter(prop, p): return []\n")
            m = venture.load(d / "venture.toml").propositions()
            self.assertEqual(list(m.PROPOSITIONS), ["Q1"])
            (d / "propositions.py").write_text("PROPOSITIONS = {}\n")
            with self.assertRaises(venture.VentureError):
                venture.load(d / "venture.toml").propositions()


class TheLetters(unittest.TestCase):
    def test_installed_verbatim(self):
        if not PICKED.exists():
            self.skipTest(f"{PICKED} isn't on this machine")
        picked = json.loads(PICKED.read_text())
        for p in ("p3", "p4", "p5", "p6"):
            for t in ("first", "second", "third"):
                raw = (TEMPLATES / f"{p}-{t}.md").read_text()
                body = "\n".join(l for l in raw.splitlines() if not l.startswith("#")).strip("\n")
                self.assertEqual(body, picked[p][t].strip("\n"), f"{p}-{t}")

    def test_every_proposition_with_letters_names_installed_templates(self):
        for k, v in props().PROPOSITIONS.items():
            for n in v.get("letters") or ():
                self.assertTrue((TEMPLATES / f"{n}.md").exists(), n)


# ---- the census: the batch fixture plus businesses for every proposition -----------------------------------

HOSTS_DDL = """CREATE TABLE hosts (place_id TEXT PRIMARY KEY, vendor TEXT, evidence TEXT, status TEXT, checked TEXT,
    url TEXT, kind TEXT);"""
PRICES_MD = """# prices

| vendor | says | kind | price | from | to | page | brief | note |
|---|---|---|---|---|---|---|---|---|
| hibu | Hibu | agency | reported | 449 | 1500 | https://x.example/ | b | n |
| wix | Wix | builder | published | 17 | 159 | https://x.example/ | b | n |
| squarespace | Squarespace | builder | published | 16 | 52 | https://x.example/ | b | n |
| wordpress | WordPress | wordpress | free |  |  | https://x.example/ | b | n |
"""
YEAR = tlb.YEAR
# id, name, locality, vendor, kind, presence, email (None for no address), reviews
EXTRA = [("FX_P4A", "Aspen Plumbing", "Lehi", "wix", "builder", "own", "info@aspenplumbing.example", 61),
         ("FX_P4B", "Birch Plumbing", "Lehi", "squarespace", "builder", "own", "info@birchplumbing.example", 72),
         ("FX_P4C", "Cove Plumbing", "Lehi", "wix", "builder", "own", "info@coveplumbing.example", 83),
         ("FX_P3A", "Dune Plumbing", "Lehi", "hibu", "agency", "own", "info@duneplumbing.example", 94)]
EXTRA += [(f"FX_P5{i:02d}", f"Pine {i} Plumbing", "Lehi", "wordpress", "wordpress", "own",
           f"office@pine{i}plumbing.example", 50 + i) for i in range(12)]
EXTRA += [("FX_P2A", "Elk Plumbing", "Lehi", None, None, "none", None, 30)]


def build_census(path):
    db = tlb.build_census(path)
    conn = sqlite3.connect(db)
    conn.executescript(HOSTS_DDL)
    for i, (pid, name, loc, vendor, kind, presence, addr, reviews) in enumerate(EXTRA):
        dom = addr.split("@")[1] if addr else None
        home = f"https://{dom}/" if dom else ""
        conn.execute("""INSERT INTO place_cache (place_id, name, address, phone, website, has_website, rating, reviews,
                        lat, lng, refreshed_at, locality, postal_code, primary_type, types, business_status,
                        google_maps_uri) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (pid, name, f"{500 + i} N Center St, {loc}, UT 84043, USA", f"(801) 555-{3000 + i}", home,
                      "yes" if home else "no", 4.9, reviews, 40.39, -111.85, tlb.dt.date.today().isoformat() + "T12:00:00",
                      loc, "84043", "plumber", "[]", "OPERATIONAL", f"https://maps.google.com/?cid={pid}"))
        conn.execute("""INSERT INTO businesses (place_id, segment, category, categories, city, first_seen, source,
                        presence_class, presence_url, presence_checked, is_chain, chain_override)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (pid, "services", "plumber", '["plumber"]', f"{loc}, Utah", "2026-09-28", "scan_services",
                      presence, home or None, "2026-09-28T12:00:00", 0, None))
        if vendor:
            conn.execute("INSERT INTO hosts VALUES (?,?,?,?,?,?,?)",
                         (pid, vendor, json.dumps({"why": f"generator {vendor}"}), "200", "2026-10-01T00:00:00", home,
                          kind))
        if not addr:
            continue
        conn.execute("INSERT INTO emails VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (pid, addr, "site", "own-domain", tlb.OWN, "mailto", home + "contact", name, 1, "ok", "[]",
                      "2026-10-01", "2026-10-01", "high", "read on the listing's own website " + dom))
        conn.execute("INSERT INTO email_pass (place_id, crawled, crawl_status, pages) VALUES (?,?,?,?)",
                     (pid, "2026-10-01", "ok", json.dumps([home])))
        conn.execute("INSERT INTO site_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                     (pid, home, home, 1, 1, YEAR, None, 1, json.dumps([f"801555{3000 + i}"]), 1,
                      tlb.dt.date.today().isoformat(), "{}"))
    conn.commit()
    conn.close()
    return db


class LeadsByProposition(unittest.TestCase):
    run_leads, batch, tearDown = tlb.BatchTest.run_leads, tlb.BatchTest.batch, tlb.BatchTest.tearDown

    def setUp(self):
        tlb.BatchTest.setUp(self)
        self.db = build_census(self.t / "census2.db")
        (self.t / "prices.md").write_text(PRICES_MD)
        pages = json.loads(Path(self.env["LEADS_PAGE_FIXTURE"]).read_text())
        for pid, name, *_rest in EXTRA:
            addr = _rest[4]
            if addr:
                pages[f"https://{addr.split('@')[1]}/"] = f"<footer>&copy; {YEAR} {name}</footer>"
        Path(self.env["LEADS_PAGE_FIXTURE"]).write_text(json.dumps(pages))
        self.env.update({"LEADS_DB": str(self.db), "LEADS_VENDOR_PRICES": str(self.t / "prices.md")})

    def test_stats_counts_every_proposition(self):
        r = self.run_leads("batch", "--stats", "--json", "--segment", "services")
        self.assertEqual(r.returncode, 0, r.stderr)
        by = json.loads(r.stdout)["by_proposition"]
        self.assertEqual(set(by), {"P0", "P1", "P2", "P3", "P4", "P5", "P6"})
        self.assertEqual(by["P4"]["emailable"], 3)
        self.assertEqual(by["P3"]["emailable"], 1)
        self.assertGreaterEqual(by["P5"]["emailable"] + by["P6"]["emailable"], 12)
        self.assertGreaterEqual(min(by["P5"]["emailable"], by["P6"]["emailable"]), 3)    # both arms dealt
        self.assertGreaterEqual(by["P2"]["businesses"], 1)                     # Elk, with no site of its own
        self.assertEqual((by["P2"]["emailable"], by["P2"]["ready"]), (0, 0))
        self.assertGreater(by["P1"]["emailable"], 0)
        text = self.run_leads("batch", "--stats", "--segment", "services").stdout
        self.assertIn("By proposition", text)
        self.assertIn("E1 (the frame): P5", text)

    def test_unknown_and_card_propositions_are_refused(self):
        r = self.run_leads("batch", "--proposition", "P9")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--proposition is one of", r.stderr)
        r = self.run_leads("batch", "--proposition", "P2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("isn't an email proposition", r.stderr)

    def p4_batch(self):
        r = self.batch("--proposition", "P4", "--json", "--no-save")
        return json.loads(r.stdout)

    def test_a_p4_batch_says_only_traced_facts(self):
        b = self.p4_batch()
        self.assertEqual(b["proposition"], "P4")
        self.assertRegex(b["batch_id"], r"-services-p4-lehi-plumber-1$")
        self.assertEqual({p["place_id"] for p in b["picks"]}, {"FX_P4A", "FX_P4B", "FX_P4C"})
        conn = sqlite3.connect(self.db)
        for p in b["picks"]:
            self.assertEqual((p["proposition"], p["proposition_experiment"]), ("P4", None))
            self.assertEqual(p["faults"], [])
            self.assertEqual(p["letters"], ["p4-first", "p4-second", "p4-third"])
            self.assertEqual([s["slot"] for s in p["specifics"]], ["builder", "fact"])
            vendor, = conn.execute("SELECT vendor FROM hosts WHERE place_id=?", (p["place_id"],)).fetchone()
            self.assertEqual(p["specifics"][0]["sentence"], {"wix": "Wix", "squarespace": "Squarespace"}[vendor])
            n, rating = conn.execute("SELECT reviews, rating FROM place_cache WHERE place_id=?",
                                     (p["place_id"],)).fetchone()
            fact = p["specifics"][1]
            self.assertEqual(fact["key"], "google_standing")
            self.assertIn(f"{n} reviews, {rating}", fact["evidence"])
            self.assertTrue(all(s["evidence"] for s in p["specifics"]))
        conn.close()
        self.trace_rendered(b)

    def trace_rendered(self, b):
        """Render the batch's first letters through `outreach send --dry-run` and read every sentence back: each is
        the approved text with only the business's name, the greeting, the price line, the phone and the address
        filled in, or it says one of the pick's own facts, each of which has a source (the trace)."""
        tmp = self.t / "o"
        tpl = tmp / "tpl"
        shutil.copytree(TEMPLATES, tpl)
        (tmp / "b.json").write_text(json.dumps(b))
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp), "CLAUDE_TOOLS_ENV": os.devnull,
               "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "OUTREACH_TEMPLATES": str(tpl),
               "OUTREACH_STATE": str(tmp / "state"), "OUTREACH_LEDGER": str(tmp / "ledger.jsonl"),
               "OUTREACH_LEADS_BIN": "/bin/false", "OUTREACH_NOTIFY_BIN": "/bin/true", "OUTREACH_PROVIDER": "fake",
               "LEADS_MAIL_ADDRESS": "PO Box 1, American Fork, UT 84003", "PATCHLAMP_VOICE_NUMBER": "801-555-0100",
               "TAYLOR_TODO": str(tmp / "TODO.md"), "OUTREACH_NOW": "2026-10-19T09:00:00"}
        r = subprocess.run([sys.executable, str(OUTREACH), "send", "--batch", str(tmp / "b.json"), "--dry-run"],
                           capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        letters = re.split(r"\n\d+\. ", r.stdout)[1:]
        self.assertEqual(len(letters), len(b["picks"]), r.stdout)
        raw = (TEMPLATES / "p4-first.md").read_text()
        approved = "\n".join(l for l in raw.splitlines() if not l.startswith("#"))
        approved = re.sub(r"^\[[?!][a-z_]+\] ?", "", approved, flags=re.M)
        for pick, text in zip(b["picks"], letters):
            body = "\n".join(l[5:] if l.startswith("   | ") else l[4:] for l in text.splitlines()
                             if l.startswith("   |"))
            subject = re.search(r'— "(.+?)" \[AI sentence', text).group(1)
            facts = {s["slot"]: s for s in pick["specifics"]}
            hi = re.search(r"^Hi (.+),$", body, re.M).group(1)          # a name, or the business's "team"
            generic = {"{first}": hi, "{business}": pick["name"], "{price_line}": None, "{phone}": "801-555-0100",
                       "{address}": "PO Box 1, American Fork, UT 84003"}
            for sent in [subject] + [x for x in re.split(r"(?<=[.!?:])\s+|\n", body) if x.strip()]:
                said = [slot for slot, s in facts.items() if s["sentence"] in sent]
                for slot in said:
                    self.assertTrue(facts[slot]["evidence"], f"{slot} has no source")
                    sent = sent.replace(facts[slot]["sentence"], "{" + slot + "}")
                for ph, val in generic.items():
                    if val:
                        sent = sent.replace(val, ph)
                sent = re.sub(r"\$\d+ a month, no contract", "{price_line}", sent)
                self.assertIn(sent.strip(), approved,
                              f"{pick['name']}: a sentence that is neither the approved text nor a traced fact: {sent!r}")


# ---- outreach: a P5/P6 batch sent, and the report ---------------------------------------------------------

def slot_picks(n, prop):
    out = []
    for p in json.loads(tob.BATCH.read_text())["picks"]:
        if p["email_kind"] != "own-domain" or len(out) >= n:
            continue
        q = dict(p, faults=[], proposition=prop, proposition_experiment="E1", proposition_arm=prop,
                 letters=[f"{prop.lower()}-first", f"{prop.lower()}-second", f"{prop.lower()}-third"],
                 specifics=[{"slot": "fact_one", "key": "google_standing",
                             "sentence": "you have more than 40 Google reviews, averaging 4.8 stars",
                             "evidence": p["maps_url"] + " (census read 2026-10-01: 44 reviews, 4.8)"},
                            {"slot": "fact_two", "key": "phone_matches",
                             "sentence": "the phone number on your site matches your Google listing",
                             "evidence": p["site_url"] + " (site read 2026-10-01)"}])
        out.append(q)
    return out


class OutreachByProposition(tob.Base):
    def test_e1_sends_carry_the_arm_sit_outside_the_ai_test_and_the_report_has_every_row(self):
        self.approve()
        self.run_it("ai-test", "start")
        picks = slot_picks(6, "P5")
        for q in picks[3:]:
            q.update(proposition="P6", proposition_arm="P6", letters=["p6-first", "p6-second", "p6-third"])
        self.run_it("send", "--batch", str(self.write_batch(picks, "b-e1")), "--go")
        seqs = self.seqs()
        self.assertEqual(6, len(seqs))
        self.assertEqual({"intro"}, {s["variant"] for s in seqs})          # E2 is the chore lanes' test, not E1's
        self.assertEqual({None}, {s["ai_test"] for s in seqs})
        self.assertEqual({"p5-first", "p6-first"}, {s["touches"][0]["template"] for s in seqs})
        self.tick_day(tob.MONDAY)
        rows = self.state_rows("sends.jsonl")
        self.assertEqual(6, len(rows))
        for r in rows:
            self.assertEqual(r["proposition_experiment"], "E1")
            self.assertEqual(r["proposition"], r["proposition_arm"])
        self.assertEqual(6, len(tob.Mail.sent))
        self.assertEqual(3, sum(r["subject"].startswith("AI for ") for r in rows))      # P6's subject line
        logs = [c for c in self.calls("leads") if "messaged" in c["argv"]]
        self.assertTrue(logs)
        self.assertTrue(all("proposition_experiment=E1" in c["argv"] for c in logs))
        out = self.run_it("status", "--by", "proposition").stdout
        for k in ("P0", "P1", "P2", "P3", "P4", "P5", "P6"):
            self.assertRegex(out, rf"\n  {k} ")
        self.assertIn("E1 (the frame): P5 against P6", out)
        self.assertIn("P5: too few to decide (3 delivered of 100)", out)
        self.assertIn("P6: too few to decide (3 delivered of 100)", out)

    def test_a_slot_pick_without_its_facts_or_their_source_is_not_written_to(self):
        self.approve()
        picks = slot_picks(3, "P5")
        picks[0]["specifics"] = picks[0]["specifics"][:1]
        picks[1]["specifics"][1]["evidence"] = ""
        out = self.run_it("send", "--batch", str(self.write_batch(picks, "b-bad")), "--go").stdout
        self.assertIn("no fact_two for its P5 letter", out)
        self.assertIn("a fact with no source", out)
        self.assertEqual(1, len(self.seqs()))

    def test_an_unapproved_proposition_letter_holds_only_its_own_batch(self):
        self.approve()
        p = self.tpl / "p4-first.md"
        p.write_text(p.read_text().replace("Just reply.", "Just reply now."))
        picks = slot_picks(2, "P4")
        for q in picks:
            q.update(proposition_experiment=None, proposition_arm=None, letters=["p4-first", "p4-second", "p4-third"],
                     specifics=[{"slot": "builder", "key": "host", "sentence": "Wix", "evidence": "hosts: wix"},
                                {"slot": "fact", **{k: q["specifics"][0][k] for k in ("key", "sentence", "evidence")}}])
        r = self.run_it("send", "--batch", str(self.write_batch(picks, "b-p4")), "--go", expect=1)
        self.assertIn("p4-first: the text changed since Taylor approved it", r.stderr)
        r = self.run_it("send", "--batch", str(self.write_batch(tob.json.loads(tob.BATCH.read_text())["picks"][:1],
                                                                "b-p1")), "--go")
        self.assertEqual(1, len(self.seqs()))


if __name__ == "__main__":
    unittest.main()
