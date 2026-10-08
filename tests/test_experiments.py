"""B142: the funnel counted by business, and the experiments registry (plan 55 § 5.6).

    python3 -m unittest tests.test_experiments   (from claude-tools/)

The registry is the venture's (ventures/<name>/experiments.json, read by lib/experiments.py); the rows are fixtures
written here (outreach's sends and replies, a pipeline), so no real lead, mailbox or ledger is read. What's checked:
a business counts once at each stage however many events it has; `leads week --by actor` and `outreach status --by
experiment E1` print the seven stages and "too few to decide" under the floor; a cut that isn't a whole-population
dimension or a registered experiment is refused with the reason, and two experiments are never crossed (the
sequencing doctrine); E1's stages past its primary endpoint are bracketed and split by E3's arm.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent / "lib"))

import datetime as dt  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

import experiments as X  # noqa: E402
import venture  # noqa: E402

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
OUTREACH = TOOLS / "bin" / "outreach"
REG_FILE = TOOLS / "ventures" / "patchlamp" / "experiments.json"
DAY = "2026-10-08"


def send(i, arm=None, day="2026-10-05", touch=0, **extra):
    r = {"ts": f"{day}T09:00:00-06:00", "date": day, "touch": touch, "place_id": f"PX{i}", "email": f"o{i}@x.example",
         "batch_id": "b1", "provider": "fake", "mailbox": "a@send.example", "channel": "email", "actor": "machine",
         "asset": "a@send.example", "segment": "services"}
    if arm:
        r.update(proposition=arm, proposition_experiment="E1", proposition_arm=arm)
    r.update(extra)
    return r


def event(i, outcome, day, **extra):
    return dict({"ts": f"{day}T10:00:00-06:00", "date": day, "key": f"place:PX{i}", "place_id": f"PX{i}",
                 "name": f"Business {i}", "outcome": outcome}, **extra)


def reply(i, cls, day="2026-10-06", **extra):
    return dict({"date": day, "place_id": f"PX{i}", "email": f"o{i}@x.example", "class": cls}, **extra)


class Registry(unittest.TestCase):
    def setUp(self):
        self.reg = X.load(REG_FILE)

    def test_the_three_q4_experiments_are_registered_with_everything_the_row_names(self):
        self.assertEqual(["E1", "E2", "E3"], list(self.reg))
        for e in self.reg.values():
            for k in ("population", "varied", "arms", "start", "kill_rule", "decision_owner", "primary_endpoint"):
                self.assertTrue(e[k], k)
        self.assertEqual(("positive", "positive", "paid"), tuple(self.reg[e]["primary_endpoint"] for e in self.reg))
        self.assertEqual(["P5", "P6"], self.reg["E1"]["arms"])
        self.assertEqual(["none", "intro", "foot"], self.reg["E2"]["arms"])     # three, as Taylor approved B132
        self.assertEqual(["A", "B"], self.reg["E3"]["arms"])
        # E1's and E3's arms are written under different names, so a reply row can carry both
        self.assertNotEqual(self.reg["E1"]["fields"]["arm"], self.reg["E3"]["fields"]["arm"])

    def test_doctrine_e3_waits_for_e1_and_e2_and_e1_e2_are_never_crossed(self):
        self.assertEqual(["E3"], X.downstream(self.reg, "E1"))
        self.assertEqual(["E3"], X.downstream(self.reg, "E2"))
        self.assertEqual([], X.downstream(self.reg, "E3"))
        self.assertTrue(X.crossed(self.reg, "E1", "E2"))
        self.assertFalse(X.crossed(self.reg, "E1", "E3"))

    def test_propositions_deal_from_the_registry(self):
        """The venture's propositions read E1 from experiments.json, so the two can't drift apart."""
        spec = importlib.util.spec_from_file_location("props_b142", REG_FILE.parent / "propositions.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(["E1"], list(mod.EXPERIMENTS))
        self.assertEqual(tuple(self.reg["E1"]["arms"]), mod.EXPERIMENTS["E1"]["arms"])
        self.assertEqual(self.reg["E1"]["kill_rule"], mod.EXPERIMENTS["E1"]["kill_rule"])

    def test_a_venture_with_no_file_has_an_empty_registry(self):
        venture._cache.clear()
        v = venture.load(HERE / "fixtures" / "ventures" / "example" / "venture.toml")
        self.assertEqual({}, X.registry(v))

    def test_a_bad_registry_names_the_file_and_the_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "experiments.json"
            good = json.loads(REG_FILE.read_text())
            for breaks, says in ((lambda e: e.pop("kill_rule"), "missing kill_rule"),
                                 (lambda e: e.update(primary_endpoint="vibes"), "isn't a stage"),
                                 (lambda e: e.update(arms=["only"]), "two or more"),
                                 (lambda e: e.update(fields={"arm": "x"}), "fields need"),
                                 (lambda e: e.update(start="soon"), "isn't a date")):
                data = json.loads(json.dumps(good))
                breaks(data["experiments"]["E1"])
                p.write_text(json.dumps(data))
                with self.assertRaises(X.RegistryError) as cm:
                    X.load(p)
                self.assertIn(says, cm.exception.msg)
                self.assertIn("E1", cm.exception.msg)


class Cuts(unittest.TestCase):
    def setUp(self):
        self.reg = X.load(REG_FILE)

    def test_whole_population_dimensions_and_registered_experiments_are_cuts(self):
        for d in ("channel", "actor", "proposition", "segment", "provider", "asset", "strength"):
            self.assertEqual(("dim", d), (X.resolve_cut([d], self.reg).kind, X.resolve_cut([d], self.reg).name))
        self.assertEqual("E1", X.resolve_cut(["experiment", "E1"], self.reg).eid)
        self.assertEqual("E1", X.resolve_cut(["E1"], self.reg).eid)
        self.assertEqual("E2", X.resolve_cut(["variant"], self.reg).eid)         # B132's view is E2's arms
        self.assertEqual("E3", X.resolve_cut(["arm"], self.reg).eid)             # B137's view is E3's arms

    def test_an_unregistered_cut_is_refused_with_the_reason(self):
        with self.assertRaises(X.Refused) as cm:
            X.resolve_cut(["mood"], self.reg)
        self.assertIn("nothing varies it on purpose", str(cm.exception))
        self.assertIn("the cuts are", str(cm.exception))
        with self.assertRaises(X.Refused) as cm:
            X.resolve_cut(["experiment", "E9"], self.reg)
        self.assertIn("E9 isn't a registered experiment", str(cm.exception))
        with self.assertRaises(X.Refused):
            X.resolve_cut(["experiment", "E1"], {})                     # a venture with none registered

    def test_two_experiments_are_never_crossed_and_the_reason_is_the_doctrine(self):
        with self.assertRaises(X.Refused) as cm:
            X.resolve_cut(["experiment", "E1", "E3"], self.reg)
        msg = str(cm.exception)
        self.assertIn("sequencing doctrine", msg)
        self.assertIn("E1's primary endpoint (positive)", msg)
        self.assertIn("split by E3's arm", msg)
        with self.assertRaises(X.Refused) as cm:
            X.resolve_cut(["variant", "proposition_arm"], self.reg)     # E2 × E1
        self.assertIn("never to cross", str(cm.exception))
        with self.assertRaises(X.Refused) as cm:
            X.resolve_cut(["actor", "segment"], self.reg)
        self.assertIn("one dimension a cut", str(cm.exception))


class Businesses(unittest.TestCase):
    def setUp(self):
        self.reg = X.load(REG_FILE)

    def test_a_lead_with_three_events_counts_once_at_every_stage(self):
        sends = [send(1, "P5"), send(1, "P5", day="2026-10-06", touch=3)]
        events = [event(1, "messaged", "2026-10-05", channel="email", outbound={"proposition": "P5"}),
                  event(1, "messaged", "2026-10-06", channel="email", outbound={"proposition": "P5"}),
                  event(1, "talked", "2026-10-07"), event(1, "interested", "2026-10-07"),
                  event(1, "interested", "2026-10-08")]
        b = X.businesses(sends=sends, replies=[reply(1, "interested")], events=events, today=DAY, reg=self.reg)
        self.assertEqual(["PX1"], list(b))
        cells = X.count(b, lambda x: x["dims"]["actor"], DAY)
        self.assertEqual({"delivered": 1, "reply": 1, "positive": 1, "trial": 0, "activated": 0, "paid": 0,
                          "retained_30": 0, "retained_90": 0}, cells["machine"]["all"])
        self.assertEqual("P5", b["PX1"]["arms"]["E1"])

    def test_a_bounce_is_not_delivered_and_a_paid_business_fills_the_stages_before_it(self):
        b = X.businesses(sends=[send(1), send(2), send(3)],
                         replies=[reply(1, "bounce"), reply(3, "out of office")],
                         events=[event(2, "won", "2026-10-07")], today=DAY, reg=self.reg)
        self.assertIsNone(b["PX1"]["stages"]["delivered"])
        st = b["PX2"]["stages"]
        self.assertEqual(["2026-10-05", "2026-10-07", "2026-10-07", "2026-10-07", None, "2026-10-07"],
                         [st[s] for s in ("delivered", "reply", "positive", "trial", "activated", "paid")])
        self.assertIsNone(b["PX3"]["stages"]["reply"])                        # out of office isn't an answer

    def test_retained_is_thirty_and_ninety_days_on_without_a_churn(self):
        events = [event(1, "messaged", "2026-06-01", channel="instagram"), event(1, "won", "2026-06-10"),
                  event(2, "messaged", "2026-06-01", channel="facebook"), event(2, "won", "2026-06-10"),
                  event(2, "churned", "2026-08-01")]
        b = X.businesses(events=events, today=DAY)
        self.assertEqual(("2026-07-10", "2026-09-08"), (b["PX1"]["stages"]["retained_30"],
                                                        b["PX1"]["stages"]["retained_90"]))
        self.assertEqual(("2026-07-10", None), (b["PX2"]["stages"]["retained_30"], b["PX2"]["stages"]["retained_90"]))
        self.assertEqual(("person", "dm"), (b["PX1"]["dims"]["actor"], b["PX1"]["dims"]["lane"]))

    def test_e1_past_positive_is_bracketed_and_split_by_e3_never_read_as_e1s_result(self):
        sends = [send(i, "P5" if i % 2 == 0 else "P6") for i in range(6)]
        replies = [reply(0, "interested", experiment_id="E3", arm="B"),
                   reply(1, "interested", experiment_id="E3", arm="A")]
        b = X.businesses(sends=sends, replies=replies, events=[event(0, "won", "2026-10-07")], today=DAY,
                         reg=self.reg)
        out = "\n".join(X.render_experiment(b, "E1", self.reg, upto=DAY))
        for h in ("delivered", "reply", "positive", "trial", "activated", "paid", "retained 30/90"):
            self.assertIn(h, out)
        self.assertIn("P5: too few to decide (3 delivered of 100)", out)
        self.assertIn("Stages past positive are bracketed", out)
        self.assertRegex(out, r"P5\s+3\s+1 \(33\.3\)\s+1 \(33\.3\)\s+\[1 \(33\.3\)\]")
        self.assertIn("E1 past positive, split by E3", out)
        self.assertIn("[P5 · E3 B: positive 1, trial 1, activated 0, paid 1", out)
        self.assertIn("never E1's result", out)

    def test_a_business_in_both_e1_and_e2_is_called_out(self):
        s = send(1, "P5", ai_test="2026-10-07T09:00:00", variant="none")
        b = X.businesses(sends=[s], today=DAY, reg=self.reg)
        self.assertIn("Crossed: 1 business is in both E1 and E2", "\n".join(X.render_experiment(b, "E1", self.reg, DAY)))

    def test_the_kill_rule_reports_and_never_acts(self):
        sends, replies = [], []
        for i in range(400):
            arm = "P5" if i < 200 else "P6"
            sends.append(send(i, arm))
            if (arm == "P5" and i < 40) or (arm == "P6" and i < 210):
                replies.append(reply(i, "interested"))
        b = X.businesses(sends=sends, replies=replies, today=DAY, reg=self.reg)
        out = "\n".join(X.render_experiment(b, "E1", self.reg, DAY))
        self.assertIn("P5: 200 delivered, past the floor", out)
        self.assertIn("Kill rule crossed for P6", out)
        self.assertIn("Taylor's word; nothing here pauses it", out)

    def test_cost_by_lane_reads_the_ledger_and_says_what_each_includes(self):
        ledger = [{"ts": "2026-10-06T10:00:00+00:00", "tool": "outreach", "kind": "claude", "cost_usd": 0.2},
                  {"ts": "2026-10-06T10:00:00+00:00", "kind": "infra", "phase": "commit", "venture": "patchlamp",
                   "cost_usd": 12.0},
                  {"ts": "2026-10-06T10:00:00+00:00", "kind": "infra", "phase": "intent", "venture": "patchlamp",
                   "cost_usd_planned": 12.0},
                  {"ts": "2026-10-06T10:00:00+00:00", "kind": "infra", "phase": "commit", "venture": "other",
                   "cost_usd": 99.0},
                  {"ts": "2026-10-06T10:00:00+00:00", "tool": "leads", "kind": "places_details", "cost_usd": 0.6,
                   "for": "remote services 2026-10-06"},
                  {"ts": "2026-10-06T10:00:00+00:00", "tool": "leads", "kind": "places_details", "cost_usd": 0.4,
                   "for": "batch 2026-10-06 services"},
                  {"ts": "2026-10-06T10:00:00+00:00", "tool": "leads", "kind": "places_details", "cost_usd": 0.1,
                   "for": "brief Business 1"}]
        self.assertEqual({"email": 12.6, None: 0.1, "dm": 0.6},
                         {k: round(v, 2) for k, v in X.costs(ledger, "patchlamp", "2026-10-05", DAY).items()})
        b = X.businesses(sends=[send(1), send(2)], replies=[reply(1, "interested")], today=DAY)
        out = "\n".join(X.render_costs(b, ledger, "patchlamp", DAY, "2026-10-05"))
        self.assertIn("email $12.60 this week, 1 conversation → $12.60 a conversation", out)
        self.assertIn("no paid client yet", out)
        self.assertIn("includes the reply classifier", out)


class Tools(unittest.TestCase):
    """The two commands, end to end on fixture rows."""

    def setUp(self):
        self.t = Path(tempfile.mkdtemp(prefix="b142-"))
        self.addCleanup(shutil.rmtree, self.t, ignore_errors=True)
        (self.t / "out").mkdir()
        sends, replies, events = [], [], []
        for i in range(8):
            arm = "P5" if i % 2 == 0 else "P6"
            sends += [send(i, arm), send(i, arm, day="2026-10-06", touch=3)]
            events.append(event(i, "messaged", "2026-10-05", channel="email", strength="good",
                                outbound={"proposition": arm, "actor": "machine"}))
        events += [event(0, "talked", "2026-10-07"), event(0, "interested", "2026-10-07"), event(0, "won", "2026-10-08")]
        replies += [reply(0, "interested", experiment_id="E3", arm="B"), reply(2, "bounce")]
        events += [event(20, "messaged", "2026-10-06", channel="instagram"), event(20, "talked", "2026-10-07"),
                   event(20, "later", "2026-10-07")]
        for name, rows in (("sends.jsonl", sends), ("replies.jsonl", replies)):
            (self.t / "out" / name).write_text("".join(json.dumps(r) + "\n" for r in rows))
        (self.t / "pipeline.jsonl").write_text("".join(json.dumps(r) + "\n" for r in events))
        (self.t / "ledger.jsonl").write_text("")
        self.env = {k: v for k, v in os.environ.items()}
        self.env.update(HOME=str(self.t), CLAUDE_TOOLS_ENV=os.devnull, OUTREACH_STATE=str(self.t / "out"),
                        OUTREACH_LEDGER=str(self.t / "ledger.jsonl"), LEADS_LEDGER=str(self.t / "ledger.jsonl"),
                        LEADS_PIPELINE=str(self.t / "pipeline.jsonl"), LEADS_PREVIEWS=str(self.t / "previews"),
                        LEADS_STATE=str(self.t / "ls"), OUTREACH_NOW=f"{DAY}T12:00:00", LEADS_NOW=DAY,
                        LEADS_DB=str(self.t / "none.db"))
        self.env.pop("VENTURE", None)

    def run_tool(self, tool, *args):
        return subprocess.run([sys.executable, str(TOOLS / "bin" / tool), *args], capture_output=True, text=True,
                              env=self.env, timeout=120)

    def test_leads_week_by_actor_counts_businesses(self):
        r = self.run_tool("leads", "week", "--by", "actor")
        self.assertEqual(0, r.returncode, r.stderr)
        rows = {l.split()[0]: l for l in r.stdout.splitlines() if l.startswith("  ") and l.split()[0] in
                ("machine", "person")}
        # eight letters (two sends each), one bounced: 7 delivered; PX0 talked, was interested and paid: once each
        self.assertRegex(rows["machine"], r"machine\s+7 \+7\s+1 \(14\.3\) \+1\s+1 \(14\.3\) \+1\s+1 \(14\.3\) \+1\s+"
                                          r"0 \(0\.0\)\s+1 \(14\.3\) \+1\s+0/0")
        # the DM lead's three events (messaged, talked, later) are one business, one reply
        self.assertRegex(rows["person"], r"person\s+1 \+1\s+1 \(100\.0\) \+1\s+0 \(0\.0\)")
        self.assertIn("Too few to decide", r.stdout)
        self.assertIn("Cost by lane", r.stdout)
        j = json.loads(self.run_tool("leads", "week", "--by", "actor", "--json").stdout)
        self.assertEqual(7, j["cells"]["machine"]["all"]["delivered"])

    def test_leads_week_keeps_the_channel_view_and_refuses_an_unregistered_cut(self):
        r = self.run_tool("leads", "week", "--by", "mood")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("not a cut — mood isn't a cut", r.stderr)
        r = self.run_tool("leads", "week", "--by", "experiment", "E1", "E3")
        self.assertNotEqual(0, r.returncode)
        self.assertIn("sequencing doctrine", r.stderr)
        r = self.run_tool("leads", "week", "--by", "experiment", "E1")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("P5: too few to decide (3 delivered of 100)", r.stdout)

    def test_outreach_status_by_experiment_e1_prints_the_seven_stages_per_arm(self):
        r = self.run_tool("outreach", "status", "--by", "experiment", "E1")
        self.assertEqual(0, r.returncode, r.stderr)
        out = r.stdout
        self.assertIn("E1 the frame — P5 vs P6", out)
        header = next(l for l in out.splitlines() if l.strip().startswith("arm"))
        self.assertEqual(["arm", "delivered", "reply", "positive", "trial", "activated", "paid", "retained", "30/90"],
                         header.split())
        self.assertRegex(out, r"\n  P5\s+3\s+1 \(33\.3\)\s+1 \(33\.3\)\s+\[1 \(33\.3\)\]\s+\[0 \(0\.0\)\]\s+"
                              r"\[1 \(33\.3\)\]\s+\[0/0\]")
        self.assertRegex(out, r"\n  P6\s+4\s+0 \(0\.0\)")
        self.assertIn("P5: too few to decide (3 delivered of 100)  |  P6: too few to decide (4 delivered of 100)", out)
        self.assertIn("[P5 · E3 B: positive 1, trial 1, activated 0, paid 1", out)
        self.assertIn("activated (the free week by card) reads 0", out)

    def test_outreach_status_refuses_an_unregistered_cut_with_the_reason(self):
        for args, says in ((("mood",), "mood isn't a cut"), (("experiment", "E9"), "E9 isn't a registered experiment"),
                           (("experiment", "E1", "E3"), "sequencing doctrine"),
                           (("variant", "segment"), "one dimension a cut")):
            r = self.run_tool("outreach", "status", "--by", *args)
            self.assertEqual(2, r.returncode, (args, r.stdout, r.stderr))
            self.assertIn(says, r.stderr)
            self.assertEqual("", r.stdout)

    def test_outreach_status_by_actor_and_the_old_views_still_answer(self):
        r = self.run_tool("outreach", "status", "--by", "actor")
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertRegex(r.stdout, r"\n  machine\s+7\s")
        self.assertNotRegex(r.stdout, r"\n  person\s")       # a DM-only lead isn't this lane's
        for old in ("variant", "segment", "fault", "letter", "prebuilt", "proposition", "arm"):
            r = self.run_tool("outreach", "status", "--by", old)
            self.assertEqual(0, r.returncode, (old, r.stderr))


if __name__ == "__main__":
    unittest.main()
