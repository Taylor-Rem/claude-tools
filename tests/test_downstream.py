"""Downstream capacity as a policy input (ROADMAP B145; plan 55 § 5.10; VISION § Decided "Autonomous acquisition" #8).

    python3 -m unittest tests.test_downstream   (from claude-tools/)

Offline, everything in a temporary directory. What's pinned (the row's acceptance first):
  - with a fixture queue of 60 minutes a day for three days, route() returns `hold first touches` for a P4
    prospect and `send` for its follow-up, and the morning message (`todo now`) carries the hold line and names
    the key with the most minutes;
  - the window: a day with no `todo now` is unknown, never zero; three unknowns are not a hold; a weekend gap
    doesn't break a hold; one day back under the budget lifts it (no state to flip);
  - the row: a key waiting on a row names it ("say `pull B… forward`"); a key without one says `todo audit`
    proposes one on Sunday;
  - `leads prospects route` fills capacity["downstream"] from the same state file;
  - portable: lib/downstream.py names no business.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent / "lib"))

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402
from datetime import date, timedelta  # noqa: E402
from pathlib import Path  # noqa: E402

import downstream as ds  # noqa: E402
import policy  # noqa: E402
import prospects  # noqa: E402

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
TODO = TOOLS / "bin" / "todo"
TODAY = date.today()

# A venture's table, as policy.route() reads it: lanes, never ids by name.
PROPS = {"P4": {"lane": "email", "letters": ("p4-first", "p4-second", "p4-third"), "label": "self-built"},
         "P2": {"lane": "card", "letters": None, "label": "no site"}}

# The fixture queue: 60 minutes, most of it one recurring automatable key waiting on a row.
QUEUE = """# The owner's list

## 1. Now — sessions are waiting on these

- [ ] **Add the DNS record for the new client's domain.** About 35 minutes at the registrar.
  - **1.** Run `site domain shop example.org`.
  automatable: the DNS host's API adds the record (B058)
  <!-- todo: repeat_key=dns-record; estimated_minutes=35 -->
- [ ] **Onboard the new client: the walk-through.** Twenty minutes by phone.
  <!-- todo: repeat_key=client-walkthrough; human_reason=physical; estimated_minutes=20 -->
- [ ] **Decide the letter's second line?** Five minutes.
  <!-- todo: repeat_key=letter-line; human_reason=judgment; estimated_minutes=5 -->

