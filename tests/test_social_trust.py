"""social packet / draft / facts / pick / receipt / lessons (B133, plan ~/projects/plans/54-a-feed-you-can-trust.md).

    python3 -m unittest tests.test_social_trust   (from claude-tools/)

Hermetic: a made-up ~/projects tree (a DATA_STORY with the 2026-10-06 post's public numbers, a CLAIMS
table, a research line that was corrected, a Prices.php), stand-ins for both writers, the judge and the
picker (SOCIAL_WRITER_OPUS, SOCIAL_WRITER_CODEX, SOCIAL_FACTS_JUDGE, SOCIAL_PICKER: a shell command that
reads the prompt on stdin), nothing posted. The same three faults are checked against the real files
and a real judge by hand: ~/projects/social/facts/fixtures/.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOCIAL = HERE.parent / "bin" / "social"
DATE = "2026-10-06"     # a Tuesday: a data post

DATA_STORY = """# Citable numbers

## v3 — CITABLE

| restaurants | 2552 |

## Services census — CITABLE (2026-09-28, ROADMAP B43)

### Ready-to-use lines (all true as of 2026-09-28)

- "We checked 5,865 independent service, creative, retail and nonprofit
  businesses from Ogden to Santaquin. 21% have no website of their own:
  857 none at all, 181 a dead link."
- "Of the home and field services, 23% have no site of their
  own; for handymen it's 45%."
- "181 businesses along the Wasatch Front send Google's visitors to a
  dead link; most are business.site pages Google shut down in 2024."

### Headline

| businesses | n |
|---|---|
| operational independents (the set) | 5865 |
| none | 857 = 15% |
| dead | 181 = 3% |
"""
# line numbers the fixtures below cite (1-based)
L_CHECKED, L_HOME, L_DEAD, L_ROW = "11-13", "14-15", "16-17", 25

CLAIMS = """# Claims

| Claim on the page | Source | Status |
|---|---|---|
| Usually in a minute | the relay ticks every minute | true now |
| "Free · no account · nothing to sign" · "What's wrong with your Google listing?" (/check) | GET /check | true now |
"""

BRIEF = """# Brief

