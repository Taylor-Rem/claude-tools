"""The AI line, tested (ROADMAP B132, plan ~/projects/plans/53-the-ai-line-tested.md): the batch lane
deals each batch a third each to `none` / `intro` / `foot` while the test is open, every send row and
pipeline line carries the variant, fault key, segment, letter sha and prebuilt flag, a reply keeps its
thread's variant, and `outreach status --by variant` reports without ever deciding for Taylor.

Against the `fake` provider and the stubs of tests/test_outreach_batch.py: nothing is mailed.

    python3 -m unittest discover -s tests -q   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads (tests/_offline.py)

import collections
import importlib.machinery
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_outreach_batch import ADDRESS, BATCH, DISCLOSURE, MONDAY, TEMPLATES, Base, letter_sha  # noqa: E402

HERE = Path(__file__).resolve().parent
LEADS = HERE.parent / "bin" / "leads"
NONE_ANSWER = "Patch, my AI operator, drafted my outreach and sent this reply in words I approved."
USUAL_ANSWER = "Patch, my AI operator, sent this reply in words I approved; I'm told of every one."
REFUSAL = "a letter with no AI sentence goes out only inside the AI-line test"
LINK_BASE = "https://see.trypatchlamp.example"


def body_paras(text):
    """The letter between the greeting and the signature, as paragraphs."""
    paras = [p for p in text.split("\n\n") if p.strip()]
    end = next(i for i, p in enumerate(paras) if p.startswith("Taylor Remund"))
    return paras[1:end]


class AiTest(Base):
    def setUp(self):
        super().setUp()
        self.env["OUTREACH_PROVIDER"] = "fake"      # the fake provider keeps everything in files under state/
        self.approve()

    def fake_rows(self, name):
        p = self.tmp / "state" / "fake" / name
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def queue(self, n=30, batch_id="b-ai-1", *extra):
        picks = self.picks()[:n]
        return self.run_it("send", "--batch", str(self.write_batch(picks, batch_id)), "--go", *extra)

    def letters_by_email(self):
        return {r["to"]: r["text"] for r in self.fake_rows("outbox.jsonl")}

    # -- the deal ----------------------------------------------------------------------
    def test_with_no_test_open_every_letter_carries_the_sentence_beside_the_intro(self):
        r = self.queue(6)
        self.assertIn("AI sentence: intro for every letter", r.stdout)
        self.assertEqual({"intro"}, {s["variant"] for s in self.seqs()})
        self.assertEqual({None}, {s["ai_test"] for s in self.seqs()})

    def test_a_batch_of_thirty_deals_ten_each_and_every_row_carries_the_five(self):
        self.run_it("ai-test", "start")
        r = self.queue(30)
        self.assertIn("AI-line test open: 10 none, 10 intro, 10 foot", r.stdout)
        seqs = self.seqs()
        self.assertEqual({"none": 10, "intro": 10, "foot": 10}, dict(collections.Counter(s["variant"] for s in seqs)))
        self.tick_day(MONDAY)
        rows = [x for x in self.state_rows("sends.jsonl") if x["touch"] == 0]
        self.assertEqual(30, len(rows))
        sha = letter_sha((self.tpl / "batch-first.md").read_text())
        picks = {p["email"]: p for p in self.picks()[:30]}
        by_email = {s["email"]: s for s in seqs}
        letters = self.letters_by_email()
        for row in rows:
            with self.subTest(name=row["name"]):
                for k in ("variant", "fault_key", "segment", "letter_sha", "prebuilt"):
                    self.assertIn(k, row)
                self.assertEqual(by_email[row["email"]]["variant"], row["variant"])
                self.assertEqual(picks[row["email"]]["faults"][0]["key"], row["fault_key"])
                self.assertEqual("services", row["segment"])
                self.assertEqual(sha, row["letter_sha"])
                self.assertIs(False, row["prebuilt"])
                text = letters[row["email"]]
                paras = body_paras(text)
                if row["variant"] == "none":
                    self.assertNotIn("Patch, my AI", text)
                elif row["variant"] == "intro":
                    self.assertEqual(1, text.count(DISCLOSURE))
                    self.assertIn(DISCLOSURE, paras[0].splitlines())
                else:
                    self.assertEqual(1, text.count(DISCLOSURE))
                    self.assertEqual(DISCLOSURE, paras[-1].splitlines()[-1])
                self.assertIn(ADDRESS, text)
                self.assertIn('Reply "no thanks"', text)
        # the pipeline line gets the same five, by `leads log --tag`
        logs = [c["argv"] for c in self.calls("leads") if c["argv"][:1] == ["log"]]
        self.assertEqual(30, len(logs))
        for argv in logs:
            tags = dict(argv[i + 1].split("=", 1) for i, a in enumerate(argv) if a == "--tag")
            self.assertEqual({"variant", "fault_key", "segment", "letter_sha", "prebuilt"}, set(tags))
            self.assertIn(tags["variant"], ("none", "intro", "foot"))
            self.assertEqual("false", tags["prebuilt"])

    def test_no_variant_collects_one_kind_of_fault(self):
        self.run_it("ai-test", "start")
        self.queue(30)
        by_key = collections.defaultdict(collections.Counter)
        for s in self.seqs():
            by_key[s["fault_key"]][s["variant"]] += 1
        for key, c in by_key.items():
            with self.subTest(key=key):
                counts = [c.get(v, 0) for v in ("none", "intro", "foot")]
                self.assertLessEqual(max(counts) - min(counts), 1, f"{key}: {dict(c)}")

    def test_the_deal_is_the_same_on_a_dry_run_and_on_go(self):
        self.run_it("ai-test", "start")
        dry = self.run_it("send", "--batch", str(self.write_batch(self.picks()[:12])), "--dry-run")
        shown = dict(re.findall(r"<([^>]+)> — \"[^\"]*\" \[AI sentence: (\w+)\]", dry.stdout))
        self.assertEqual(12, len(shown))
        self.queue(12)
        self.assertEqual(shown, {s["email"]: s["variant"] for s in self.seqs()})

    def test_a_held_pick_is_not_queued(self):
        r = self.queue(5, "b-hold", "--hold", "2")
        self.assertIn("held back by Taylor", r.stdout)
        self.assertEqual(4, len(self.seqs()))
        self.assertNotIn(self.picks()[1]["email"], {s["email"] for s in self.seqs()})

    # -- start and stop ----------------------------------------------------------------
    def test_stop_keeps_a_placement_and_threads_in_flight_finish_as_they_began(self):
        self.run_it("ai-test", "start")
        self.queue(6, "b-before")
        before = {s["email"]: s["variant"] for s in self.seqs()}
        r = self.run_it("ai-test", "stop", "--keep", "foot")
        self.assertIn("New sequences go out foot", r.stdout)
        self.assertIn("kept foot", self.run_it("ai-test", "show").stdout)
        picks = self.picks()[6:9]
        self.run_it("send", "--batch", str(self.write_batch(picks, "b-after")), "--go")
        after = {s["email"]: s["variant"] for s in self.seqs() if s["batch_id"] == "b-after"}
        self.assertEqual({"foot"}, set(after.values()))
        self.tick_day(MONDAY)
        letters = self.letters_by_email()
        for email, v in before.items():
            with self.subTest(email=email, variant=v):
                if v == "none":                  # began inside the test, so it finishes without the sentence
                    self.assertNotIn("Patch, my AI", letters[email])
                else:
                    self.assertIn(DISCLOSURE, letters[email])

    def test_a_none_sequence_the_test_never_dealt_is_refused(self):
        self.queue(1)
        seqs = self.seqs()
        seqs[0]["variant"] = "none"            # a hand edit: not dealt by the test
        (self.tmp / "state" / "sequences.json").write_text(json.dumps(seqs))
        self.tick_day(MONDAY)
        self.assertEqual([], self.fake_rows("outbox.jsonl"))
        self.assertIn(REFUSAL, self.seqs()[0]["why"])

    def test_status_never_stops_the_test(self):
        self.run_it("ai-test", "start")
        self.run_it("status", "--by", "variant")
        self.assertIn("open since", self.run_it("ai-test", "show").stdout)

    # -- replies keep their variant ------------------------------------------------------
    def reply(self, email, text, rid):
        p = self.tmp / "state" / "fake" / "inbox.jsonl"
        with open(p, "a") as f:
            f.write(json.dumps({"id": rid, "from": email, "subject": "Re: two things I noticed", "text": text,
                                "ts": f"{MONDAY}T15:00:0{len(rid) % 10}-06:00"}) + "\n")

    def test_a_yes_in_a_none_thread_is_stored_under_none_and_answered_with_the_none_sentence(self):
        self.run_it("ai-test", "start")
        self.queue(3)
        self.tick_day(MONDAY)
        by_v = {s["variant"]: s for s in self.seqs()}
        self.reply(by_v["none"]["email"], "Yes please!", "r-none")
        self.reply(by_v["intro"]["email"], "Yes, send it.", "r-intro")
        self.run_it("inbox", OUTREACH_NOW=f"{MONDAY}T16:00:00", OUTREACH_LINK_BASE=LINK_BASE,
                    STUB_PREVIEW_URL="https://previews.patchlamp.com/p/x/")
        rows = {r["email"]: r for r in self.state_rows("replies.jsonl")}
        none_row, intro_row = rows[by_v["none"]["email"]], rows[by_v["intro"]["email"]]
        self.assertEqual(("yes", "none", True), (none_row["class"], none_row["variant"], none_row["answered"]))
        self.assertEqual("intro", intro_row["variant"])
        for row in (none_row, intro_row):
            for k in ("fault_key", "segment", "letter_sha", "prebuilt"):
                self.assertIn(k, row)
        answers = {r["to"]: r["text"] for r in self.fake_rows("sent-replies.jsonl")}
        self.assertIn(NONE_ANSWER, answers[by_v["none"]["email"]])
        self.assertNotIn(USUAL_ANSWER, answers[by_v["none"]["email"]])
        self.assertIn(USUAL_ANSWER, answers[by_v["intro"]["email"]])
        self.assertNotIn(NONE_ANSWER, answers[by_v["intro"]["email"]])

    # -- the report ----------------------------------------------------------------------
    def test_status_by_variant_prints_the_five_per_hundred_and_says_too_few(self):
        self.run_it("ai-test", "start")
        self.queue(30)
        self.tick_day(MONDAY)
        by_v = collections.defaultdict(list)
        for s in self.seqs():
            by_v[s["variant"]].append(s)
        self.reply(by_v["none"][0]["email"], "Yes please.", "r1")
        self.reply(by_v["foot"][0]["email"], "no thanks", "r2")
        self.run_it("inbox", OUTREACH_NOW=f"{MONDAY}T16:00:00")
        out = self.run_it("status", "--by", "variant").stdout
        self.assertIn("delivered", out)
        self.assertIn("preview clicks", out)
        self.assertIn("replies", out)
        self.assertIn("positive", out)
        self.assertIn("customers", out)
        lines = {l.split()[0]: l for l in out.splitlines() if l.startswith("  ") and l.split()[0] in
                 ("none", "intro", "foot")}
        self.assertEqual({"none", "intro", "foot"}, set(lines))
        self.assertRegex(lines["none"], r"none\s+10\s+0 \(0\.0\)\s+1 \(10\.0\)\s+1 \(10\.0\)\s+0 \(0\.0\)")
        self.assertRegex(lines["foot"], r"foot\s+10\s+0 \(0\.0\)\s+1 \(10\.0\)\s+0 \(0\.0\)\s+0 \(0\.0\)")
        self.assertIn("Too few to decide", out)
        self.assertNotIn("Directional", out)

    def test_above_the_floor_it_says_directional_and_never_proven(self):
        self.run_it("ai-test", "start")
        started = json.loads((self.tmp / "state" / "ai-test.json").read_text())["started"]
        sends, replies = [], []
        for v, n_reply in (("none", 24), ("intro", 14), ("foot", 10)):
            for k in range(120):
                pid, email = f"P-{v}-{k}", f"o{k}@{v}.example"
                sends.append({"ts": f"{MONDAY}T09:00:00-06:00", "date": MONDAY, "touch": 0, "template": "batch-first",
                              "place_id": pid, "email": email, "batch_id": "b", "variant": v, "fault_key": "hours",
                              "segment": "services", "letter_sha": "a" * 64, "prebuilt": False, "ai_test": started})
                if k < n_reply:
                    replies.append({"date": MONDAY, "place_id": pid, "email": email,
                                    "class": "interested" if k % 4 else "not now"})
        state = self.tmp / "state"
        (state / "sends.jsonl").write_text("".join(json.dumps(x) + "\n" for x in sends))
        (state / "replies.jsonl").write_text("".join(json.dumps(x) + "\n" for x in replies))
        pipe = self.tmp / "pipeline.jsonl"
        pipe.write_text(json.dumps({"place_id": "P-none-1", "outcome": "won"}) + "\n")
        out = self.run_it("status", "--by", "variant", LEADS_PIPELINE=str(pipe)).stdout
        self.assertIn("Directional, not proven: none leads with 20.0 replies per hundred delivered, against "
                      "11.7 (intro), 8.3 (foot)", out)
        self.assertNotIn("Too few", out)
        self.assertNotRegex(out.replace("not proven", ""), r"\bproven\b")
        self.assertRegex(out, r"none\s+120\s+0 \(0\.0\)\s+24 \(20\.0\)\s+18 \(15\.0\)\s+1 \(0\.8\)")
        # the other cuts read the same rows
        self.assertIn("hours", self.run_it("status", "--by", "fault", LEADS_PIPELINE=str(pipe)).stdout)
        self.assertIn("not prebuilt", self.run_it("status", "--by", "prebuilt", LEADS_PIPELINE=str(pipe)).stdout)

    # -- the checker -----------------------------------------------------------------------
    def module(self, **env):
        """bin/outreach loaded in-process under this test's environment (its paths are read at import)."""
        old = dict(os.environ)
        os.environ.update({k: str(v) for k, v in {**self.env, **env}.items()})
        try:
            loader = importlib.machinery.SourceFileLoader("outreach_b132", str(HERE.parent / "bin" / "outreach"))
            spec = importlib.util.spec_from_loader("outreach_b132", loader)
            m = importlib.util.module_from_spec(spec)
            loader.exec_module(m)
        finally:
            os.environ.clear()
            os.environ.update(old)
        return m

    def test_the_checker_passes_none_only_inside_the_test(self):
        m = self.module()
        for name in ("batch-first", "batch-second", "batch-third"):
            with self.subTest(name=name, test="closed"):
                bad = m.check_batch_template(name)
                self.assertEqual(1, len(bad), bad)
                self.assertIn(REFUSAL, bad[0])
                self.assertIn("the reply to a yes says it", bad[0])
                self.assertEqual([], m.check_batch_template(name, none_ok=True))
        self.run_it("ai-test", "start")
        for name in ("batch-first", "batch-second", "batch-third"):
            with self.subTest(name=name, test="open"):
                self.assertEqual([], m.check_batch_template(name))
        self.assertEqual([], m.check_template("answer-yes"))

    def test_the_checker_catches_a_sentence_in_the_wrong_place(self):
        p = self.tpl / "batch-first.md"
        text = p.read_text().replace("[?ai_foot] ", "[?ai_intro] ")       # both lines on for intro, none for foot
        p.write_text(text)
        m = self.module()
        bad = " ".join(m.check_batch_template("batch-first", none_ok=True))
        self.assertIn("isn't there exactly once", bad)
        self.assertIn("(two faults, foot)", bad)

    def test_go_still_works_with_the_test_closed(self):
        r = self.queue(3)
        self.assertNotIn(REFUSAL, r.stdout + r.stderr)
        self.assertEqual(3, len(self.seqs()))

    def test_approve_prints_all_three_renderings(self):
        out = self.run_it("approve", "--template", "batch-first", "--template", "answer-yes").stdout
        for label in ("batch-first.md — AI sentence intro", "batch-first.md — AI sentence foot",
                      "batch-first.md — AI sentence none (only inside the AI-line test)",
                      "answer-yes.md — in a `none` thread of the AI-line test"):
            self.assertIn(label, out)
        self.assertIn(NONE_ANSWER, out)

    def test_doctor_shows_the_test_state(self):
        r = self.run_it("doctor", expect=None)
        self.assertIn("AI-line test: not started", r.stdout)
        self.assertNotIn(REFUSAL, r.stdout)

    def test_the_preview_lane_letters_have_no_variant(self):
        for name in ("first", "second", "third"):
            self.assertNotIn("[?ai_", (TEMPLATES / f"{name}.md").read_text())


