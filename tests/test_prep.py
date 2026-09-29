"""prep (ROADMAP B65, plan ~/projects/plans/28-prep-run.md): the brief, the facts lint, the research
boundary's hook, `prep research` end to end and `prep doctor`, all against a fake `claude`
(tests/fixtures/prep/fake-claude) and a fixture census: no network, no model, no money.

    python3 -m unittest tests.test_prep -q   (from claude-tools/)
"""

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PREP = TOOLS / "bin" / "prep"
FIX = HERE / "fixtures" / "prep"
FAKE = FIX / "fake-claude"
SERVICES = HERE / "fixtures" / "leads-services"
MAPS = "https://maps.google.com/?cid=FX_S01"


def fixture_census(path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("leads_services_build_prep", SERVICES / "build.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.build(path, businesses=True)


def prep_module():
    import importlib.util
    from importlib.machinery import SourceFileLoader
    spec = importlib.util.spec_from_loader("prep_mod", SourceFileLoader("prep_mod", str(PREP)))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


P = prep_module()
LISTING = json.loads((FIX / "details" / "FX_S01.json").read_text())
GOOD = json.loads((FIX / "facts-good.json").read_text())


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.t = t
        self.db = fixture_census(t / "census.db")
        (t / "leads" / "details").mkdir(parents=True)
        shutil.copy(FIX / "details" / "FX_S01.json", t / "leads" / "details" / "FX_S01.json")
        self.log = t / "fake.jsonl"
        self.env = dict(os.environ)
        for k in ("PREP_MODEL_BUILD", "PREP_MODEL_JUDGE", "FAKE_CLAUDE_MODE", "FAKE_CLAUDE_AUTH"):
            self.env.pop(k, None)
        self.env.update({
            "LEADS_DB": str(self.db), "LEADS_STATE": str(t / "leads"), "LEADS_LEDGER": str(t / "ledger.jsonl"),
            "PREP_STATE": str(t / "prep"), "PREP_LEDGER": str(t / "ledger.jsonl"), "PREP_CLAUDE": str(FAKE),
            "CLAUDE_TOOLS_ENV": str(t / "no-env"), "GOOGLE_MAPS_API_KEY": "", "LEADS_SEGMENT": "",
            "PREP_TODAY": "2026-09-29", "FAKE_CLAUDE_LOG": str(self.log), "FAKE_CLAUDE_FACTS": str(FIX / "facts-good.json"),
            "ANTHROPIC_API_KEY": "sk-ant-FAKEkeyNEVERreal000",   # set here to prove every session strips it
        })

    def tearDown(self):
        self.tmp.cleanup()

    def run_prep(self, *args, env=None, timeout=120):
        return subprocess.run([sys.executable, str(PREP), *args], capture_output=True, text=True,
                              env=dict(self.env, **(env or {})), timeout=timeout)

    def fake_calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]


# ---- the lint ---------------------------------------------------------------------------------------

class LintTest(unittest.TestCase):
    def lint(self, doc, listing=LISTING):
        return P.lint_facts(doc, listing)

    def edited(self, fn):
        d = copy.deepcopy(GOOD)
        fn(d)
        return self.lint(d)

    def assertFails(self, res, fragment):
        self.assertFalse(res["ok"], res)
        self.assertTrue(any(fragment in e for e in res["errors"]), res["errors"])

    def test_good_file_passes(self):
        res = self.lint(GOOD)
        self.assertTrue(res["ok"], res["errors"])
        self.assertEqual(res["counts"], {"facts": 6, "high": 4, "medium": 2, "services": 3})
        self.assertFalse(res["thin"])

    def test_every_fact_needs_a_source_url_and_its_words(self):
        self.assertFails(self.edited(lambda d: d["facts"][0]["source"].pop("url")), "no source URL")
        self.assertFails(self.edited(lambda d: d["facts"][0]["source"].update(words="")), "no source words")
        self.assertFails(self.edited(lambda d: d["facts"][0].pop("source")), "no source")
        self.assertFails(self.edited(lambda d: d["facts"][5]["source"].update(url="not a url")), "no source URL")

    def test_high_needs_listing_own_site_record_or_two_independent_sources(self):
        def one_search(d):
            d["facts"][5]["confidence"] = "high"
        self.assertFails(self.edited(one_search), "high needs")

        def one_review(d):
            d["facts"][1].pop("also")
        self.assertFails(self.edited(one_review), "high needs")

        def same_review_twice(d):
            d["facts"][1]["also"][0].update(ref=1, words="fixed our pump")
        self.assertFails(self.edited(same_review_twice), "high needs")

        def search_plus_directory(d):
            d["facts"][5]["confidence"] = "high"
            d["facts"][5]["also"] = [{"kind": "directory", "url": "https://www.bbb.org/us/ut/american-fork/profile/mikes",
                                      "words": "Serving American Fork, Lehi"}]
        self.assertTrue(self.edited(search_plus_directory)["ok"])

        def own_site(d):
            d["facts"][3].update(confidence="high",
                                 source={"kind": "own_site", "url": "https://mikespool.example/", "words": "Weekly service"})
        self.assertTrue(self.edited(own_site)["ok"])

    def test_a_review_run_of_six_words_fails(self):
        res = self.edited(lambda d: d["facts"][3].update(text="Weekly cleaning all season and they fixed things."))
        self.assertFails(res, "shares a run of 6 words with review 1")
        res = self.edited(lambda d: d["about"][0].update(text="The water has never been this clear, customers say."))
        self.assertFails(res, "review 0")
        # five shared words in a row are fine; the words field is never checked (it is never published)
        self.assertTrue(self.edited(lambda d: d["facts"][3].update(text="Weekly cleaning all season long."))["ok"])

    def test_a_persons_name_fails(self):
        self.assertFails(self.edited(lambda d: d["facts"][2].update(text="Jorge does the spring openings.")),
                         "a person's name from the reviews (jorge)")
        self.assertFails(self.edited(lambda d: d["about"][0].update(text="Trusted by Whitfield families.")),
                         "whitfield")
        self.assertFails(self.edited(lambda d: d["about"][0].update(text="Run by owner Dan since the start.")),
                         "a person's name")
        self.assertFails(self.edited(lambda d: d["services"][0].update(name="Pump repair with Mr. Jones")),
                         "a person's name")
        # the business's own name holds a name, and that is fine
        self.assertTrue(self.edited(lambda d: d["about"][0].update(text="Mike's Pool Care keeps pools clear."))["ok"])

    @unittest.skipUnless(Path("/usr/share/dict/words").exists(), "no system dictionary")
    def test_a_name_that_starts_a_review_sentence_fails_and_a_common_word_does_not(self):
        self.assertFails(self.edited(lambda d: d["facts"][2].update(text="Carlos does the spring openings.")),
                         "(carlos)")
        self.assertTrue(self.edited(lambda d: d["facts"][3].update(text="Weekly visits, all season."))["ok"])

    def test_a_price_fails(self):
        for text in ("Openings from $180.", "Openings for 180 dollars.", "Cleaning at 60/hour.", "Just 40 per visit."):
            self.assertFails(self.edited(lambda d: d["about"][0].update(text=text)), "a price")

    def test_a_street_address_fails(self):
        for text in ("Find us at 600 N 100 E.", "Visit 101 N Main St for supplies.", "Suite 4, the back office."):
            self.assertFails(self.edited(lambda d: d["area"].update(text=text)), "street address")
        self.assertFails(self.edited(lambda d: d["area"].update(text="Based at 101 N Main in town.")), "street address")

    def test_meta_hosts_only_as_search_results(self):
        self.assertFails(self.edited(lambda d: d["facts"][5]["source"].update(kind="directory")), "Meta host")
        self.assertFails(self.edited(lambda d: d["facts"][5]["source"].update(
            kind="own_site", url="https://www.instagram.com/mikespool/")), "Meta host")
        self.assertTrue(self.lint(GOOD)["ok"])   # the good file cites facebook.com as a search result

    def test_listing_and_review_words_are_checked_against_the_listing_read(self):
        self.assertFails(self.edited(lambda d: d["facts"][0]["source"].update(words="(801) 555-9999")),
                         "aren't in the listing read")
        self.assertFails(self.edited(lambda d: d["facts"][2]["source"].update(words="drained the whole pool")),
                         "aren't in review 0")
        self.assertFails(self.edited(lambda d: d["facts"][2]["source"].update(ref=9)), "needs ref")
        self.assertFails(self.edited(lambda d: d["facts"][2]["source"].pop("ref")), "needs ref")
        self.assertFails(self.edited(lambda d: d["facts"][0]["source"].update(url="https://maps.google.com/?cid=OTHER")),
                         "maps link")
        long_words = " ".join(["Carlos opened our pool in April and balanced the chemicals the same week."] * 3)
        self.assertFails(self.edited(lambda d: d["facts"][2]["source"].update(words=long_words)), "under 25")

    def test_record_is_a_gov_host(self):
        def rec(d, url):
            d["facts"].append({"id": "f9", "kind": "since", "text": "Registered in Utah in 2019.", "confidence": "high",
                               "source": {"kind": "record", "url": url, "words": "Registration Date: 2019"}})
        self.assertFails(self.edited(lambda d: rec(d, "https://opencorporates.com/companies/us_ut/1")), ".gov")
        self.assertTrue(self.edited(lambda d: rec(d, "https://businessregistration.utah.gov/EntitySearch/1"))["ok"])

    def test_shape_errors(self):
        self.assertFails(self.edited(lambda d: d.update(verdict="skip")), "skip_reason")
        self.assertTrue(self.edited(lambda d: d.update(verdict="skip", skip_reason="closed"))["ok"])
        self.assertFails(self.edited(lambda d: d.update(verdict="maybe")), "verdict")
        self.assertFails(self.edited(lambda d: d["services"][0].update(facts=["f99"])), "doesn't exist")
        self.assertFails(self.edited(lambda d: d["services"][0].update(facts=[])), "names no facts")
        self.assertFails(self.edited(lambda d: d["facts"][1].update(id="f1")), "id used twice")
        self.assertFails(self.edited(lambda d: d["facts"][1].update(kind="gossip")), "kind 'gossip'")
        self.assertFails(self.edited(lambda d: d["facts"][1]["source"].update(kind="rumour")), "kind 'rumour'")
        self.assertFails(self.edited(lambda d: d["facts"][1].update(confidence="low")), "confidence")
        self.assertFails(self.edited(lambda d: d.update(place_id="OTHER")), "not the listing's")
        self.assertFails(self.lint(GOOD, listing=None), "no listing read")

    def test_thin_is_a_warning_not_an_error(self):
        def thin(d):
            for f in d["facts"]:
                f["confidence"] = "medium"
                f.pop("also", None)
        res = self.edited(thin)
        self.assertTrue(res["ok"], res["errors"])
        self.assertTrue(res["thin"])
        self.assertTrue(any("only medium" in w for w in res["warnings"]))

    def test_cli_exit_codes_and_json(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            shutil.copy(FIX / "details" / "FX_S01.json", t / "listing.json")
            (t / "facts.json").write_text(json.dumps(GOOD))
            r = subprocess.run([sys.executable, str(PREP), "facts", "lint", str(t / "facts.json")],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("OK · 6 facts (4 high, 2 medium) · 3 services", r.stdout)
            bad = copy.deepcopy(GOOD)
            bad["about"][0]["text"] = "From $99."
            (t / "facts.json").write_text(json.dumps(bad))
            r = subprocess.run([sys.executable, str(PREP), "facts", "lint", str(t / "facts.json"), "--json"],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 1)
            self.assertFalse(json.loads(r.stdout)["ok"])


class VerifyTest(unittest.TestCase):
    def test_words_not_on_the_page_are_set_aside_and_high_drops_to_medium(self):
        doc = copy.deepcopy(GOOD)
        doc["facts"][3].update(confidence="high", source={"kind": "own_site", "url": "https://mikes.example/",
                                                          "words": "Weekly pool service all season"})
        doc["facts"][4]["also"] = [{"kind": "directory", "url": "https://dir.example/mikes", "words": "Mon-Fri 8-5"}]
        doc["facts"][5].update(confidence="high", also=[{"kind": "directory", "url": "https://dir.example/mikes",
                                                         "words": "Serving American Fork and Lehi"}])
        pages = {"https://mikes.example/": P.norm_text("Home. Weekly pool service all season, openings in spring."),
                 "https://dir.example/mikes": P.norm_text("Mike's Pool Care. Serving Orem.")}
        fetched = []

        def fetch(url):
            fetched.append(url)
            return pages.get(url)
        rep = P.verify_sources(doc, fetch=fetch)
        self.assertEqual(sorted(set(fetched)), sorted(pages))          # each page read once; reviews/listing never
        self.assertEqual([r["fact"] for r in rep["found"]], ["f4"])
        self.assertEqual(sorted(r["fact"] for r in rep["missing"]), ["f5", "f6"])
        self.assertEqual(rep["downgraded"], ["f6"])                    # f5 still has the listing behind it
        f5, f6 = doc["facts"][4], doc["facts"][5]
        self.assertEqual(f5["confidence"], "high")
        self.assertNotIn("also", f5)
        self.assertEqual(f5["unverified"][0]["url"], "https://dir.example/mikes")
        self.assertEqual(f6["confidence"], "medium")
        self.assertIn("weren't found", f6["downgraded"])
        self.assertEqual(doc["facts"][3]["confidence"], "high")
        self.assertTrue(P.lint_facts(doc, LISTING)["ok"])

    def test_an_unreadable_page_counts_as_unverified_and_meta_is_never_read(self):
        doc = copy.deepcopy(GOOD)
        doc["facts"][3].update(confidence="high", source={"kind": "own_site", "url": "https://gone.example/",
                                                          "words": "Weekly"})
        rep = P.verify_sources(doc, fetch=lambda url: None)
        self.assertEqual(rep["downgraded"], ["f4"])
        self.assertIsNone(P.fetch_text("https://www.facebook.com/mikespoolcare"))


# ---- the boundary's hook ------------------------------------------------------------------------------

class HookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name)) / "biz"
        (self.root / "log").mkdir(parents=True)
        P.write_json(self.root / "log" / "research.caps.json", {"searches": 0, "fetches": 0, "denied": 0})

    def tearDown(self):
        self.tmp.cleanup()

    def hook(self, tool, ti):
        r = subprocess.run([sys.executable, str(PREP), "hook", "research", "--dir", str(self.root)],
                           input=json.dumps({"tool_name": tool, "tool_input": ti, "cwd": "/"}),
                           capture_output=True, text=True)
        return r.returncode, r.stderr

    def test_meta_hosts_are_refused(self):
        for url in ("https://www.facebook.com/x", "https://m.facebook.com/x", "https://l.facebook.com/l.php?u=x",
                    "https://www.instagram.com/x/", "https://fb.com/x", "https://scontent.xx.fbcdn.net/a.jpg",
                    "https://www.threads.net/@x", "https://m.me/x", "https://wa.me/1801"):
            code, err = self.hook("WebFetch", {"url": url, "prompt": "t"})
            self.assertEqual(code, 2, url)
            self.assertIn("Meta host", err)
        code, _ = self.hook("WebFetch", {"url": "https://www.bbb.org/x", "prompt": "t"})
        self.assertEqual(code, 0)
        code, _ = self.hook("WebFetch", {"url": "https://notfacebook.com/x", "prompt": "t"})
        self.assertEqual(code, 0)
        rows = [json.loads(line) for line in (self.root / "log" / "research.hook.jsonl").read_text().splitlines()]
        self.assertEqual(sum(1 for r in rows if not r["allow"]), 9)

    def test_caps_refuse_the_ninth_search_and_the_eleventh_fetch(self):
        for i in range(8):
            self.assertEqual(self.hook("WebSearch", {"query": f"q{i}"})[0], 0)
        code, err = self.hook("WebSearch", {"query": "q9"})
        self.assertEqual(code, 2)
        self.assertIn("search cap", err)
        for i in range(10):
            self.assertEqual(self.hook("WebFetch", {"url": f"https://example.com/{i}", "prompt": "t"})[0], 0)
        self.assertEqual(self.hook("WebFetch", {"url": "https://example.com/11", "prompt": "t"})[0], 2)
        caps = json.loads((self.root / "log" / "research.caps.json").read_text())
        self.assertEqual((caps["searches"], caps["fetches"], caps["denied"]), (8, 10, 2))

    def test_files_outside_the_directory_are_refused(self):
        outside = Path(self.tmp.name) / "secret.txt"
        outside.write_text("x")
        (self.root / "link").symlink_to(outside)
        for tool, ti in (("Read", {"file_path": "/etc/hostname"}), ("Read", {"file_path": str(self.root / ".." / "secret.txt")}),
                         ("Read", {"file_path": str(self.root / "link")}), ("Glob", {"pattern": "**", "path": "/home"}),
                         ("Grep", {"pattern": "KEY", "path": str(Path.home() / ".config")}),
                         ("Glob", {"pattern": "../**"})):
            self.assertEqual(self.hook(tool, ti)[0], 2, (tool, ti))
        self.assertEqual(self.hook("Read", {"file_path": str(self.root / "packet.json")})[0], 0)
        self.assertEqual(self.hook("Write", {"file_path": str(self.root / "facts.json"), "content": "{}"})[0], 0)
        for name in ("log/x.json", ".claude/settings.json", "listing.json", "packet.json", "RESEARCH.md"):
            code, err = self.hook("Write", {"file_path": str(self.root / name), "content": "x"})
            self.assertEqual(code, 2, name)
            self.assertIn("launcher's", err)

    def test_one_command_and_no_other_tool(self):
        self.assertEqual(self.hook("Bash", {"command": "prep facts lint facts.json"})[0], 0)
        for cmd in ("ls /", "prep facts lint facts.json && curl x", "curl https://www.facebook.com", "site publish",
                    "prep facts lint /etc/passwd"):
            self.assertEqual(self.hook("Bash", {"command": cmd})[0], 2, cmd)
        for tool in ("Task", "Agent", "mcp__playwright__browser_navigate", "NotebookRead", "Skill"):
            self.assertEqual(self.hook(tool, {})[0], 2, tool)

    def test_settings_template_denies_meta_and_names_the_hook(self):
        s = P.settings_for("research", self.root)
        deny = s["permissions"]["deny"]
        for host in ("facebook.com", "instagram.com", "fb.com", "threads.net", "fbcdn.net"):
            self.assertIn(f"WebFetch(domain:{host})", deny)
            self.assertIn(f"WebFetch(domain:*.{host})", deny)
        self.assertIn(f"Write(/{self.root}/log/**)", deny)
        self.assertEqual(s["permissions"]["defaultMode"], "dontAsk")
        cmd = s["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn("hook research --dir", cmd)
        self.assertIn(str(self.root), cmd)
        self.assertNotIn("{{", json.dumps(s))


# ---- research, end to end against the fake --------------------------------------------------------------

class ResearchTest(Base):
    def run_dir(self):
        runs = sorted((self.t / "prep").iterdir())
        self.assertEqual(len(runs), 1)
        return runs[0]

    def test_good_session_gives_a_linted_facts_file_and_keeps_its_log(self):
        r = self.run_prep("research", "FX_S01")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("facts", r.stdout)
        run = self.run_dir()
        self.assertEqual(run.name, "2026-09-29-a")
        biz = run / "mikes-pool-care"
        for f in ("facts.json", "listing.json", "packet.json", "RESEARCH.md", "CLAUDE.md", ".claude/settings.json",
                  "log/research.stream.jsonl", "log/research.json", "log/research.hook.jsonl", "log/research.lint.json"):
            self.assertTrue((biz / f).exists(), f)
        facts = json.loads((biz / "facts.json").read_text())
        # code owns the computed fields: the faults come from leads, the hours from the listing
        self.assertIn("only 2 photos", facts["faults"])
        self.assertEqual(facts["hours"]["as_listed"][0], "Monday: 8:00 AM – 5:00 PM")
        self.assertTrue(P.lint_file(biz / "facts.json")["ok"])
        # the session: the model named, never Fable; restricted; the stamped boundary; no API key; prep on PATH
        call = [c for c in self.fake_calls() if "-p" in c["argv"]][0]
        a = call["argv"]
        self.assertEqual(a[a.index("--model") + 1], "claude-sonnet-5-5")
        for flag in ("--restricted", "--strict-mcp-config", "--disable-slash-commands"):
            self.assertIn(flag, a)
        self.assertEqual(a[a.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(a[a.index("--settings") + 1], str(biz / ".claude" / "settings.json"))
        self.assertFalse(call["api_key_seen"])
        self.assertTrue(call["path_has_prep"])
        self.assertEqual(call["lint_exit"], 0)
        # the boundary refused the Meta fetch and the read outside; allowed the search and the ordinary fetch
        by = {(h["tool"], json.dumps(h["input"])): h["refused"] for h in call["hooks"]}
        self.assertEqual([h["refused"] for h in call["hooks"]], [True, False, False, True])
        self.assertEqual(len(by), 4)
        hook_rows = [json.loads(line) for line in (biz / "log" / "research.hook.jsonl").read_text().splitlines()]
        self.assertFalse([h for h in hook_rows if h["allow"] and P.is_meta(h["target"] or "")])
        # run.json keeps the usage by stage; the ledger line is notional (cost_usd 0) with the list price beside it
        rj = json.loads((run / "run.json").read_text())
        self.assertEqual(rj["businesses"]["mikes-pool-care"]["status"], "facts")
        u = rj["usage"]["research"]
        self.assertEqual((u["sessions"], u["output_tokens"], u["models"]), (1, 50, ["claude-sonnet-5-5"]))
        self.assertEqual(u["permission_denials"], 2)
        ledger = [json.loads(line) for line in (self.t / "ledger.jsonl").read_text().splitlines()]
        self.assertEqual([e["kind"] for e in ledger], ["prep_research"])
        self.assertEqual(ledger[0]["cost_usd"], 0)
        self.assertEqual(ledger[0]["plan_usd_list"], 0.1234)

    def test_a_failed_lint_is_retried_once_with_the_errors(self):
        r = self.run_prep("research", "FX_S01", env={"FAKE_CLAUDE_MODE": "bad"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        calls = [c for c in self.fake_calls() if "-p" in c["argv"]]
        self.assertEqual(len(calls), 2)
        self.assertIsNone(calls[0]["resume"])
        self.assertIsNotNone(calls[1]["resume"])
        self.assertIn("shares a run of 6 words", calls[1]["prompt"])
        self.assertIn("a price", calls[1]["prompt"])
        biz = self.run_dir() / "mikes-pool-care"
        self.assertTrue((biz / "log" / "research-retry.json").exists())
        rj = json.loads((self.run_dir() / "run.json").read_text())
        self.assertEqual(rj["businesses"]["mikes-pool-care"]["status"], "facts")
        self.assertEqual(rj["usage"]["research"]["sessions"], 2)

    def test_a_skip_is_kept_with_its_reason(self):
        r = self.run_prep("research", "FX_S01", env={"FAKE_CLAUDE_MODE": "skip"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("skip", r.stdout)
        self.assertIn("has its own site", r.stdout)

    def test_a_session_on_fable_fails_the_business(self):
        r = self.run_prep("research", "FX_S01", env={"FAKE_CLAUDE_MODE": "fable"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("Fable is never a prep model", r.stdout)
        self.assertEqual(len([c for c in self.fake_calls() if "-p" in c["argv"]]), 1)   # no retry on Fable

    def test_fable_named_as_the_model_is_refused_before_any_session(self):
        r = self.run_prep("research", "FX_S01", env={"PREP_MODEL_BUILD": "fable"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("never runs on Fable", r.stderr)
        self.assertFalse([c for c in self.fake_calls() if "-p" in c["argv"]])

    def test_not_the_subscription_login_is_refused(self):
        r = self.run_prep("research", "FX_S01", env={"FAKE_CLAUDE_AUTH": "apikey"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("not the subscription", r.stderr)
        self.assertFalse([c for c in self.fake_calls() if "-p" in c["argv"]])

    def test_the_time_cap_stops_a_session(self):
        r = self.run_prep("research", "FX_S01", env={"FAKE_CLAUDE_MODE": "hang", "PREP_RESEARCH_MINUTES": "0.01"})
        self.assertEqual(r.returncode, 1)
        rj = json.loads((self.run_dir() / "run.json").read_text())
        s = rj["businesses"]["mikes-pool-care"]["stages"]["research"]["sessions"][0]
        self.assertTrue(s["timed_out"])

    def test_no_listing_on_disk_and_no_fetch_is_a_skip_and_a_stranger_fails(self):
        r = self.run_prep("research", "FX_S02", "NOT_A_PLACE", "--no-fetch")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no listing read on disk", r.stdout)
        self.assertIn("not in the services census", r.stdout)
        self.assertFalse([c for c in self.fake_calls() if "-p" in c["argv"]])

    def test_dry_run_stamps_and_prints_the_command(self):
        r = self.run_prep("research", "FX_S01", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--model claude-sonnet-5-5", r.stdout)
        self.assertTrue((self.run_dir() / "mikes-pool-care" / ".claude" / "settings.json").exists())
        self.assertFalse([c for c in self.fake_calls() if "-p" in c["argv"]])
        self.assertFalse((self.t / "ledger.jsonl").exists())


# ---- brief and doctor ------------------------------------------------------------------------------------

class BriefDoctorTest(Base):
    def test_brief_prints_the_packet(self):
        r = self.run_prep("brief", "FX_S01")
        self.assertEqual(r.returncode, 0, r.stderr)
        for s in ("Mike's Pool Care · pool service · American Fork", "slug mikes-pool-care", "facebook.com/mikespoolcare",
                  "[0] 5★ 3 weeks ago — Carlos opened", "only 2 photos"):
            self.assertIn(s, r.stdout)
        j = json.loads(self.run_prep("brief", "FX_S01", "--json").stdout)
        self.assertEqual((j["slug"], len(j["reviews"]), j["listing"]["maps_url"]), ("mikes-pool-care", 3, MAPS))
        self.assertEqual(self.run_prep("brief", "NOPE").returncode, 1)

    def test_doctor(self):
        r = self.run_prep("doctor")
        self.assertIn("ok  login: the subscription (max, claude.ai)", r.stdout)
        self.assertIn("ok  model build: claude-sonnet-5-5", r.stdout)
        self.assertIn("ok  research settings: Meta hosts denied", r.stdout)
        self.assertIn("ANTHROPIC_API_KEY set, stripped from every session", r.stdout)
        self.assertIn("BAD Places key: missing", r.stdout)       # the fixture env has none
        self.assertEqual(r.returncode, 1)
        r = self.run_prep("doctor", env={"FAKE_CLAUDE_AUTH": "apikey", "PREP_MODEL_JUDGE": "claude-fable-5"})
        self.assertIn("BAD login: not the subscription (api_key)", r.stdout)
        self.assertIn("BAD model judge: claude-fable-5", r.stdout)
        r = self.run_prep("doctor", env={"GOOGLE_MAPS_API_KEY": "fake-key-by-name"})
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("fake-key-by-name", r.stdout)


if __name__ == "__main__":
    unittest.main()