## 3. Decisions
"""
ROADMAP = "| id | what | status |\n|---|---|---|\n| B058 | the DNS row | queued |\n"


def day(n):
    return TODAY - timedelta(days=n)


def seed(path, totals, by_key=None, rows=None):
    """totals: {days ago: minutes}."""
    for n, m in totals.items():
        ds.record_day(path, day(n), m, by_key or {"dns-record": m}, rows or {"dns-record": "B058"}, 1)


def p4(**kw):
    r = prospects.record(venture="example", key="place:Q1", place_id="Q1", name="Q",
                         proposition={"id": "P4", "lane": "email", "facts": [{"key": "a"}, {"key": "b"}]},
                         strength={"level": "good"},
                         routes=[{"channel": "email", "value": "a@q.example", "verdict": "high"}])
    r.update(kw)
    return r


class TheWindow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "minutes.json"

    def tearDown(self):
        self.tmp.cleanup()

    def m(self):
        return ds.measure(ds.read_days(self.path), TODAY, 45)

    def test_three_days_over_holds_and_names_the_top_key(self):
        seed(self.path, {0: 60, 1: 60, 2: 60})
        d = self.m()
        self.assertTrue(d["hold"])
        self.assertEqual((d["over_budget_days"], d["known_days"]), (3, 3))
        self.assertEqual(d["top_keys"][0], {"repeat_key": "dns-record", "minutes": 180, "row": "B058", "proposal": None})
        self.assertIn("dns-record", d["why"])
        self.assertIn("B058 would remove it", d["why"])

    def test_unknown_days_are_not_zero_and_not_a_hold(self):
        self.assertFalse(self.m()["hold"])                        # three unknowns
        seed(self.path, {0: 60, 1: 60})
        d = self.m()
        self.assertEqual((d["hold"], d["known_days"]), (False, 2))
        self.assertEqual(ds.message_lines(d)[0][:40], "Downstream: over your 45-min budget 2 of")

    def test_a_weekend_without_a_run_keeps_the_window(self):
        seed(self.path, {0: 60, 3: 60, 4: 60})                    # Friday, Thursday, then Monday
        self.assertTrue(self.m()["hold"])
        self.path.unlink()
        seed(self.path, {0: 60, 8: 60, 9: 60})                    # older than the lookback: not three known days
        self.assertFalse(self.m()["hold"])

    def test_one_day_back_under_lifts_it(self):
        seed(self.path, {1: 60, 2: 60, 3: 60})
        self.assertTrue(self.m()["hold"])
        seed(self.path, {0: 30})
        d = self.m()
        self.assertFalse(d["hold"])
        self.assertEqual(d["over_budget_days"], 2)

    def test_a_key_without_a_row_says_audit_proposes_one(self):
        seed(self.path, {0: 60, 1: 60, 2: 60}, by_key={"env-value": 60}, rows={"env-value": ""})
        d = self.m()
        self.assertEqual(d["top_keys"][0]["row"], None)
        self.assertEqual(d["top_keys"][0]["proposal"], ds.NO_ROW)
        lines = ds.message_lines(d)
        self.assertIn("env-value 180 min → no row yet: `todo audit` proposes one on Sunday", lines[1])
        self.assertNotIn("pull", lines[2])

    def test_the_budget_is_an_env_value(self):
        self.assertEqual(ds.budget({}), 45)
        self.assertEqual(ds.budget({"TODO_DAILY_MINUTES": "90"}), 90)
        self.assertEqual(ds.budget({"TODO_DAILY_MINUTES": "lots"}), 45)

    def test_a_state_file_that_cannot_be_read_is_no_hold(self):
        self.path.write_text("{not json")
        self.assertFalse(self.m()["hold"])


class TheRule(unittest.TestCase):
    """The acceptance: a P4 prospect's day-0 touch holds; its day-3 follow-up sends."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "minutes.json"
        seed(self.path, {0: 60, 1: 60, 2: 60})
        self.down = ds.measure(ds.read_days(self.path), TODAY, 45)

    def tearDown(self):
        self.tmp.cleanup()

    def cap(self, down="hold", today=TODAY):
        return policy.capacity_view(None, {}, 4, downstream=self.down if down == "hold" else down,
                                    today=today.isoformat())

    def test_first_touch_holds_follow_up_sends(self):
        first = policy.route(p4(), self.cap(), PROPS)
        self.assertEqual((first["action"], first["lane"], first["rule"], first["decision"]),
                         ("hold first touches", "hold", 7, ["AA#8"]))
        self.assertIn("dns-record", first["reason"])

        sent = prospects.apply_send(p4(), {"date": day(3).isoformat(), "touch": 0, "template": "p4-first",
                                           "mailbox": "a@send.example", "email": "a@q.example", "proposition": "P4"})
        follow = policy.route(sent, self.cap(), PROPS)
        self.assertEqual((follow["action"], follow["lane"], follow["rule"], follow["status"]),
                         ("send", "email", 3, "ready"))
        self.assertEqual((follow["touch"]["n"], follow["touch"]["template"], follow["asset"]),
                         (3, "p4-second", "a@send.example"))
        self.assertIn("rule 7: a follow-up goes on under the downstream hold (first touches hold)", follow["notes"])

    def test_a_follow_up_before_its_day_waits_and_after_the_sequence_nothing(self):
        sent = prospects.apply_send(p4(), {"date": day(1).isoformat(), "touch": 0, "template": "p4-first",
                                           "mailbox": "a@send.example", "email": "a@q.example"})
        p = policy.route(sent, self.cap(), PROPS)
        self.assertEqual((p["action"], p["status"]), ("wait", "waiting"))
        self.assertIn(f"due {day(-2).isoformat()}", p["reason"])
        for n in (3, 10):
            sent = prospects.apply_send(sent, {"date": day(1).isoformat(), "touch": n, "mailbox": "a@send.example"})
        p = policy.route(sent, self.cap(), PROPS)
        self.assertEqual((p["rule"], p["lane"]), (1, "nothing"))           # held by its own (finished) sequence

    def test_a_reply_stops_the_sequence_and_the_conversation_goes_on(self):
        sent = prospects.apply_send(p4(), {"date": day(3).isoformat(), "touch": 0, "mailbox": "a@send.example"})
        sent = prospects.apply_reply(sent, {"date": day(1).isoformat(), "class": "question"})
        p = policy.route(sent, self.cap(), PROPS)
        self.assertEqual((p["rule"], p["action"]), (6, "answer"))
        sent["conversation"]["open"] = False
        self.assertEqual(policy.route(sent, self.cap(), PROPS)["rule"], 1)  # answered: no follow-up letter

    def test_no_hold_when_under_budget_or_unread(self):
        p = policy.route(p4(), self.cap(down=None), PROPS)
        self.assertEqual(p["action"], "wait")                    # rule 3, no registry in this capacity
        self.assertIn("rule 7: no hold (downstream capacity wasn't read)", p["notes"])
        under = ds.measure({}, TODAY, 45)
        p = policy.route(p4(), self.cap(down=under), PROPS)
        self.assertIn("rule 7: no hold (the human queue has 0 recorded days of 3)", p["notes"])
        self.assertEqual(p["rule"], 3)

    def test_suppressed_still_first(self):
        sent = prospects.apply_send(p4(), {"date": day(3).isoformat(), "touch": 0, "mailbox": "a@send.example"})
        sent["state"]["suppressed"] = "replied no"
        self.assertEqual(policy.route(sent, self.cap(), PROPS)["rule"], 1)


