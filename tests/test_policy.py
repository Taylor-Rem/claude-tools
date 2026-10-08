"""One prospect record, and the policy as code and as a page (ROADMAP B140, plan 55 § 5.1-5.2).

    python3 -m unittest tests.test_policy   (from claude-tools/)

Offline. What's pinned:
  - the page: private-docs/leads/policy.md (POLICY_PAGE overrides) lists the seven rules in lib/policy.py's ORDER,
    each with the same number, lane and decision as `policy.RULES`; a drift either way fails;
  - route() is pure and says each rule as plan 55 § 5.2 says it, on hand-made records (rule by rule, the order
    between them, rule 7's "no hold" note, rule 3's mailbox chosen by assets.plan_tick and nothing else);
  - no drift: on the fifty-five operational businesses of tests/policy_capture.py's world, what the CLIs decide
    today is still tests/fixtures/policy/today.json, and route() over the records `leads prospects rebuild` makes
    agrees with it except where § 5.2 says otherwise: each such business is named in DIFFERENCES with the class of
    difference, and a difference that appears or disappears fails the test;
  - the store: rebuilt from the logs when missing, the hooks in `leads log` and `outreach suppress` update the
    record they touch, the venture is a column;
  - portable: route() reads a proposition's lane, never its id, so another venture's table routes the same way.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent / "lib"))

import copy  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

import assets  # noqa: E402
import policy  # noqa: E402
import prospects  # noqa: E402
import policy_capture as pc  # noqa: E402

PAGE = Path(os.environ.get("POLICY_PAGE") or Path.home() / "projects" / "private-docs" / "leads" / "policy.md")

PROPS = {"P1": {"lane": "email", "letters": ("batch-first", "batch-second", "batch-third"), "label": "faulted"},
         "P2": {"lane": "card", "letters": None, "label": "no site"},
         "P5": {"lane": "email", "letters": ("p5-first", "p5-second", "p5-third"), "label": "own site"},
         "P0": {"lane": None, "letters": None, "label": "none"}}

# Where route() follows plan 55 § 5.2 and a CLI does something else today, business by business. The class says why;
# the report to Flint names each one. (cli lane, route lane) per class:
CLASSES = {
    "second-look": ("nothing", "email"),     # the batch re-reads the page before a letter says a fact (© now current);
                                             # route plans on stored facts, the lane still checks at send time
    "kit-to-card": ("taylor", "card"),       # the kit DMs or calls a no-site business by nearness and reach; § 5.2
                                             # sends one that isn't strong with a confirmed page to the card lane
    "kit-no-address": ("taylor", "nothing"), # the kit DMs a business on a free builder address (wixsite, godaddysites:
                                             # presence `builder`, so not P2); its proposition is an email one and it
                                             # has no address, so no rule applies
    "no-phone-to-card": ("nothing", "card"), # the kit's pool needs a phone; § 5.2's card lane needs a postal address
    "bounce-to-card": ("nothing", "card"),   # rule 4: an address that bounced goes to the card lane (not built, B54)
    "p0-kit": ("taylor", "nothing"),         # the kit DMs a page-only business the venture gives no proposition (P0:
                                             # presence `unknown`, no site of its own read)
}
DIFFERENCES = {
    "FX_B16": "second-look",
    "FX_C02": "kit-to-card", "FX_C05": "kit-to-card", "FX_C06": "kit-to-card", "FX_N01": "kit-to-card",
    "FX_S04": "kit-to-card", "FX_S12": "kit-to-card", "FX_C03": "kit-to-card", "FX_P2A": "kit-to-card",
    "FX_R01": "kit-to-card", "FX_S01": "kit-to-card", "FX_S02": "kit-to-card", "FX_S03": "kit-to-card",
    "FX_C04": "kit-no-address", "FX_S05": "kit-no-address",
    "FX_S07": "no-phone-to-card",
    "FX_P504": "bounce-to-card",
    "FX_S08": "p0-kit",
}


def rec(**kw):
    base = prospects.record(venture="example", key="place:X1", place_id="X1", name="X",
                            proposition={"id": "P5", "lane": "email", "facts": [{"key": "a"}, {"key": "b"}]},
                            strength={"level": "good"},
                            routes=[{"channel": "email", "value": "a@x.example", "verdict": "high"},
                                    {"channel": "postal", "value": "1 Main St", "verdict": "high"}])
    for k, v in kw.items():
        if isinstance(base.get(k), dict) and isinstance(v, dict):
            base[k].update(v)
        else:
            base[k] = v
    return base


def registry(tmp, boxes=("a@send.example", "b@send.example"), provider="fake"):
    reg = assets.Registry(Path(tmp) / "assets.db")
    assets.seed(reg, "example", provider, ["send.example"], list(boxes))
    return assets.snapshot(reg, "example")


class ThePage(unittest.TestCase):
    def test_the_page_says_what_the_code_says(self):
        if not PAGE.exists():
            self.skipTest(f"{PAGE} isn't on this machine (private-docs/ is in no repo)")
        rules, order = policy.page_rules(PAGE.read_text())
        code, code_order = policy.code_rules()
        self.assertEqual(order, code_order, "the page's 'Read in this order' line isn't policy.ORDER")
        self.assertEqual([n for n, _, _ in rules], list(code_order), "the page lists the rules out of ORDER")
        self.assertEqual(sorted(rules), sorted(code), "a rule's number, lane or decision differs between the page "
                                                      "and lib/policy.py RULES: change VISION, then RULES, then the page")

    def test_a_drift_is_caught(self):
        text = PAGE.read_text() if PAGE.exists() else "\n".join(
            [f"Read in this order: {', '.join(map(str, policy.ORDER))}."] +
            [f"{r.n}. **{r.lane}** — x (decision: {', '.join(r.decision)})" for n in policy.ORDER
             for r in [policy.BY_N[n]]])
        drifted = text.replace("(decision: AA#8)", "(decision: AA#9)")
        self.assertNotEqual(sorted(policy.page_rules(drifted)[0]), sorted(policy.code_rules()[0]))
        moved = text.replace("Read in this order: 1, 6, 7", "Read in this order: 1, 7, 6")
        self.assertNotEqual(policy.page_rules(moved)[1], policy.ORDER)

    def test_every_rule_cites_a_decision(self):
        self.assertEqual(sorted(r.n for r in policy.RULES), [1, 2, 3, 4, 5, 6, 7])
        self.assertEqual(sorted(policy.ORDER), [1, 2, 3, 4, 5, 6, 7])
        for r in policy.RULES:
            self.assertTrue(r.decision and all(d.startswith(("AA#", "SF#")) for d in r.decision), r)
            self.assertIn(r.lane, policy.LANES)


class TheRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cap = policy.capacity_view(registry(self.tmp.name), {}, 4)

    def tearDown(self):
        self.tmp.cleanup()

    def route(self, r, cap="default"):
        return policy.route(r, self.cap if cap == "default" else cap, PROPS)

    def test_rule_1(self):
        for state, why in (({"suppressed": "replied no thanks"}, "suppressed"), ({"stage": "won"}, "a client"),
                           ({"stage": "trialing"}, "a client"), ({"stage": "lost"}, "closed"),
                           ({"held": "a batch in the last 56 days"}, "held"), ({"excluded": "a chain"}, "a chain")):
            p = self.route(rec(state=state))
            self.assertEqual((p["lane"], p["rule"], p["status"]), ("nothing", 1, "none"), state)
            self.assertIn(why, p["reason"])
            self.assertEqual(p["decision"], ["SF#2", "AA#4"])
        p = self.route(rec(proposition={"id": "P0", "lane": None}))
        self.assertEqual((p["lane"], p["rule"]), ("nothing", 1))
        self.assertIn("no proposition", p["reason"])

    def test_rule_6_before_held_and_strength(self):
        text = rec(state={"held": "in the pipeline", "stage": "interested"}, strength={"level": "strong"},
                   conversation={"open": True, "channel": "text", "class": "interested"},
                   consent={"ok": False, "line": "You may not text this number.", "reason": "they asked us to stop"})
        p = self.route(text)
        self.assertEqual((p["lane"], p["rule"], p["handler"]), ("conversation", 6, "consent"))
        self.assertFalse(p["touch"]["may_send"])
        self.assertEqual(p["touch"]["line"], "You may not text this number.")
        email = rec(conversation={"open": True, "channel": "email", "class": "interested"},
                    close={"experiment": "E3", "arm": "B", "open": True})
        p = self.route(email)
        self.assertEqual((p["rule"], p["experiment"], p["arm"]), (6, "E3", "B"))
        email["close"]["open"] = False
        p = self.route(email)
        self.assertEqual((p["rule"], p["arm"], p["touch"]["actor"]), (6, None, "taylor"))
        # a no is suppressed first, conversation or not
        p = self.route(rec(state={"suppressed": "replied no"}, conversation={"open": True, "channel": "email"}))
        self.assertEqual(p["rule"], 1)

    def test_rule_7_never_holds_yet_and_holds_when_told(self):
        p = self.route(rec())
        self.assertIn("rule 7: no hold (downstream capacity isn't measured yet, B145)", p["notes"])
        cap = dict(self.cap, downstream={"hold": True, "why": "three days over budget"})
        p = self.route(rec(), cap)
        self.assertEqual((p["lane"], p["rule"], p["decision"]), ("hold", 7, ["AA#8"]))
        p = self.route(rec(conversation={"open": True, "channel": "email", "class": "question"}), cap)
        self.assertEqual(p["rule"], 6)                            # replies continue under a hold

    def test_rule_2_needs_strong_and_a_confirmed_page(self):
        dm = {"channel": "instagram", "value": "x", "verdict": "high"}
        r = rec(strength={"level": "strong"}, routes=rec()["routes"] + [dm])
        p = self.route(r)
        self.assertEqual((p["lane"], p["rule"], p["asset_kind"]), ("taylor", 2, "taylor"))
        self.assertEqual([(t["n"], t["channel"]) for t in p["sequence"]], [(0, "instagram"), (3, "instagram"),
                                                                          (10, "email")])
        self.assertEqual(p["sequence"][2]["template"], "p5-first")
        self.assertEqual(self.route(dict(r, strength={"level": "good"}))["rule"], 3)
        unsure = rec(strength={"level": "strong"}, routes=rec()["routes"] + [dict(dm, verdict="unsure")])
        self.assertEqual(self.route(unsure)["rule"], 3)

    def test_rule_3_is_the_registrys_choice(self):
        p = self.route(rec())
        self.assertEqual((p["lane"], p["rule"], p["status"], p["asset_kind"]), ("email", 3, "ready", "mailbox"))
        self.assertIn(p["asset"], ("a@send.example", "b@send.example"))
        self.assertEqual(p["touch"]["template"], "p5-first")
        # the same answer assets.plan_tick gives for one first letter
        tick = assets.plan_tick(self.cap["snapshot"], {}, [], [{"id": "place:X1"}], 4)
        self.assertEqual(p["asset"], tick["send"][0]["mailbox"])
        # no PERMITTED contract: the lane is right, and it waits
        with tempfile.TemporaryDirectory() as tmp:
            prohibited = policy.capacity_view(registry(tmp, provider="google-workspace"), {}, 4)
            p = self.route(rec(), prohibited)
        self.assertEqual((p["lane"], p["status"]), ("email", "waiting"))
        self.assertIn("PROHIBITED", p["reason"])
        p = self.route(rec(), None)
        self.assertEqual((p["lane"], p["status"]), ("email", "waiting"))
        self.assertIn("registry wasn't read", p["reason"])
        # caps spent at every mailbox: waiting
        full = {"a@send.example": {"today": 4}, "b@send.example": {"today": 4}}
        p = self.route(rec(), dict(self.cap, usage=full))
        self.assertEqual(p["status"], "waiting")
        # no letter facts, or no admitted address: not the email lane
        self.assertEqual(self.route(rec(proposition={"facts": []}))["lane"], "nothing")
        low = rec(routes=[{"channel": "email", "value": "a@x.example", "verdict": "low"}])
        p = self.route(low)
        self.assertEqual(p["lane"], "nothing")
        self.assertIn("a@x.example: low", p["reason"])

    def test_rule_4_card(self):
        p = self.route(rec(proposition={"id": "P2", "lane": "card", "facts": []}))
        self.assertEqual((p["lane"], p["rule"], p["status"]), ("card", 4, "waiting"))
        bounced = rec(routes=[{"channel": "email", "value": "a@x.example", "verdict": "bounced"},
                              {"channel": "postal", "value": "1 Main St", "verdict": "high"}])
        self.assertEqual(self.route(bounced)["rule"], 4)
        nopost = rec(proposition={"id": "P2", "lane": "card"}, routes=[])
        p = self.route(nopost)
        self.assertEqual(p["lane"], "nothing")
        self.assertIn("no postal address", p["reason"])

    def test_rule_5_form_only(self):
        form = [{"channel": "form", "value": "https://x.example/contact", "verdict": "high"}]
        p = self.route(rec(proposition={"id": "P1", "lane": "email"}, routes=form, strength={"level": "strong"}))
        self.assertEqual((p["lane"], p["rule"], p["touch"]["channel"]), ("taylor", 5, "form"))
        p = self.route(rec(proposition={"id": "P1", "lane": "email"}, routes=form))
        self.assertEqual((p["lane"], p["rule"]), ("nothing", None))
        self.assertIn("a contact form only", p["reason"])

    def test_pure(self):
        r = rec(strength={"level": "strong"})
        before = copy.deepcopy(r)
        a, b = self.route(r), self.route(r)
        self.assertEqual(a, b)
        self.assertEqual(r, before)

    def test_portable_lanes_not_ids(self):
        """Another venture's propositions route by their lanes: no P-number is read by name."""
        other = {"Q7": {"lane": "email", "letters": ("q-first",)}, "Q8": {"lane": "card"}, "Q0": {"lane": None}}
        p = policy.route(rec(proposition={"id": "Q7", "lane": "email"}), self.cap, other)
        self.assertEqual((p["rule"], p["proposition"], p["touch"]["template"]), (3, "Q7", "q-first"))
        self.assertEqual(policy.route(rec(proposition={"id": "Q8", "lane": "card"}), self.cap, other)["rule"], 4)
        self.assertEqual(policy.route(rec(proposition={"id": "Q0"}), self.cap, other)["rule"], 1)
        src = (Path(policy.__file__)).read_text()
        for pid in ("P1", "P2", "P3", "P4", "P5", "P6"):
            self.assertNotIn(f'"{pid}"', src)