@unittest.skipUnless((Path.home() / "projects/client-leads/wasatch.db").exists(), "needs the census")
class LeadsTag(unittest.TestCase):
    def test_log_keeps_the_tags_under_outbound(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, LEADS_STATE=tmp, LEADS_LEDGER=f"{tmp}/ledger.jsonl",
                       CLAUDE_TOOLS_ENV=f"{tmp}/no-env", LEADS_MAIL_ADDRESS="", GOOGLE_MAPS_API_KEY="",
                       LEADS_PIPELINE=f"{tmp}/pipeline.jsonl", LEADS_GROUPS_LOG=f"{tmp}/groups.md")
            r = subprocess.run([sys.executable, str(LEADS), "log", "Nowhere Test Plumbing", "messaged", "email day 0",
                                "--via", "email", "--channel", "email", "--email", "x@nowhere.example",
                                "--tag", "variant=none", "--tag", "fault_key=hours_saturday",
                                "--tag", "segment=services", "--tag", "letter_sha=abc", "--tag", "prebuilt=false"],
                               capture_output=True, text=True, env=env)
            self.assertEqual(0, r.returncode, r.stderr)
            [e] = [json.loads(l) for l in Path(f"{tmp}/pipeline.jsonl").read_text().splitlines()]
            self.assertEqual({"variant": "none", "fault_key": "hours_saturday", "segment": "services",
                              "letter_sha": "abc", "prebuilt": False}, e["outbound"])
            bad = subprocess.run([sys.executable, str(LEADS), "log", "Nowhere Test Plumbing", "talked",
                                  "--tag", "novalue"], capture_output=True, text=True, env=env)
            self.assertNotEqual(0, bad.returncode)
            self.assertIn("key=value", bad.stderr)


if __name__ == "__main__":
    unittest.main()
