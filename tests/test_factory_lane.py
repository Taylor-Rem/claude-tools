"""B150: the Factory feeds the engine. A mailbox `infra certify` makes `active` joins the lane the next working
day with no env change, and one `infra drain` takes out sends no first letter; the Workspace entry
(OUTREACH_MAILBOXES, a PROHIBITED contract) begins no thread but finishes the ones it began.

    python3 -m unittest tests.test_factory_lane   (from claude-tools/)

The outreach side runs on the fake outreach provider (letters land in state/fake/outbox.jsonl) and the
Factory side on the fake infra provider; both read one registry. Nothing reaches the network.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads (tests/_offline.py)
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent / "lib"))

import datetime as dt  # noqa: E402
import json  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import unittest  # noqa: E402

import assets  # noqa: E402
import test_outreach_batch as tb  # noqa: E402
import venture  # noqa: E402

INFRA = tb.TOOLS / "bin" / "infra"
D = "factory-one.example"
SEEDS = "seed1@gmail.example,seed2@outlook.example"
TODO = "# T\n\n## 1. Now\n\n### 1b. Waiting\n\n## 3. Decisions\n"


class FactoryLane(tb.Base):
    def setUp(self):
        super().setUp()
        (self.tmp / "TODO.md").write_text(TODO)
        (self.tmp / "env").write_text("")
        self.env.update({
            "OUTREACH_PROVIDER": "fake", "OUTREACH_MAILBOX_PROVIDER": "google-workspace",   # the entry: PROHIBITED
            "ASSETS_DB": str(self.tmp / "assets.db"), "CLAUDE_TOOLS_ENV": str(self.tmp / "env"),
            "INFRA_STATE": str(self.tmp / "infra"), "INFRA_LEDGER": str(self.tmp / "ledger.jsonl"),
            "TODO_FILE": str(self.tmp / "TODO.md"), "INFRA_PROVIDER": "fake", "INFRA_SEED_INBOXES": SEEDS,
            "INFRA_NOW": "2026-10-01T15:00:00+00:00", "ASSETS_RDAP": "0"})
        self.approve()
        self.tenant = venture.venture().tenant

    def infra(self, *args, ok=0, **over):
        env = dict(self.env, **{k: str(v) for k, v in over.items()})
        r = subprocess.run([sys.executable, str(INFRA), *args], capture_output=True, text=True, env=env, timeout=60)
        if ok is not None:
            self.assertEqual(r.returncode, ok, f"infra {args}\n{r.stdout}\n{r.stderr}")
        return r

    def outbox(self):
        return self.state_rows("fake/outbox.jsonl")

    def certify_on(self, day):
        """Provision on 2026-10-01, a seed round each day to `day`, Postmaster reading, the human steps ticked,
        then `infra certify` on `day`."""
        self.infra("provision", "--domain", D, "--mailboxes", "2", "--go")
        d = dt.date(2026, 10, 2)
        while d <= day:
            t = f"{d.isoformat()}T15:00:00+00:00"
            self.infra("seeds", "send", D, INFRA_NOW=t)
            self.infra("seeds", "read", D, INFRA_NOW=t)
            d += dt.timedelta(days=1)
        with open(self.tmp / "state" / "postmaster-fetch.jsonl", "a") as f:
            f.write(json.dumps({"ts": f"{day.isoformat()}T15:00:00+00:00", "domain": D, "outcome": "no data"}) + "\n")
        todo = (self.tmp / "TODO.md").read_text().replace("- [ ] **", "- [x] **")
        (self.tmp / "TODO.md").write_text(todo)
        r = self.infra("certify", D, INFRA_NOW=f"{day.isoformat()}T15:00:00+00:00")
        self.assertIn("are `active`", r.stdout)

    def factory_boxes(self):
        return {r["name"] for r in assets.Registry(self.tmp / "assets.db").rows(self.tenant)
                if r["kind"] == "mailbox" and r["name"].endswith("@" + D)}

    def test_a_domain_certified_today_sends_tomorrow_and_a_drained_one_sends_none(self):
        self.run_it("send", "--batch", str(self.write_batch(self.picks(9))), "--go")
        # warming: nothing goes, and the Workspace entry (PROHIBITED) begins no thread
        self.infra("provision", "--domain", D, "--mailboxes", "2", "--go")
        self.tick_day("2026-10-16", end="12:00")
        self.assertEqual([], self.outbox())
        r = self.run_it("tick", OUTREACH_NOW="2026-10-16T12:30:00")
        self.assertIn("0 sent", r.stdout)
        # certified on Sunday the 18th; Monday the lane sends from it, with no env change
        self.certify_on(dt.date(2026, 10, 18))
        boxes = self.factory_boxes()
        self.assertEqual(2, len(boxes))
        self.tick_day(tb.MONDAY)
        out = self.outbox()
        self.assertEqual(9, len(out))
        self.assertEqual(boxes, {m["from"] for m in out}, "a first letter left a mailbox the registry didn't admit")
        self.assertFalse(set(tb.BOXES) & {m["from"] for m in out})
        st = self.run_it("status").stdout
        self.assertIn("the Factory this week: 2 mailbox(es) joined the lane", st)
        # drained: no first letter from it the next day; its threads' follow-ups still go from it
        self.run_it("send", "--batch", str(self.write_batch(self.picks()[10:14], "b-two")), "--go",
                    OUTREACH_NOW="2026-10-20T07:00:00")
        self.infra("drain", D, "--why", "test: a bad reading")
        self.tick_day("2026-10-20")
        self.assertEqual(9, len(self.outbox()), "a drained mailbox sent a first letter")
        self.tick_day("2026-10-22")                      # day 3: the Monday threads' second letters
        later = self.outbox()[9:]
        self.assertEqual(9, len(later))
        self.assertTrue(all(m["in_reply_to"] for m in later))
        self.assertEqual(boxes, {m["from"] for m in later})

    def test_one_contract_carries_half_the_first_letters(self):
        self.certify_on(dt.date(2026, 10, 18))
        self.run_it("send", "--batch", str(self.write_batch(self.picks(9))), "--go")
        self.tick_day(tb.MONDAY, OUTREACH_MAILBOX_PER_DAY="3")      # two caps of three: six, half of it three
        self.assertEqual(3, len(self.outbox()))
        # the Workspace entry's cap of three sends nothing (no thread of its own), so the evening check is quiet
        r = self.run_it("assets", "--check", OUTREACH_NOW=f"{tb.MONDAY}T17:30:00", OUTREACH_MAILBOX_PER_DAY="3")
        self.assertIn("rules: none breached", r.stdout)

    def test_cap_zero_holds_the_factory_too(self):
        self.certify_on(dt.date(2026, 10, 18))
        self.run_it("send", "--batch", str(self.write_batch(self.picks(3))), "--go")
        self.tick_day(tb.MONDAY, OUTREACH_MAILBOX_PER_DAY="0")
        self.assertEqual([], self.outbox())
        self.run_it("assets", "set", sorted(self.factory_boxes())[0], "--cap", "2")   # the registry's own cap
        self.tick_day("2026-10-20", OUTREACH_MAILBOX_PER_DAY="0")
        self.assertEqual(1, len(self.outbox()))           # its cap is 2; half of the contract's 2 is 1

    def test_the_workspace_entry_finishes_the_threads_it_began(self):
        # a thread begun from the entry before B150's rule held (its provider then PERMITTED), then the verdict
        self.env["OUTREACH_MAILBOX_PROVIDER"] = "fake"
        self.run_it("send", "--batch", str(self.write_batch(self.picks(3))), "--go")
        self.tick_day(tb.MONDAY, OUTREACH_MAILBOX_PER_DAY="4")
        self.assertEqual(3, len(self.outbox()))
        self.run_it("assets", "set", "fake", "--verdict", "PROHIBITED", "--clause", "test")
        self.run_it("send", "--batch", str(self.write_batch(self.picks()[10:13], "b-two")), "--go",
                    OUTREACH_NOW="2026-10-22T07:00:00")
        self.tick_day("2026-10-22", OUTREACH_MAILBOX_PER_DAY="4")
        later = self.outbox()[3:]
        self.assertEqual(3, len(later), "the threads didn't finish, or a new one began")
        self.assertTrue(all(m["in_reply_to"] for m in later))


class FactoryRamp(unittest.TestCase):
    """A Factory mailbox's ramp counts from its own day in `warming`, not the Workspace entry's start."""

    def test_ramp_from_its_own_warming(self):
        import tempfile
        tmp = _pathlib.Path(tempfile.mkdtemp(prefix="factory-ramp-"))
        reg = assets.Registry(tmp / "a.db")
        t0 = dt.datetime(2026, 10, 1, 15, tzinfo=dt.timezone.utc)
        pid = reg.ensure("t", "provider", "fake", contract="PERMITTED", now=t0)
        tid = reg.ensure("t", "tenant", "t-at-fake", parent_id=pid, now=t0)
        did = reg.ensure("t", "domain", "d.example", parent_id=tid, state="provisioning", now=t0)
        mid = reg.ensure("t", "mailbox", "a@d.example", parent_id=did, state="provisioning", now=t0)
        reg.set_state(did, "warming", "provisioned", cascade=True, now=t0)
        self.assertEqual("2026-10-01", assets.entered(reg, mid, "warming"))
        mv = assets.week_moves(reg, "t", "2026-09-30")
        self.assertEqual([], mv["joined"])
        reg.set_state(did, "active", "certified", cascade=True, now=t0 + dt.timedelta(days=15))
        self.assertEqual(["a@d.example"], assets.week_moves(reg, "t", "2026-10-10")["joined"])
        snap = assets.snapshot(reg, "t")
        cap = assets.capacity(snap, {}, lambda mb: 7)
        self.assertEqual(7, cap["mailboxes"]["a@d.example"]["cap"])
        self.assertEqual(7, cap["first_capacity"])


if __name__ == "__main__":
    unittest.main()