class NoDrift(unittest.TestCase):
    """The fixture world: the CLIs today, the records, and route() against both."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.world = pc.build_world(cls.tmp.name)
        cls.captured = pc.capture(cls.world)
        pc.run(cls.world, pc.LEADS, "prospects", "rebuild")
        cls.store = prospects.Store(cls.world["env"]["PROSPECTS_DB"], venture="patchlamp")
        cls.records = {r["place_id"]: r for r in cls.store.all() if r.get("place_id")}
        snap = registry(cls.tmp.name + "/r", boxes=("a@send.example", "b@send.example"))
        cls.cap = policy.capacity_view(snap, {}, 5)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_clis_still_decide_what_they_decided(self):
        golden = json.loads(pc.GOLDEN.read_text())
        self.assertEqual(self.captured, golden, "a CLI decides differently than tests/fixtures/policy/today.json: "
                         "if that is intended, `python3 tests/policy_capture.py --write` and read the diff")

    def test_route_agrees_with_the_clis_except_where_named(self):
        golden = json.loads(pc.GOLDEN.read_text())
        compared, differ = 0, {}
        for pid, g in golden.items():
            r = self.records.get(pid)
            if r is None:
                self.assertEqual(g["lane"], "nothing", f"{pid} has no record (closed on Google) but a CLI acts on it")
                continue
            compared += 1
            p = policy.route(r, self.cap)
            same = p["lane"] == g["lane"] and (p["lane"] != "email" or p["proposition"] == g["batch"])
            if not same:
                differ[pid] = (g["lane"], p["lane"])
        self.assertGreaterEqual(compared, 50)
        self.assertEqual(sorted(differ), sorted(DIFFERENCES),
                         f"route() and today's CLIs differ on businesses DIFFERENCES doesn't name (or agree on one it "
                         f"does): {differ}")
        for pid, cls in DIFFERENCES.items():
            self.assertEqual(differ[pid], CLASSES[cls], f"{pid}: not the {cls} difference")

    def test_every_rule_but_7_and_5_is_exercised(self):
        rules = {policy.route(r, self.cap)["rule"] for r in self.records.values()}
        self.assertTrue({1, 2, 3, 4, 6} <= rules, rules)

    def test_the_record_has_its_footing_and_sources(self):
        r = self.records["FX_P4A"]
        self.assertEqual(r["proposition"]["id"], "P4")
        self.assertTrue(all(f["evidence"] for f in r["proposition"]["facts"]))
        self.assertTrue(all(f["evidence"] and f["footing"] for f in r["facts"]))
        self.assertEqual({k for k in r["outcomes"]}, set(prospects.FUNNEL))
        self.assertEqual(r["venture"], "patchlamp")
        self.assertIn("identity", r["footing"])
        self.assertEqual([x["verdict"] for x in self.records["FX_B15"]["routes"] if x["channel"] == "email"],
                         ["duplicate"])
        self.assertEqual([x["verdict"] for x in self.records["FX_P504"]["routes"] if x["channel"] == "email"],
                         ["bounced"])
        self.assertIsNone(self.records["FX_P504"]["state"]["suppressed"])        # a bounce refuses the address only
        self.assertEqual(self.records["FX_P502"]["state"]["suppressed"], "replied no thanks")
        self.assertEqual(self.records["FX_P503"]["touches"][0]["template"], "p5-first")
        self.assertEqual(self.records["FX_P503"]["outcomes"]["delivered"], pc._day(5))
        s11 = self.records["FX_S11"]
        self.assertEqual((s11["conversation"]["channel"], s11["consent"]["governed"]), ("text", False))


class SharedSites(unittest.TestCase):
    """`shared_site_places`: three listings on one organisation's domain are a chain; three Facebook pages (or any
    platform or directory host) are three businesses (B140, Flint 2026-10-08)."""

    def test_a_facebook_trio_is_admitted_and_a_real_shared_domain_refused(self):
        import sqlite3
        import test_leads_batch as tlb
        with tempfile.TemporaryDirectory() as tmp:
            world = pc.build_world(tmp)
            conn = sqlite3.connect(world["db"])
            for i in range(3):
                conn.execute("INSERT INTO place_cache (place_id, name, website) VALUES (?, ?, ?)",
                             (f"FX_CH{i}", f"Bigchain {i}", f"https://www.bigchain.example/store-{i}"))
            conn.commit()
            conn.close()
            L = tlb.leads_module(world["env"])
            got = L.shared_site_places()
        self.assertEqual({p for p in got if p.startswith("FX_CH")}, {"FX_CH0", "FX_CH1", "FX_CH2"})
        for pid in ("FX_S01", "FX_C03", "FX_R01"):          # three listings linking their own Facebook pages
            self.assertNotIn(pid, got)
        self.assertTrue(L.shared_host_is_a_platform("https://m.facebook.com/x"))
        self.assertTrue(L.shared_host_is_a_platform("https://www.thumbtack.com/ut/x"))
        self.assertFalse(L.shared_host_is_a_platform("https://bigchain.example/"))


class TheStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.world = pc.build_world(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_table_is_built_on_first_read_and_hooks_write_through(self):
        db = Path(self.world["env"]["PROSPECTS_DB"])
        self.assertFalse(db.exists())
        out = pc.run(self.world, pc.LEADS, "prospects", "route", "Pine 9 Plumbing", "--json").stdout
        self.assertTrue(db.exists())
        self.assertEqual(json.loads(out)["lane"], "email")
        st = prospects.Store(db, venture="patchlamp")
        n = st.count()
        pc.run(self.world, pc.LEADS, "log", "Pine 9 Plumbing", "messaged", "a DM", "--channel", "instagram",
               "--place", "FX_P509")
        r = st.by_place("FX_P509")
        self.assertEqual(r["state"]["stage"], "contacted")
        self.assertEqual(r["touches"][-1]["channel"], "instagram")
        self.assertEqual(st.count(), n)
        pc.run(self.world, pc.OUTREACH, "suppress", "add", "FX_P508", "--reason", "replied no thanks")
        self.assertEqual(st.by_place("FX_P508")["state"]["suppressed"], "replied no thanks")
        self.assertEqual(json.loads(pc.run(self.world, pc.LEADS, "prospects", "route", "FX_P508", "--json")
                                    .stdout)["rule"], 1)
        # a rebuild from the logs comes to the same records
        before = {r["key"]: r for r in st.all()}
        pc.run(self.world, pc.LEADS, "prospects", "rebuild")
        after = {r["key"]: r for r in st.all()}
        self.assertEqual(after["place:FX_P508"]["state"], before["place:FX_P508"]["state"])
        self.assertEqual(after["place:FX_P509"]["state"]["stage"], "contacted")

    def test_ls_and_show(self):
        out = pc.run(self.world, pc.LEADS, "prospects", "ls").stdout
        self.assertIn("by the lane lib/policy.py routes them to", out)
        self.assertRegex(out, r"email\s+rule 3\s+\d+")
        out = pc.run(self.world, pc.LEADS, "prospects", "show", "Aspen Plumbing").stdout
        self.assertIn("proposition P4", out)
        self.assertIn("route email: info@aspenplumbing.example (high", out)

    def test_ventures_are_kept_apart(self):
        db = Path(self.tmp.name) / "p.db"
        a, b = prospects.Store(db, venture="one"), prospects.Store(db, venture="two")
        a.rebuild([prospects.record(key="place:1", place_id="1", name="A")])
        b.rebuild([prospects.record(key="place:2", place_id="2", name="B")])
        self.assertEqual([r["name"] for r in a.all()], ["A"])
        self.assertEqual([r["name"] for r in b.all()], ["B"])
        self.assertIsNone(a.by_place("2"))

    def test_note_never_raises(self):
        os.environ["PROSPECTS_DB"], saved = "/nonexistent/dir/x.db", os.environ.get("PROSPECTS_DB")
        try:
            self.assertIsNone(prospects.note("event", {"key": "place:1", "place_id": "1"}))
            self.assertIsNone(prospects.note("nonsense", {}))
        finally:
            os.environ["PROSPECTS_DB"] = saved


if __name__ == "__main__":
    unittest.main()