class TheMorningMessage(unittest.TestCase):
    """`todo now` (schedule s12's prompt sends it as printed) writes today's total and leads with the hold."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        (t / "projects").mkdir()
        (t / "projects" / "TAYLOR-TODO.md").write_text(QUEUE)
        (t / "projects" / "HISTORY.md").write_text("# History\n")
        (t / "projects" / "ROADMAP.md").write_text(ROADMAP)
        self.state = t / "state"
        self.env = {"PATH": "/usr/bin:/bin", "HOME": str(t), "TODO_FILE": str(t / "projects" / "TAYLOR-TODO.md"),
                    "TODO_STATE_DIR": str(self.state), "TODO_DAILY_MINUTES": "45",
                    "CLAUDE_TOOLS_ENV": os.environ.get("CLAUDE_TOOLS_ENV", "/dev/null")}

    def tearDown(self):
        self.tmp.cleanup()

    def todo(self, *args):
        r = subprocess.run([_sys.executable, str(TODO), *args], capture_output=True, text=True, env=self.env,
                           stdin=subprocess.DEVNULL, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r.stdout

    def test_sixty_minutes_three_days_carries_the_line(self):
        out = self.todo("now", "--offline")
        self.assertIn("about 1 h in all", out)
        self.assertNotIn("Downstream", out)                      # one day known: no hold, and no warning yet
        days = ds.read_days(self.state / "minutes.json")
        self.assertEqual(days[TODAY.isoformat()]["total"], 60)
        self.assertEqual(days[TODAY.isoformat()]["by_key"], {"dns-record": 35, "client-walkthrough": 20,
                                                             "letter-line": 5})
        self.assertEqual(days[TODAY.isoformat()]["rows"]["dns-record"], "B058")
        self.assertEqual(days[TODAY.isoformat()]["onboarding"], 2)      # the client's domain, the walk-through

        seed(self.state / "minutes.json", {1: 60, 2: 60}, by_key={"dns-record": 35, "client-walkthrough": 25},
             rows={"dns-record": "B058"})
        out = self.todo("now", "--offline").splitlines()
        self.assertLess(len(out), 12, "\n".join(out))
        self.assertTrue(out[1].startswith("Downstream hold: over your 45-min budget 3 days running (60, 60, 60 min)"),
                        out[1])
        self.assertIn("first touches hold; follow-ups, replies and the close go on; 2 onboarding steps open.", out[1])
        self.assertTrue(out[2].startswith("  Most minutes: dns-record 105 min → B058; client-walkthrough 70 min → no row yet: "
                                          "`todo audit` proposes one on Sunday; letter-line 5 min → no row yet"),
                        out[2])
        self.assertIn("Say `pull B058 forward` to build it next", out[3])

        short = self.todo("now", "--short", "--offline").strip()
        self.assertEqual(len(short.splitlines()), 1)
        self.assertIn("First touches hold: over 45 min 3 days running; most minutes: dns-record (B058).", short)

        d = json.loads(self.todo("downstream", "--json"))
        self.assertTrue(d["hold"])
        self.assertIn("B058", self.todo("downstream"))
        a = json.loads(self.todo("audit", "--json"))
        self.assertTrue(a["downstream"]["hold"])
        self.assertIn("Downstream hold:", self.todo("audit", "--sunday"))

    def test_a_higher_budget_is_no_hold(self):
        seed(self.state / "minutes.json", {1: 60, 2: 60})
        self.env["TODO_DAILY_MINUTES"] = "90"
        self.assertNotIn("Downstream", self.todo("now", "--offline"))


class TheLeadsRoute(unittest.TestCase):
    """`leads prospects route` fills capacity["downstream"] from the state file `todo now` keeps."""

    def test_route_reads_the_window(self):
        import policy_capture as pc
        with tempfile.TemporaryDirectory() as tmp:
            world = pc.build_world(tmp)
            state = Path(tmp) / "todo-state"
            seed(state / "minutes.json", {0: 60, 1: 60, 2: 60})
            world["env"] = dict(world["env"], TODO_STATE_DIR=str(state), TODO_DAILY_MINUTES="45")
            pc.run(world, pc.LEADS, "prospects", "rebuild")
            ls = json.loads(pc.run(world, pc.LEADS, "prospects", "ls", "--json").stdout)
            self.assertIn(("hold", 7), {(x["lane"], x["rule"]) for x in ls})
            p = json.loads(pc.run(world, pc.LEADS, "prospects", "route", "FX_P503", "--json").stdout)
            self.assertEqual((p["action"], p["rule"], p["touch"]["n"]), ("send", 3, 3))
            (state / "minutes.json").unlink()
            ls = json.loads(pc.run(world, pc.LEADS, "prospects", "ls", "--json").stdout)
            self.assertNotIn("hold", {x["lane"] for x in ls})


class Portable(unittest.TestCase):
    def test_no_business_in_the_module(self):
        import test_portable as tp
        f = TOOLS / "lib" / "downstream.py"
        self.assertIn(f, tp.engine_files())
        self.assertEqual([], tp.scan([f], tp.all_needles(), tp.all_prices()))


if __name__ == "__main__":
    unittest.main()
