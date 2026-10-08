"""The capacity registry (ROADMAP B141, plan 55 § 5.3): lib/assets.py and `outreach assets`.

    python3 -m unittest tests.test_assets   (from claude-tools/)

Nothing here reaches the network: RDAP is a loopback stand-in or off, and the outreach runs use a temp
state dir, so the registry they seed is the test's own.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent / "lib"))

import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import unittest  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402
from pathlib import Path  # noqa: E402

import assets  # noqa: E402

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
OUTREACH = TOOLS / "bin" / "outreach"
T = "acme"                     # a tenant name that is nobody's


def lane(reg, provider="p1", verdict="PERMITTED", domain="one.example", boxes=("a@one.example", "b@one.example"),
         tenant=T, state="active"):
    """A provider with a verdict, a tenant, one domain and its mailboxes, all `state`."""
    pid = reg.ensure(tenant, "provider", provider, contract=verdict, clause="test clause", clause_date="2026-10-08")
    tid = reg.ensure(tenant, "tenant", f"{tenant}-at-{provider}", parent_id=pid)
    did = reg.ensure(tenant, "domain", domain, parent_id=tid)
    for b in boxes:
        reg.ensure(tenant, "mailbox", b, parent_id=did, state=state)
    return pid


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="assets-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.reg = assets.Registry(self.tmp / "assets.db")

    def snap(self, tenant=T):
        return assets.snapshot(self.reg, tenant)


class SeedTest(Base):
    def test_the_lane_enters_at_four_levels_once(self):
        boxes = ["x@send.example", "y@send.example", "z@send.example"]
        for _ in range(2):
            assets.seed(self.reg, T, "google-workspace", ["send.example"], boxes)
        rows = self.reg.rows(T)
        self.assertEqual(sorted(r["kind"] for r in rows), ["domain", "mailbox", "mailbox", "mailbox", "provider", "tenant"])
        prov = next(r for r in rows if r["kind"] == "provider")
        self.assertEqual(prov["contract"], "PROHIBITED")
        self.assertIn("unsolicited mass email", prov["clause"])
        self.assertEqual(prov["clause_date"], "2026-10-07")
        self.assertIn("whole Workspace account", prov["suspension_scope"])
        snap = self.snap()
        for mb in snap["mailboxes"]:
            self.assertEqual([k for k, _, _ in assets.chain_states(mb)], ["mailbox", "domain", "tenant", "provider"])
            self.assertFalse(assets.first_touch_ok(mb)[0])
            self.assertIn("PROHIBITED", assets.first_touch_ok(mb)[1])
            self.assertFalse(assets.follow_up_ok(mb)[0])

    def test_seed_keeps_what_was_set_and_tenants_stay_apart(self):
        assets.seed(self.reg, T, "google-workspace", ["send.example"], ["x@send.example"])
        mb = self.reg.find(T, "x@send.example")
        self.reg.set_fields(mb["id"], cap_day=3)
        self.reg.set_state(mb["id"], "paused", "by hand")
        assets.seed(self.reg, T, "google-workspace", ["send.example"], ["x@send.example"])
        mb = self.reg.find(T, "x@send.example")
        self.assertEqual((mb["cap_day"], mb["state"]), (3, "paused"))
        assets.seed(self.reg, "other", "fake", ["else.example"], ["q@else.example"])
        self.assertEqual({r["name"] for r in self.reg.rows("other") if r["kind"] == "mailbox"}, {"q@else.example"})
        with self.assertRaises(assets.AssetError):
            self.reg.find("other", "x@send.example")

    def test_an_unknown_provider_is_unreviewed_and_sends_nothing(self):
        assets.seed(self.reg, T, "smtp:mail.example", [], ["x@send.example"])
        mb = self.snap()["mailboxes"][0]
        self.assertEqual(assets.verdict(mb), "unreviewed")
        self.assertFalse(assets.first_touch_ok(mb)[0])
        self.assertTrue(any("no contract verdict" in w for w in assets.warnings(self.snap())))


class LifecycleTest(Base):
    def test_transitions_and_retire_with_open_threads(self):
        lane(self.reg)
        mb = self.reg.find(T, "a@one.example")
        with self.assertRaises(assets.AssetError) as cm:
            self.reg.set_state(mb["id"], "provisioning", "back")
        self.assertIn("not provisioning", str(cm.exception))
        self.reg.set_state(mb["id"], "draining", "reputation")
        with self.assertRaises(assets.AssetError) as cm:
            self.reg.set_state(mb["id"], "retired", "done", open_threads=2)
        self.assertIn("2 open thread(s)", str(cm.exception))
        self.reg.set_state(mb["id"], "retired", "done", open_threads=0)
        with self.assertRaises(assets.AssetError):
            self.reg.set_state(mb["id"], "active", "again")
        log = [(e["from_state"], e["to_state"]) for e in self.reg.events(asset_id=mb["id"])][::-1]
        self.assertEqual(log, [(None, "active"), ("active", "draining"), ("draining", "retired")])

    def test_cascade_reaches_the_mailboxes(self):
        lane(self.reg)
        d = self.reg.find(T, "one.example")
        changed = self.reg.set_state(d["id"], "paused", "test", cascade=True)
        self.assertEqual(sorted(n for _, n, _, _ in changed), ["a@one.example", "b@one.example", "one.example"])

    def test_sync_pauses_mirrors_the_lane_and_lifts_back(self):
        lane(self.reg)
        assets.sync_pauses(self.reg, T, {"a@one.example": {"why": "angry reply from x@y.example"}})
        a = self.reg.find(T, "a@one.example")
        self.assertEqual(a["state"], "paused")
        self.assertIn("angry reply", a["state_why"])
        assets.sync_pauses(self.reg, T, {})
        self.assertEqual(self.reg.find(T, "a@one.example")["state"], "active")
        # a pause set by hand isn't lifted by the lane's file
        b = self.reg.find(T, "b@one.example")
        self.reg.set_state(b["id"], "paused", "Taylor, by hand")
        assets.sync_pauses(self.reg, T, {})
        self.assertEqual(self.reg.find(T, "b@one.example")["state"], "paused")


class RulesTest(Base):
    def test_a_paused_mailboxs_follow_ups_wait_then_go_first(self):
        """The acceptance: a paused mailbox's follow-ups move by the rule — held in their due order while it is
        paused (never moved to another sender), first letters go round the others, and on resume its
        follow-ups go before any first letter."""
        lane(self.reg, boxes=("a@one.example", "b@one.example", "c@one.example"))
        a = self.reg.find(T, "a@one.example")
        self.reg.set_state(a["id"], "paused", "the lane's pause rule: angry reply")
        follow = [{"id": "f2", "mailbox": "a@one.example", "due": "2026-10-09"},
                  {"id": "f1", "mailbox": "a@one.example", "due": "2026-10-08"},
                  {"id": "fb", "mailbox": "b@one.example", "due": "2026-10-08"}]
        fresh = [{"id": "n1"}, {"id": "n2"}, {"id": "n3"}]
        # two contracts' worth isn't needed here: cap 10 a box, 30 in all, half is 15
        plan = assets.plan_tick(self.snap(), {}, follow, fresh, default_cap=10)
        sent = [(s["mailbox"], s["id"], s["kind"]) for s in plan["send"]]
        self.assertIn(("b@one.example", "fb", "follow"), sent)
        self.assertNotIn("a@one.example", {m for m, _, _ in sent})
        self.assertEqual([h["id"] for h in plan["held"]], ["f1", "f2"])
        self.assertTrue(all("paused" in h["why"] and "go first when it is resumed" in h["why"] for h in plan["held"]))
        self.assertIn(("c@one.example", "n1", "first"), sent)          # b's slot went to its follow-up
        self.assertEqual([w["id"] for w in plan["waiting"]], ["n2", "n3"])
        # resumed: the oldest follow-up goes from its own mailbox, ahead of every first letter
        self.reg.set_state(a["id"], "active", "resumed")
        plan = assets.plan_tick(self.snap(), {}, follow, fresh, default_cap=10)
        self.assertEqual(plan["send"][0], {"mailbox": "a@one.example", "id": "f1", "kind": "follow"})
        self.assertEqual(plan["send"][1]["kind"], "follow")
        self.assertEqual([h["id"] for h in plan["held"]], ["f2"])     # one letter a mailbox a tick
        self.assertEqual([(s["mailbox"], s["kind"]) for s in plan["send"][2:]], [("c@one.example", "first")])

    def test_a_contract_at_half_refuses_a_new_first_letter(self):
        """The acceptance: two contracts, 20 + 10 = 30 first letters of capacity; the first has carried 15
        (half) today, so its mailbox — with room under its own cap — is refused, and the other takes it."""
        lane(self.reg, provider="big", domain="big.example", boxes=("a@big.example",))
        lane(self.reg, provider="small", domain="small.example", boxes=("b@small.example",))
        self.reg.set_fields(self.reg.find(T, "a@big.example")["id"], cap_day=20)
        usage = {"a@big.example": {"today": 15, "first_today": 15}}
        plan = assets.plan_tick(self.snap(), usage, [], [{"id": "n1"}, {"id": "n2"}], default_cap=10)
        self.assertEqual(plan["send"], [{"mailbox": "b@small.example", "id": "n1", "kind": "first"}])
        refused = {r["mailbox"]: r["why"] for r in plan["refused"]}
        self.assertIn("no contract above half (15)", refused["a@big.example"])
        self.assertIn("15 of today's first-touch capacity of 30", refused["a@big.example"])
        # one under half, it may send
        usage["a@big.example"] = {"today": 14, "first_today": 14}
        plan = assets.plan_tick(self.snap(), usage, [], [{"id": "n1"}, {"id": "n2"}], default_cap=10)
        self.assertEqual({s["mailbox"] for s in plan["send"]}, {"a@big.example", "b@small.example"})
        # a follow-up is not a first touch: the half rule doesn't hold it
        usage["a@big.example"] = {"today": 15, "first_today": 15}
        plan = assets.plan_tick(self.snap(), usage, [{"id": "f", "mailbox": "a@big.example", "due": "x"}], [], 10)
        self.assertEqual(plan["send"], [{"mailbox": "a@big.example", "id": "f", "kind": "follow"}])

    def test_one_contract_runs_at_half(self):
        lane(self.reg, boxes=("a@one.example", "b@one.example"))
        usage = {"a@one.example": {"today": 5, "first_today": 5}, "b@one.example": {"today": 5, "first_today": 5}}
        plan = assets.plan_tick(self.snap(), usage, [], [{"id": "n"}], default_cap=10)
        self.assertEqual(plan["send"], [])
        self.assertEqual(len(plan["refused"]), 2)
        self.assertEqual(assets.breaches(self.snap(), usage, 10), [])
        usage["a@one.example"] = {"today": 6, "first_today": 6}
        self.assertTrue(any("over half" in b for b in assets.breaches(self.snap(), usage, 10)))

    def test_caps_round_robin_and_prohibited(self):
        lane(self.reg, boxes=("a@one.example", "b@one.example", "c@one.example", "d@one.example"))
        fresh = [{"id": f"n{i}"} for i in range(4)]
        firsts = [assets.plan_tick(self.snap(), {}, [], fresh, default_cap=10, offset=k)["send"][0]["mailbox"]
                  for k in range(4)]
        self.assertEqual(firsts, ["a@one.example", "b@one.example", "c@one.example", "d@one.example"])
        plan = assets.plan_tick(self.snap(), {"a@one.example": {"today": 10}}, [], fresh, default_cap=10)
        self.assertNotIn("a@one.example", {s["mailbox"] for s in plan["send"]})
        self.assertIn("at its cap", {r["mailbox"]: r["why"] for r in plan["refused"]}["a@one.example"])
        d = self.reg.find(T, "one.example")
        self.reg.set_fields(d["id"], cap_day=1)
        plan = assets.plan_tick(self.snap(), {}, [], fresh, default_cap=10)
        self.assertEqual(len(plan["send"]), 1)
        self.assertTrue(any("domain one.example is at its cap" in r["why"] for r in plan["refused"]))
        lane(self.reg, provider="ws", verdict="PROHIBITED", domain="ws.example", boxes=("w@ws.example",), tenant="t2")
        plan = assets.plan_tick(self.snap("t2"), {}, [{"id": "f", "mailbox": "w@ws.example", "due": "x"}],
                                [{"id": "n"}], default_cap=10)
        self.assertEqual(plan["send"], [])
        self.assertIn("PROHIBITED", plan["held"][0]["why"])

    def test_accepted_risk_and_draining(self):
        lane(self.reg, verdict="ACCEPTED_RISK", boxes=("a@one.example",))
        follow = [{"id": "f", "mailbox": "a@one.example", "due": "x"}]
        plan = assets.plan_tick(self.snap(), {}, follow, [{"id": "n"}], default_cap=10)
        self.assertEqual([s["kind"] for s in plan["send"]], ["follow"])
        plan = assets.plan_tick(self.snap(), {}, [], [{"id": "n"}], default_cap=10)
        self.assertEqual(plan["send"], [])
        self.assertIn("PERMITTED contracts only", plan["refused"][0]["why"])
        self.reg.set_fields(self.reg.find(T, "p1")["id"], contract="PERMITTED")
        self.reg.set_state(self.reg.find(T, "a@one.example")["id"], "draining", "test")
        plan = assets.plan_tick(self.snap(), {}, follow, [{"id": "n"}], default_cap=10)
        self.assertEqual([s["kind"] for s in plan["send"]], ["follow"])
        plan = assets.plan_tick(self.snap(), {}, [], [{"id": "n"}], default_cap=10)
        self.assertEqual(plan["send"], [])

    def test_drain_on_reputation(self):
        lane(self.reg)
        d = self.reg.find(T, "one.example")
        self.reg.record_reading(d["id"], "postmaster", "spam_rate", "0.05", "2026-10-07")
        self.assertEqual(assets.drain_on_reputation(self.reg, T, 0.1), [])
        self.reg.record_reading(d["id"], "postmaster", "spam_rate", "0.12", "2026-10-08")
        changed = assets.drain_on_reputation(self.reg, T, 0.1)
        self.assertEqual(sorted(n for _, n, _, _, _ in changed), ["a@one.example", "b@one.example", "one.example"])
        self.assertIn("spam rate 0.12% on 2026-10-08", self.reg.find(T, "one.example")["state_why"])
        self.assertEqual(assets.drain_on_reputation(self.reg, T, 0.1), [])      # once
        with self.assertRaises(assets.AssetError):
            self.reg.record_reading(d["id"], "guess", "spam_rate", "0", "2026-10-08")
        self.assertIn("BAD", assets.bad_reading({"reputation": {"value": "bad", "date": "d", "source": "postmaster"}}, .1))
        self.assertIn("placement", assets.bad_reading({"inbox_pct": {"value": "40", "date": "d", "source": "probe"}}, .1))

    def test_breaches(self):
        lane(self.reg, provider="ws", verdict="PROHIBITED", boxes=("a@one.example",))
        self.assertEqual(assets.breaches(self.snap(), {}, 0), [])
        bad = assets.breaches(self.snap(), {"a@one.example": {"today": 1, "first_today": 1}}, 5)
        self.assertFalse(any("cold-mail cap of 5" in b for b in bad))         # B150: no thread, the cap sends nothing
        bad = assets.breaches(self.snap(), {"a@one.example": {"today": 1, "first_today": 1, "open_threads": 2}}, 5)
        self.assertTrue(any("cold-mail cap of 5 today under contract PROHIBITED and 2 open" in b for b in bad))
        self.assertTrue(any("sent 1 first letter(s) today though contract PROHIBITED" in b for b in bad))


class RdapTest(Base):
    def test_renewal_from_rdap_cached_and_offline(self):
        hits = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                body = json.dumps({"events": [{"eventAction": "registration", "eventDate": "2026-10-01T00:00:00Z"},
                                              {"eventAction": "expiration", "eventDate": "2027-10-01T00:00:00Z"}]})
                self.send_response(200)
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        lane(self.reg)
        old = dict(os.environ)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))
        os.environ["ASSETS_RDAP_BASE"] = f"http://127.0.0.1:{srv.server_address[1]}/domain/"
        os.environ.pop("ASSETS_RDAP", None)
        assets.refresh_renewals(self.reg, T)
        assets.refresh_renewals(self.reg, T)                   # cached: no second GET
        self.assertEqual(hits, ["/domain/one.example"])
        d = self.reg.find(T, "one.example")
        self.assertEqual((d["renews"], d["renews_source"]), ("2027-10-01", "rdap"))
        os.environ["ASSETS_RDAP_BASE"] = "http://127.0.0.1:9/domain/"     # nothing listens: offline
        assets.refresh_renewals(self.reg, T, force=True)
        self.assertEqual(self.reg.find(T, "one.example")["renews"], "2027-10-01")
        os.environ["ASSETS_RDAP"] = "0"
        self.assertEqual(assets.refresh_renewals(self.reg, T, force=True), [])


class OutreachAssetsTest(unittest.TestCase):
    """`outreach assets` and the registry lines in `outreach status`, as the tool runs."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="outreach-assets-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.tmp),
            "CLAUDE_TOOLS_ENV": os.devnull, "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
            "OUTREACH_STATE": str(self.tmp / "state"), "OUTREACH_LEDGER": str(self.tmp / "ledger.jsonl"),
            "OUTREACH_MAILBOXES": "a@send.example,b@send.example,c@send.example",
            "OUTREACH_PROVIDER": "fake", "OUTREACH_MAILBOX_PER_DAY": "0", "OUTREACH_WARMUP_START": "2026-08-01",
            "OUTREACH_NOW": "2026-10-19T09:00:00", "ASSETS_RDAP": "0",
            "VENTURES_DIR": str(TOOLS / "tests" / "fixtures" / "ventures"), "VENTURE": "example",
            **{k: os.environ[k] for k in os.environ
               if k.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy", "claude_tools_offline_proxy")},
        }

    def run_it(self, *args, expect=0, **over):
        env = dict(self.env, **{k: str(v) for k, v in over.items()})
        r = subprocess.run([sys.executable, str(OUTREACH), *args], capture_output=True, text=True, env=env, timeout=60)
        if expect is not None:
            self.assertEqual(r.returncode, expect, f"{args}\n{r.stdout}\n{r.stderr}")
        return r

    def test_lists_the_lane_at_four_levels(self):
        out = self.run_it("assets").stdout
        self.assertIn("tenant brightwell", out)                                   # V.tenant, from the venture
        self.assertIn("provider google-workspace  [active]  contract PROHIBITED (read 2026-10-07)", out)
        self.assertIn("unsolicited mass email", out)
        self.assertIn("domain trybrightwell.example  [active]", out)             # the venture's sending domain
        self.assertIn("domain send.example  [active]", out)
        for b in ("a", "b", "c"):
            self.assertIn(f"mailbox {b}@send.example  [active]  cap 0 · today 0 · 30 days: 0 sent", out)
        self.assertIn("first letter: no — contract PROHIBITED for cold mail", out)
        self.assertIn("rules: none breached", out)
        data = json.loads(self.run_it("assets", "--json").stdout)
        self.assertEqual({r["kind"] for r in data["rows"]}, {"provider", "tenant", "domain", "mailbox"})
        self.assertEqual({r["verdict"] for r in data["rows"]}, {"PROHIBITED"})
        self.assertEqual(data["first_capacity"], 0)
        self.assertTrue((self.tmp / "assets.db").exists())                     # beside the state dir, not $HOME's

    def test_check_fails_when_workspace_could_send(self):
        self.run_it("assets", "--check")
        # B150: first letters go by the registry's rule 1, so a cap on a PROHIBITED mailbox with no thread of its
        # own sends nothing; with a thread it began, its follow-ups would go through it, and that's the breach
        self.run_it("assets", "--check", OUTREACH_MAILBOX_PER_DAY="5")
        state = self.tmp / "state"
        state.mkdir(exist_ok=True)
        (state / "sequences.json").write_text(json.dumps([{"id": "s1", "email": "x@q.example", "status": "active",
                                                           "mailbox": "a@send.example", "touches": []}]))
        r = self.run_it("assets", "--check", expect=1, OUTREACH_MAILBOX_PER_DAY="5")
        self.assertIn("cold-mail cap of 5 today under contract PROHIBITED and 1 open thread(s)", r.stdout)
        st = self.run_it("status", OUTREACH_MAILBOX_PER_DAY="5").stdout
        self.assertIn("Registry (B141)", st)
        self.assertIn("google-workspace PROHIBITED", st)
        self.assertIn("rules: BREACHED", st)

    def test_state_set_and_incident(self):
        r = self.run_it("assets", "state", "a@send.example", "paused", expect=1)
        self.assertIn("--why", r.stderr)
        self.assertIn("a@send.example: active -> paused",
                      self.run_it("assets", "state", "a@send.example", "paused", "--why", "test").stdout)
        self.run_it("assets", "set", "google-workspace", "--cost", "7.2", "--step", "Cancel two seats")
        self.run_it("assets", "incident", "send.example", "a bounce storm")
        out = self.run_it("assets").stdout
        self.assertIn("mailbox a@send.example  [paused]", out)
        self.assertIn("paused since", out)
        self.assertIn("$7.2/mo", out)
        self.assertIn("waits on Taylor: Cancel two seats", out)
        self.assertIn("incident", out)
        self.assertIn("a bounce storm", out)
        r = self.run_it("assets", "set", "a@send.example", "--verdict", "PERMITTED", expect=1)
        self.assertIn("provider row", r.stderr)
        r = self.run_it("assets", "state", "nobody@x.example", "active", "--why", "x", expect=1)
        self.assertIn("no asset", r.stderr)

    def test_the_lanes_pause_and_postmaster_reach_the_registry(self):
        state = self.tmp / "state"
        state.mkdir()
        (state / "paused.json").write_text(json.dumps({"b@send.example": {"ts": "x", "why": "angry reply from z@q.example"}}))
        (state / "postmaster.jsonl").write_text(json.dumps({"ts": "2026-10-18T08:00:00", "domain": "send.example",
                                                            "rate": 0.2}) + "\n")
        out = self.run_it("assets").stdout
        self.assertIn("mailbox b@send.example  [draining]", out)      # paused by the lane, then drained with its domain
        self.assertIn("domain send.example  [draining]", out)
        self.assertIn("spam 0.20% (postmaster, 2026-10-18)", out)
        self.assertIn("reputation: postmaster spam rate 0.20%", out)

    def test_the_api_reading_reaches_the_registry(self):
        """B136's daily reading (lib/postmaster.py, source api) lands as a dated postmaster reading."""
        state = self.tmp / "state"
        state.mkdir()
        (state / "postmaster.jsonl").write_text(json.dumps({
            "ts": "2026-10-18T06:00:00", "source": "api", "domain": "send.example", "date": "2026-10-17",
            "rate": 0.02, "reputation": "HIGH"}) + "\n")
        out = self.run_it("assets").stdout
        self.assertIn("reputation HIGH (postmaster, 2026-10-17), spam 0.02% (postmaster, 2026-10-17)", out)
        self.assertIn("domain send.example  [active]", out)

    def test_dry_run_changes_nothing(self):
        self.run_it("assets", "--dry-run")
        self.assertFalse((self.tmp / "assets.db").exists())


if __name__ == "__main__":
    unittest.main()
