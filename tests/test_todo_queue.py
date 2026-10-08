"""The human queue (ROADMAP B138): `todo now`, `todo audit`, `todo reconcile`, `todo show`, `todo add`'s
hidden metadata, and the web page hiding it. Everything runs on the fixture copy in
tests/fixtures/todo/queue/ inside a temporary directory, with fake `outreach` and `leads` on PATH:
no network, nothing read or written in the real tree.

    python3 -m unittest tests.test_todo_queue -q   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
TODO = TOOLS / "bin" / "todo"
FIX = HERE / "fixtures" / "todo" / "queue"
_sys.path.insert(0, str(TOOLS / "lib"))
import todo_queue as tq  # noqa: E402


def entry(title, extra="", who="Flint, 2026-10-06"):
    return f"- [ ] **{title}** {extra}\n  _({who})_\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.proj = t / "projects"
        self.proj.mkdir()
        for name in ("TODO.md", "HISTORY.md", "ROADMAP.md"):
            shutil.copy(FIX / name, self.proj / ("TAYLOR-TODO.md" if name == "TODO.md" else name))
        self.bin = t / "bin"
        self.bin.mkdir()
        self.fake("outreach", "echo 2")
        self.fake("leads", "echo '3 follow-ups due:'; echo '  1. someone'")
        self.env = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(t), "TODO_FILE": str(self.proj / "TAYLOR-TODO.md"),
                    "TODO_STATE_DIR": str(t / "state"), "CLAUDE_TOOLS_ENV": os.environ.get("CLAUDE_TOOLS_ENV", "/dev/null")}

    def tearDown(self):
        self.tmp.cleanup()

    def fake(self, name, body):
        f = self.bin / name
        f.write_text(f"#!/bin/sh\n{body}\n")
        f.chmod(0o755)

    def run_todo(self, *args, ok=True):
        r = subprocess.run([sys_python(), str(TODO), *args], capture_output=True, text=True, env=self.env,
                           stdin=subprocess.DEVNULL, timeout=60)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        return r

    def read(self, name):
        return (self.proj / name).read_text()


def sys_python():
    return _sys.executable


class Now(Base):
    def test_under_twelve_lines_with_a_total(self):
        out = self.run_todo("now").stdout.strip().splitlines()
        self.assertLess(len(out), 12, "\n".join(out))
        self.assertRegex(out[0], r"^Yours now: \d+ on the list, about [\dh min]+ in all")
        text = "\n".join(out)
        # the funnel-blocking setup first, its command or link on the line, minutes on every entry line
        self.assertIn("Setup that blocks the lane:", text)
        first = next(l for l in out if re.match(r"\s+\d+\. ", l))
        self.assertIn("provider: open the account", first)
        self.assertIn("mailvendor.example.com", first)
        for l in out:
            if re.match(r"\s+\d+\. ", l):
                self.assertRegex(l, r" — .+ · ~\d+\??\s?min$")
        self.assertIn("Replies waiting on you: 2 — text `replies`", text)
        self.assertIn("Send today: 3 follow-ups due: `leads due`", text)
        self.assertIn('say "reconcile: yes" — 5 entries leave the list', text)

    def test_hides_waiting_and_proposed_shows_a_stalled_row(self):
        text = self.run_todo("now", "--json").stdout
        titles = [x["title"] for x in json.loads(text)]
        self.assertFalse(any("press link" in t for t in titles), "a waiting entry is hidden")
        self.assertTrue(any("old waiting step" in t for t in titles), "its row stalled thirty days: shown again")
        self.assertFalse(any("weekly rhythm" in t for t in titles), "§ 1c is not the queue")
        self.assertFalse(any("ticked one" in t for t in titles))
        later = [x for x in json.loads(text) if x["later"]]
        self.assertEqual(len(later), 1)
        self.assertIs(json.loads(text)[-1]["later"], True, "an entry dated ahead goes last")

    def test_pause_says_so_instead_of_listing_sends(self):
        self.run_todo("pause", "the owner paused outbound while the line is built")
        out = self.run_todo("now").stdout
        self.assertIn("Send today: nothing — sends are paused (the owner paused outbound", out)
        self.assertIn("3 follow-ups held", out)
        self.run_todo("pause", "--off")
        self.assertIn("3 follow-ups due", self.run_todo("now").stdout)

    def test_a_tool_that_fails_degrades_to_a_line(self):
        self.fake("outreach", "exit 3")
        (self.bin / "leads").unlink()
        out = self.run_todo("now").stdout
        self.assertIn("Replies waiting on you: couldn't read `outreach replies` (exit 3)", out)
        self.assertIn("couldn't read `leads` (not on PATH)", out)

    def test_short_line_for_the_request_box(self):
        out = self.run_todo("now", "--short", "--offline").stdout.strip()
        self.assertEqual(len(out.splitlines()), 1)
        self.assertIn("First: The production line's provider", out)

    def test_show(self):
        out = self.run_todo("show", "1").stdout
        self.assertTrue(out.startswith("- [ ] **The production line's provider"))
        self.assertIn("setenv.sh VENDOR_API_KEY", out)


class Audit(Base):
    def test_identity_hour_human_only_env_values_automatable_with_how(self):
        a = json.loads(self.run_todo("audit", "--json").stdout)
        by = {r["title"][:20]: r for r in a["entries"]}
        ident = next(r for r in a["entries"] if r["title"].startswith("The identity hour"))
        self.assertEqual(ident["class"], "human-only")
        self.assertTrue(ident["why"].startswith("identity"))
        for t in ("Site chat", "Four envs"):
            r = next(r for r in a["entries"] if r["title"].startswith(t))
            self.assertEqual(r["class"], "automatable", r)
            self.assertEqual(r["repeat_key"], "env-value")
            self.assertIn("API", r["why"])
        self.assertTrue(by)

    def test_the_same_key_proposes_then_queues(self):
        env_entry = lambda n: entry(f"Two lines in the host's environment, number {n}.")  # noqa: E731
        head = "## 1. Now\n\n"
        for n, want in ((1, None), (2, "propose"), (3, "queue")):
            text = head + "\n".join(env_entry(i) for i in range(n))
            # minutes stay under thirty, so only the count moves the rule
            a = tq.audit(tq.parse(text.replace("number", "(two minutes) number")), [], today=date(2026, 10, 8))
            got = [p["action"] for p in a["proposals"] if p["repeat_key"] == "env-value"]
            self.assertEqual(got, [want] if want else [], (n, a["proposals"]))

    def test_thirty_minutes_in_thirty_days_queues_on_one_occurrence(self):
        text = "## 1. Now\n\n" + entry("Two lines in the host's environment (thirty minutes).")
        a = tq.audit(tq.parse(text), [], today=date(2026, 10, 8))
        self.assertEqual([p["action"] for p in a["proposals"]], ["queue"])
        old = text.replace("2026-10-06", "2026-08-01")
        self.assertEqual(tq.audit(tq.parse(old), [], today=date(2026, 10, 8))["proposals"], [])

    def test_counts_the_done_trail_graduates_an_approval_and_lists_exceptions(self):
        a = json.loads(self.run_todo("audit", "--json").stdout)
        keys = {k["repeat_key"]: k for k in a["keys"]}
        self.assertEqual(keys["env-value"]["occurrence_count"], 3)   # two in § 1, one in the done trail
        self.assertEqual(keys["dns-record"]["occurrence_count"], 2)
        acts = {p["repeat_key"]: p["action"] for p in a["proposals"]}
        self.assertEqual(acts["env-value"], "queue")
        self.assertEqual(acts["dns-record"], "propose")
        self.assertEqual(acts["approve-batch"], "graduate")
        kept = "## 1. Now\n\n" + "\n".join(entry(f"Two lines in the environment {i} (two minutes).",
                                                 "kept manual because: the host has no API for it") for i in range(3))
        a2 = tq.audit(tq.parse(kept), [], today=date(2026, 10, 8))
        self.assertEqual(a2["proposals"], [])
        self.assertEqual(a2["exceptions"][0]["reason"], "the host has no API for it")

    def test_sunday_text_files_nothing(self):
        before = self.read("ROADMAP.md"), self.read("TAYLOR-TODO.md")
        out = self.run_todo("audit", "--sunday").stdout
        self.assertIn("env-value: queue the row", out)
        self.assertIn("nothing here is filed until you say so", out)
        self.assertEqual(before, (self.read("ROADMAP.md"), self.read("TAYLOR-TODO.md")))


class Reconcile(Base):
    def test_proposes_for_every_entry_and_changes_nothing(self):
        before = self.read("TAYLOR-TODO.md"), self.read("HISTORY.md")
        plan = json.loads(self.run_todo("reconcile", "--json").stdout)
        n_entries = len([e for e in tq.parse(before[0]) if e["section"] in ("1", "1b", "1c")])
        self.assertEqual(len(plan), n_entries)
        for p in plan:
            self.assertIn(p["class"], tq.CLASSES + ("MOVE",))
            self.assertTrue(p["reason"])
        cls = {p["title"][:22]: (p["class"], p["to"]) for p in plan}
        self.assertEqual(cls["Add the image API key "], ("DONE", "trail"))
        self.assertEqual(cls["Decide: a second ledge"], ("MOVE", "3"))
        self.assertEqual(cls["The press link: one DN"], ("WAITING_FOR_AUTOMATION", "1b"))
        self.assertEqual(cls["A ticked one still in "], ("DONE", "trail"))
        self.assertEqual(cls["The identity hour: the"][0], "HUMAN_NOW")
        self.run_todo("reconcile")
        r = self.run_todo("reconcile", "--apply", ok=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("needs Taylor's word", r.stderr)
        self.assertEqual(before, (self.read("TAYLOR-TODO.md"), self.read("HISTORY.md")))

    def test_apply_on_the_word(self):
        before = self.read("TAYLOR-TODO.md")
        open_before = {e["title"] for e in tq.parse(before) if not e["done"]}
        self.run_todo("reconcile", "--apply", "--word", "reconcile: yes")
        todo, hist = self.read("TAYLOR-TODO.md"), self.read("HISTORY.md")
        after = tq.parse(todo)
        self.assertNotIn("### 1c.", todo)
        # § 1 holds HUMAN_NOW and WAITING only: every remaining entry proposes to stay where it is
        plan = tq.reconcile_plan(after, tq.roadmap_status(self.read("ROADMAP.md")))
        for p in plan:
            if p.get("unsure"):
                continue
            self.assertIn(p["cls"], ("HUMAN_NOW", "WAITING_FOR_AUTOMATION"), p["entry"]["title"])
            self.assertEqual(p["target"], p["entry"]["section"])
        # every entry left in § 1 / 1b carries the hidden line, and the moved decision sits in § 3
        for e in after:
            if e["section"] in ("1", "1b"):
                self.assertTrue(any(tq.HIDDEN.match(l) for l in e["lines"]), e["title"])
        self.assertIn("Decide: a second ledger tool?", next(e["title"] for e in after if e["section"] == "3"
                                                             and e["title"].startswith("Decide")))
        # every move named in HISTORY, the moved blocks ticked there, nothing open lost
        self.assertIn("## TAYLOR-TODO — the done trail (reconciled", hist)
        for t in ("Add the image API key", "The weekly rhythm", "Walk the trial for free",
                  "A ticked one still in § 1", "Decide: a second ledger tool?"):
            self.assertRegex(hist, re.escape(t) + r".*\*\* — ")
        self.assertIn("- [x] **Add the image API key", hist)
        self.assertLess(hist.index("reconciled"), hist.index("(moved 2026-10-07)"))
        survivors = {e["title"] for e in after} | {e["title"] for e in tq.parse(hist)}
        self.assertEqual(open_before - survivors, set())

    def test_a_waiting_entry_is_ticked_by_code_when_its_row_ships(self):
        rm = self.read("ROADMAP.md").replace("| B144 | the factory | queued |", "| B144 | the factory | done (2026-10-20) |")
        (self.proj / "ROADMAP.md").write_text(rm)
        plan = json.loads(self.run_todo("reconcile", "--json").stdout)
        p = next(p for p in plan if p["title"].startswith("The press link"))
        self.assertEqual((p["class"], p["to"]), ("DONE", "trail"))
        self.assertIn("B144 shipped", p["reason"])
        self.assertNotIn("press link", self.run_todo("now", "--offline").stdout)

    def test_line_by_line(self):
        plan = json.loads(self.run_todo("reconcile", "--json").stdout)
        i = next(p["i"] for p in plan if p["title"].startswith("Add the image API key"))
        self.run_todo("reconcile", "--apply", "--word", "reconcile: yes", "--only", str(i))
        todo = self.read("TAYLOR-TODO.md")
        self.assertNotIn("Add the image API key", todo)
        self.assertIn("The weekly rhythm", todo)          # not named: stays in § 1c for another answer
        self.assertIn("### 1c.", todo)


class AddAndPage(Base):
    def test_add_writes_the_hidden_line(self):
        self.run_todo("add", "Paste the vendor value into the host environment", "--section", "1", "--minutes", "3")
        todo = self.read("TAYLOR-TODO.md")
        m = re.search(r"\*\*Paste the vendor value.*\n(  <!-- todo: .* -->)", todo)
        self.assertTrue(m, todo[-600:])
        self.assertIn("repeat_key=env-value", m.group(1))
        self.assertIn("estimated_minutes=3", m.group(1))
        e = next(e for e in tq.parse(todo) if e["title"].startswith("Paste the vendor"))
        self.assertEqual(e["meta"]["estimated_minutes"], "3")
        self.assertIn("Paste the vendor value", self.run_todo("ls").stdout)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_the_web_page_does_not_show_the_hidden_line(self):
        page = (TOOLS / "todo-site" / "index.html").read_text()
        a, b = page.index("  // ---- markdown"), page.index("  // ---- render")
        js = (page[a:b] + "\nconst fs = require('fs'); const t = fs.readFileSync(0, 'utf8');"
              "for (const s of parse(t)) for (const it of s.items) console.log(bodyHtml(it));")
        md = ("## 1. Now\n\n- [ ] **Do a thing.** It unblocks X. _(Flint, 2026-10-08)_\n"
              "  <!-- todo: repeat_key=env-value; human_reason=automatable; estimated_minutes=2 -->\n")
        script = Path(self.tmp.name) / "render.js"      # the page uses NUL placeholders: a file, not -e
        script.write_text(js)
        r = subprocess.run(["node", str(script)], input=md, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("todo:", r.stdout)
        self.assertNotIn("&lt;!--", r.stdout)
        self.assertIn('class="meta">Flint, 2026-10-08', r.stdout)


class Portable(unittest.TestCase):
    def test_no_venture_literal(self):
        """VISION § Rules 10: the queue is a utility; no product name, domain or price in its code."""
        for f in (TOOLS / "lib" / "todo_queue.py",):
            text = f.read_text().lower()
            for lit in ("patchlamp", "trypatchlamp", "plateful", "$20", "$99"):
                self.assertNotIn(lit, text, f"{f.name} holds {lit}")


if __name__ == "__main__":
    unittest.main()