1. Shops are many.
2. Nobody local takes the change by text — corrected: three shops do take a change by text; the difference is speed. Every plan I found takes email, a form or a portal.
"""

PRICES = """<?php
final class Prices
{
    public const TIERS = [
        'hosting' => [
            'name' => 'Hosting',
            'monthly' => 2_000,
            'usage' => 1_000,
            'topup' => 5_000,
        ],
        'starter' => [
            'name' => 'Starter',
            'monthly' => 9_900,
            'usage' => 10_000,
        ],
    ];
}
"""

TOPICS = """# topics
- [number] 181 businesses here still send Google's visitors to a dead link. That is 3% of the 5,865 I checked. (DATA_STORY § Services: dead 181 = 3%; link /check, else /templates)
- [number] The plans take changes by email. (research/b/brief.md:4; link /compare)
"""

GOOD = {"caption": "181 businesses from Ogden to Santaquin send Google's visitors to a dead link. Most are business.site "
                   "pages Google shut down in 2024. That is 3% of the 5,865 I checked. Is yours one? Patched.\npatchlamp.com/check",
        "ledger": [{"sentence": "181 businesses from Ogden to Santaquin send Google's visitors to a dead link.",
                    "sources": [f"client-leads/DATA_STORY_STATS.md:{L_CHECKED}", f"client-leads/DATA_STORY_STATS.md:{L_DEAD}"]},
                   {"sentence": "Most are business.site pages Google shut down in 2024.", "sources": [f"client-leads/DATA_STORY_STATS.md:{L_DEAD}"]},
                   {"sentence": "That is 3% of the 5,865 I checked.",
                    "sources": [f"client-leads/DATA_STORY_STATS.md:{L_ROW}", f"client-leads/DATA_STORY_STATS.md:{L_CHECKED}"]}]}


def judge_says(*verdicts):
    return {"looked": True, "sentences": [{"n": i, "verdict": v, "why": f"because {i}"} for i, v in enumerate(verdicts, 1)]}


class TrustTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        self.projects = root / "projects"
        for rel, text in (("client-leads/DATA_STORY_STATS.md", DATA_STORY), ("patchlamp/CLAIMS.md", CLAIMS),
                          ("research/b/brief.md", BRIEF), ("patchlamp/app/Support/Prices.php", PRICES)):
            p = self.projects / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        self.social = self.projects / "social"
        (self.social / "topics").mkdir(parents=True)
        (self.social / "topics" / "patchlamp.md").write_text(TOPICS)
        (self.social / "rules.md").write_text("# rules\n- a number stands on a line in a file\n")
        self.posted = self.social / "posted.jsonl"
        self.posted.write_text(json.dumps({"date": "2026-10-05", "status": "posted", "kind": "text",
                                           "caption": "Can I just text it a photo of my price list? Yes."}) + "\n")
        self.marketing = self.projects / "marketing"
        (self.marketing / "copy").mkdir(parents=True)
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def stand_in(self, obj, name=None, keep=None):
        """A shell command that keeps its prompt in `keep` and prints obj."""
        self.n += 1
        f = self.root / f"answer{self.n}.txt"
        f.write_text("thinking it over\n" + (obj if isinstance(obj, str) else json.dumps(obj)))
        return (f"cat > {keep}; " if keep else "cat > /dev/null; ") + f"cat {f}"

    def run_social(self, *args, **env_extra):
        env = dict(os.environ, SOCIAL_DIR=str(self.social), SOCIAL_PROJECTS=str(self.projects),
                   SOCIAL_MARKETING_DIR=str(self.marketing), CLAUDE_TOOLS_ENV=str(self.root / "no-env"),
                   SOCIAL_LEDGER=str(self.root / "ledger.jsonl"))
        for k in ("SOCIAL_WRITER_OPUS", "SOCIAL_WRITER_CODEX", "SOCIAL_FACTS_JUDGE", "SOCIAL_PICKER"):
            env.pop(k, None)
        env.update(env_extra)
        return subprocess.run([sys.executable, str(SOCIAL), *args], capture_output=True, text=True, env=env, cwd=self.tmp.name)

    def draft_file(self, d, name="d.json"):
        f = self.root / name
        f.write_text(json.dumps(d))
        return str(f)

    def lessons(self):
        f = self.social / "lessons.md"
        return f.read_text() if f.exists() else ""

    # ---- the packet --------------------------------------------------------------------------

    def test_packet_quotes_source_lines_with_file_and_line(self):
        r = self.run_social("packet", "--date", DATE)
        self.assertEqual(r.returncode, 0, r.stderr)
        md = (self.social / "packets" / f"{DATE}.md").read_text()
        self.assertIn("topics/patchlamp.md:2", md)
        self.assertIn("client-leads/DATA_STORY_STATS.md:16-17", md)
        self.assertIn("most are business.site pages Google shut down in 2024", md)
        self.assertIn("| dead | 181 = 3% |", md)
        self.assertIn("Services census", md)                     # the section is named beside the line
        self.assertIn("Can I just text it a photo", md)           # the last posts
        self.assertIn("a number stands on a line in a file", md)  # the rule sheet
        day = json.loads((self.social / "packets" / f"{DATE}.json").read_text())
        self.assertEqual(day["kind"], "data")

    def test_packet_quotes_a_captured_count(self):
        r = self.run_social("facts", "--date", DATE, "capture", "--", "echo", "kits this week: 24 checked")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.run_social("packet", "--date", DATE)
        md = (self.social / "packets" / f"{DATE}.md").read_text()
        self.assertIn(f"social/facts/{DATE}.md", md)
        self.assertIn("kits this week: 24 checked", md)

    def test_sunday_has_no_post(self):
        r = self.run_social("packet", "--date", "2026-10-04")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Sunday", r.stderr)

    # ---- the fact check, code layer --------------------------------------------------------------

    def test_numbers_in_no_file_fail_in_code_with_the_sentence(self):
        """2026-10-03: the week's counts came from the kit runs, which are in no file."""
        judge = self.root / "judge-ran"
        d = {"date": "2026-10-03", "caption": "Counted the week: 24 trades, painters to HVAC. 12 send Google to a "
             "Facebook page, 7 to a link that won't load. Fair. Patched.",
             "ledger": [{"sentence": "Counted the week: 24 trades, painters to HVAC.", "sources": ["this week's remote kits"]}]}
        r = self.run_social("facts", "--draft", self.draft_file(d), SOCIAL_FACTS_JUDGE=f"touch {judge}")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("fail (code)", r.stdout)
        self.assertIn("Counted the week: 24 trades", r.stdout)
        self.assertIn("not a line in a file", r.stdout)
        self.assertIn("12 send Google to a Facebook page", r.stdout)     # a number with no ledger line at all
        self.assertFalse(judge.exists(), "the judge isn't asked once code has failed")
        self.assertIn("2026-10-03 · a number needs a line in a file", self.lessons())   # a fact lesson, by itself

    def test_a_price_off_pricing_fails_in_code(self):
        d = {"caption": "A site kept right by text, $79 a month. Patched.", "ledger": []}
        r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons")
        self.assertEqual(r.returncode, 1)
        self.assertIn("$79 is not a plan price on /pricing", r.stdout)
        d = {"caption": "Starter is $99 a month. Patched.", "ledger": [{"sentence": "Starter is $99 a month.", "sources": ["/pricing:starter"]}]}
        r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons",
                            SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported")))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_ledger_line_not_in_its_file_fails_in_code(self):
        d = {"caption": "181 businesses send visitors to a dead link. Patched.",
             "ledger": [{"sentence": "181 businesses send visitors to a dead link.",
                         "sources": ["client-leads/DATA_STORY_STATS.md:5"], "quote": "181 businesses along the Wasatch Front"}]}
        r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons")
        self.assertEqual(r.returncode, 1)
        self.assertIn("that line now reads", r.stdout)
        d["ledger"][0]["sources"] = ["client-leads/DATA_STORY_STATS.md:900"]
        r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons")
        self.assertIn("the file has", r.stdout)
        d["ledger"][0]["sources"] = ["../outside.md:1"]
        (self.root / "outside.md").write_text("181 businesses along the Wasatch Front\n")
        r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons")
        self.assertIn("isn't a file under ~/projects", r.stdout)

    def test_a_number_not_in_the_line_it_cites_fails(self):
        d = {"caption": "182 businesses send visitors to a dead link. Patched.",
             "ledger": [{"sentence": "182 businesses send visitors to a dead link.", "sources": [f"client-leads/DATA_STORY_STATS.md:{L_DEAD}"]}]}
        r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons")
        self.assertEqual(r.returncode, 1)
        self.assertIn("182 is not in the line it cites", r.stdout)

    def test_spelled_out_numbers_and_units_are_checked(self):
        d = {"caption": "Twenty-four trades checked this week. Patched.", "ledger": []}
        r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons")
        self.assertEqual(r.returncode, 1)
        self.assertIn("it has a number (24)", r.stdout)
        # 181 is in the line, but as a count, not a percentage
        d = {"caption": "181% of businesses send visitors to a dead link. Patched.",
             "ledger": [{"sentence": "181% of businesses send visitors to a dead link.", "sources": [f"client-leads/DATA_STORY_STATS.md:{L_DEAD}"]}]}
        r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons")
        self.assertIn("181% is not in the line it cites", r.stdout)
        d = {"caption": "Three percent of them send visitors to a dead link. Patched.",
             "ledger": [{"sentence": "Three percent of them send visitors to a dead link.", "sources": [f"client-leads/DATA_STORY_STATS.md:{L_ROW}"]}]}
        r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons",
                            SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported")))
        self.assertEqual(r.returncode, 0, r.stdout)          # "three percent" is "3%" and the row says 3%

    def test_only_plan_prices_are_prices(self):
        d = {"caption": "Top-ups are $50. Patched.", "ledger": [{"sentence": "Top-ups are $50.", "sources": ["/pricing:hosting"]}]}
        r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons")
        self.assertEqual(r.returncode, 1)
        self.assertIn("$50 is not a plan price", r.stdout)

    def test_a_draft_or_topic_line_is_never_a_source(self):
        (self.marketing / "copy" / "feed-2026-10-06.md").write_text("24 trades\n")
        (self.social / "facts").mkdir()
        (self.social / "facts" / f"{DATE}.md").write_text("kits: 24 trades\n")
        for ref, ok in (("marketing/copy/feed-2026-10-06.md:1", False), ("social/topics/patchlamp.md:2", False),
                        (f"social/facts/{DATE}.md:1", True)):
            d = {"caption": "24 trades this week. Patched.", "ledger": [{"sentence": "24 trades this week.", "sources": [ref]}]}
            r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons",
                                SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported")))
            self.assertEqual(r.returncode == 0, ok, ref + r.stdout)
            if not ok:
                self.assertIn("is not a source", r.stdout)

    def test_an_empty_packet_fails_every_cite(self):
        (self.social / "topics" / "patchlamp.md").write_text("# nothing\n")
        self.run_social("packet", "--date", DATE)
        self.run_social("draft", "--date", DATE, "--no-codex", SOCIAL_WRITER_OPUS=self.stand_in(
            {"caption": "181 businesses send visitors to a dead link. Patched.",
             "ledger": [{"sentence": "181 businesses send visitors to a dead link.", "sources": [f"client-leads/DATA_STORY_STATS.md:{L_DEAD}"]}]}))
        r = self.run_social("facts", "--date", DATE, SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported")))
        self.assertEqual(r.returncode, 1)
        self.assertIn("today's packet holds no source lines", r.stdout)

    def test_no_claim_cant_wave_a_fact_through(self):
        d = {"caption": "Most owners fix it in a day. Is yours one? Patched.",
             "ledger": [{"sentence": "Most owners fix it in a day.", "sources": [f"client-leads/DATA_STORY_STATS.md:{L_DEAD}"]}]}
        r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons",
                            SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("no claim", "no claim")))
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("\"Most owners fix it in a day.\" — unsure: called no claim", r.stdout)
        self.assertIn("\"Is yours one?\" — no claim", r.stdout)

    def test_a_clock_time_needs_no_source(self):
        d = {"caption": "2:14am. Zero calls. Made a portrait of the mug instead. Patched.", "ledger": []}
        r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons",
                            SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("no claim", "no claim", "no claim")))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # ---- the fact check, the judge ---------------------------------------------------------------

    def test_a_sentence_that_says_more_than_its_stat_fails_by_the_judge(self):
        """2026-09-29: the numbers are in the file; 'a blank where the link goes' is more than the stat."""
        prompt = self.root / "judge-prompt.txt"
        d = {"date": "2026-09-29", "caption": "Of the home and field services here, 23% have no site of their own. "
             "The listing has a blank where the link goes. Patched.",
             "ledger": [{"sentence": "Of the home and field services here, 23% have no site of their own.",
                         "sources": [f"client-leads/DATA_STORY_STATS.md:{L_HOME}"]},
                        {"sentence": "The listing has a blank where the link goes.", "sources": [f"client-leads/DATA_STORY_STATS.md:{L_HOME}"]}],
             "why": ["SECRET-REASON the writer gave"]}
        r = self.run_social("facts", "--draft", self.draft_file(d),
                            SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported", "not supported"), keep=prompt))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("fail (judge)", r.stdout)
        self.assertIn("\"The listing has a blank where the link goes.\" — not supported", r.stdout)
        p = prompt.read_text()
        self.assertIn("23% have no site of their", p)            # the cited line, re-read from the file
        self.assertNotIn("SECRET-REASON", p)                      # never the writer's reasons
        self.assertIn('"unsure"', p)
        self.assertIn("one of", p)                                # the schema names the choices, fills none in
        self.assertIn("2026-09-29 · a sentence says no more than its source", self.lessons())

    def test_a_stale_line_fails_by_the_judge(self):
        d = {"caption": "Every plan I found takes changes by email, a form or a portal. Patched.",
             "ledger": [{"sentence": "Every plan I found takes changes by email, a form or a portal.",
                         "sources": ["research/b/brief.md:4"], "quote": "Every plan I found takes email, a form or a portal"}]}
        r = self.run_social("facts", "--draft", self.draft_file(d), "--no-lessons",
                            SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("not supported")))
        self.assertEqual(r.returncode, 1)
        self.assertIn("\"Every plan I found takes changes by email, a form or a portal.\" — not supported", r.stdout)

    def test_unsure_is_a_fail_and_a_garbled_judge_is_couldnt(self):
        f = self.draft_file(GOOD)
        r = self.run_social("facts", "--draft", f, "--no-lessons",
                            SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported", "unsure", "supported", "no claim")))
        self.assertEqual(r.returncode, 1)
        self.assertIn("unsure", r.stdout)
        r = self.run_social("facts", "--draft", f, "--no-lessons", SOCIAL_FACTS_JUDGE=self.stand_in("no json here"))
        self.assertEqual(r.returncode, 4)
        r = self.run_social("facts", "--draft", f, "--no-lessons",
                            SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported", "probably", "supported", "no claim")))
        self.assertEqual(r.returncode, 4)
        r = self.run_social("facts", "--draft", f, "--no-lessons",
                            SOCIAL_FACTS_JUDGE=self.stand_in({"looked": False, "why": "the sources were cut off"}))
        self.assertEqual(r.returncode, 4)
        self.assertIn("the sources were cut off", r.stdout)

    # ---- a morning, end to end -------------------------------------------------------------------

    def opus_answer(self):
        return {"caption": GOOD["caption"], "why": ["the number first", "one aside", "then stop"],
                "ledger": [{"sentence": e["sentence"], "sources": e["sources"]} for e in GOOD["ledger"]]}

    def test_codex_timeout_posts_on_one_draft_and_says_so(self):
        before = self.posted.read_text()
        self.run_social("packet", "--date", DATE)
        r = self.run_social("draft", "--date", DATE, SOCIAL_WRITER_OPUS=self.stand_in(self.opus_answer()),
                            SOCIAL_WRITER_CODEX="sleep 5", SOCIAL_CODEX_TIMEOUT="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("one draft today (codex timeout", r.stdout)
        assign = (self.marketing / "assignments" / f"feed-{DATE}.md").read_text()
        self.assertIn("| dead | 181 = 3% |", assign)           # the packet inline: Codex can't read outside marketing/
        self.assertIn("marketing/copy/feed-2026-10-06.md", assign)
        r = self.run_social("facts", "--date", DATE,
                            SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported", "supported", "supported", "no claim")))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        img = self.root / "photo.jpg"
        img.write_bytes(b"\xff\xd8not really")
        r = self.run_social("pick", "--date", DATE, "--image", str(img), "--mood", "direct", "--art", "stock")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("queued as draft 1", r.stdout)
        q = json.loads(next((self.social / "queue").glob("*.json")).read_text())
        self.assertEqual((q["day"], q["kind"], q["writer"], q["facts"]), (DATE, "data", "opus", "pass"))
        r = self.run_social("receipt", "1")
        out = r.stdout
        self.assertIn("written by Opus (the only draft)", out)
        self.assertIn("one draft today: Codex timeout", out)
        self.assertNotIn("Codex: cost not reported", out)
        self.assertIn(f"client-leads/DATA_STORY_STATS.md:{L_DEAD}", out)
        self.assertIn("facts: pass", out)
        self.assertLessEqual(len(out.splitlines()), 12)
        pick = [json.loads(x) for x in (self.social / "picks.jsonl").read_text().splitlines()]
        self.assertEqual(pick[-1]["how"], "only")
        self.assertEqual(self.posted.read_text(), before, "nothing in this flow writes posted.jsonl")

    def test_two_drafts_are_picked_blind_and_logged(self):
        self.run_social("packet", "--date", DATE)
        codex = dict(self.opus_answer(), caption=GOOD["caption"].replace("Is yours one?", "Yours could be one."))
        r = self.run_social("draft", "--date", DATE, SOCIAL_WRITER_OPUS=self.stand_in(self.opus_answer()),
                            SOCIAL_WRITER_CODEX=self.stand_in("## Proposed\n...\n```json\n" + json.dumps(codex) + "\n```"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.run_social("facts", "--date", DATE,
                        SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported", "supported", "supported", "no claim")))
        prompt = self.root / "pick-prompt.txt"
        r = self.run_social("pick", "--date", DATE, SOCIAL_PICKER=self.stand_in(
            {"choice": "A", "prefer": "A", "argument": "the question invites a check"}, keep=prompt))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        p = prompt.read_text()
        self.assertNotIn("opus", p.lower())
        self.assertNotIn("codex", p.lower())
        self.assertIn("Draft A", p)
        self.assertIn("the number first", p)                      # both sets of reasons
        row = json.loads((self.social / "picks.jsonl").read_text().splitlines()[-1])
        self.assertEqual(row["how"], "pick")
        self.assertEqual(row["won"], row["labels"]["A"])
        self.assertEqual(row["argument"], "the question invites a check")

    def test_a_failed_splice_falls_back_to_the_preferred_draft(self):
        self.run_social("packet", "--date", DATE)
        self.run_social("draft", "--date", DATE, SOCIAL_WRITER_OPUS=self.stand_in(self.opus_answer()),
                        SOCIAL_WRITER_CODEX=self.stand_in(self.opus_answer()))
        self.run_social("facts", "--date", DATE,
                        SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported", "supported", "supported", "no claim")))
        r = self.run_social("pick", "--date", DATE, SOCIAL_PICKER=self.stand_in(
            {"choice": "splice", "prefer": "B", "caption": "Nine thousand dead links, $5 to fix. Patched.", "ledger": [],
             "argument": "shorter"}))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        row = json.loads((self.social / "picks.jsonl").read_text().splitlines()[-1])
        self.assertEqual(row["how"], "splice-failed")
        self.assertEqual(row["won"], row["labels"]["B"])
        self.assertIn("$5 is not a plan price on /pricing", self.lessons())

    def test_a_splice_keeps_each_sentence_s_source(self):
        self.run_social("packet", "--date", DATE)
        self.run_social("draft", "--date", DATE, SOCIAL_WRITER_OPUS=self.stand_in(self.opus_answer()),
                        SOCIAL_WRITER_CODEX=self.stand_in(self.opus_answer()))
        self.run_social("facts", "--date", DATE,
                        SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported", "supported", "supported", "no claim")))
        r = self.run_social("pick", "--date", DATE, SOCIAL_PICKER=self.stand_in(
            {"choice": "splice", "prefer": "A", "argument": "the dead link and the share, no aside",
             "caption": "181 businesses from Ogden to Santaquin send Google's visitors to a dead link. That is 3% of the 5,865 I checked. Patched."}),
            SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported", "supported")))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        row = json.loads((self.social / "picks.jsonl").read_text().splitlines()[-1])
        self.assertEqual(row["how"], "splice")
        led = [json.loads(x) for x in (self.root / "ledger.jsonl").read_text().splitlines()]
        self.assertEqual((led[-1]["kind"], led[-1]["verdict"], led[-1]["won"]), ("social-words", "pass", "splice"))
        # notional subscription cost: plan_usd_list, never cost_usd (books counts cost_usd as money spent)
        self.assertEqual(led[-1]["cost_usd"], 0)
        self.assertIn("plan_usd_list", led[-1])

    def test_pick_kind_demo_copies_the_tiles_demo_fields_and_posted_says_which_demo(self):
        self.run_social("packet", "--date", DATE)
        self.run_social("draft", "--date", DATE, "--no-codex", SOCIAL_WRITER_OPUS=self.stand_in(self.opus_answer()))
        self.run_social("facts", "--date", DATE,
                        SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported", "supported", "supported", "no claim")))
        img = self.root / "tile.jpg"
        img.write_bytes(b"\xff\xd8not really")
        (self.root / "tile.json").write_text(json.dumps({"kind": "demo", "project": "demo-service", "page": "/",
                                                         "ask": "Saturday hours are 8 to 3", "golden": "abc123",
                                                         "box": {"x": 1}}))
        r = self.run_social("pick", "--date", DATE, "--image", str(img), "--kind", "demo")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        q = json.loads(next((self.social / "queue").glob("*.json")).read_text())
        self.assertEqual(q["kind"], "demo")
        self.assertEqual(q["demo"], {"project": "demo-service", "page": "/", "ask": "Saturday hours are 8 to 3",
                                     "golden": "abc123"})

    def test_a_writer_that_declines_is_passed_on_and_no_draft_means_none(self):
        self.run_social("packet", "--date", DATE)
        r = self.run_social("draft", "--date", DATE, "--no-codex", SOCIAL_WRITER_OPUS=self.stand_in(
            {"caption": "", "declined": "nothing true to post in this shape today, because the census is a week old"}))
        self.assertEqual(r.returncode, 1)
        self.assertIn("declined — nothing true to post in this shape today, because the census is a week old", r.stdout)
        r = self.run_social("receipt", "--date", DATE)
        self.assertIn("the census is a week old", r.stdout)

    def test_no_passing_draft_goes_to_taylor(self):
        self.run_social("packet", "--date", DATE)
        self.run_social("draft", "--date", DATE, "--no-codex", SOCIAL_WRITER_OPUS=self.stand_in(self.opus_answer()))
        r = self.run_social("facts", "--date", DATE,
                            SOCIAL_FACTS_JUDGE=self.stand_in(judge_says("supported", "not supported", "supported", "no claim")))
        self.assertEqual(r.returncode, 1)
        r = self.run_social("pick", "--date", DATE)
        self.assertEqual(r.returncode, 1)
        self.assertIn("goes to Taylor for post / swap / skip", r.stdout)

    # ---- lessons ------------------------------------------------------------------------------------

    def test_a_taste_rule_waits_for_keep(self):
        r = self.run_social("lessons", "propose", "Lead with the number - the 10/6 pick", "One aside, then stop")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Reply keep N or drop N", r.stdout)
        self.assertNotIn("Lead with the number", self.lessons())
        self.run_social("lessons", "drop", "2")
        self.assertNotIn("One aside", self.lessons())
        r = self.run_social("lessons", "keep", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Lead with the number - the 10/6 pick (kept by Taylor)", self.lessons().split("## Taste")[1])
        r = self.run_social("lessons", "keep", "1")
        self.assertNotEqual(r.returncode, 0)     # nothing left to keep

    def test_taste_lines_are_capped(self):
        (self.social / "lessons.md").write_text("# l\n\n## Facts\n\n## Taste\n\n" + "".join(f"- rule {i}\n" for i in range(12)))
        self.run_social("lessons", "propose", "one more")
        r = self.run_social("lessons", "keep", "1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("retire one first", r.stderr)

    def test_fact_lessons_dedupe(self):
        d = {"caption": "A site for $79. Patched.", "ledger": []}
        f = self.draft_file(d)
        self.run_social("facts", "--draft", f)
        self.run_social("facts", "--draft", f)
        self.assertEqual(self.lessons().count("$79 is not a plan price"), 1)


if __name__ == "__main__":
    unittest.main()
