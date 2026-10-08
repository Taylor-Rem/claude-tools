"""social check, queue --hold/--kind (B112, plan 48): a stand-in judge, nothing posted.

    python3 -m unittest tests.test_social_check   (from claude-tools/)

SOCIAL_JUDGE stands in for `claude -p` (like PREP_CLAUDE in prep): a shell
command that reads the prompt on stdin and prints what a judge would.
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
FIXTURE = HERE / "fixtures" / "social" / "no-product.jpg"


def answer(**kw):
    base = {"looked": True, "product": "yes", "product_what": "a phone with message bubbles",
            "raccoon": "same", "why": "the notched ear and the brass boom"}
    base.update(kw)
    return base


class SocialCheckTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.social = self.dir / "social"
        self.social.mkdir()
        self.prompt_file = self.dir / "prompt.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def run_social(self, *args, judge=None):
        env = dict(os.environ, SOCIAL_DIR=str(self.social), CLAUDE_TOOLS_ENV=str(self.dir / "no-env"),
                   IMG_PATCH_REF=str(FIXTURE))
        if judge is not None:
            # the stand-in keeps the prompt it was given, then answers
            env["SOCIAL_JUDGE"] = f"cat > {self.prompt_file}; {judge}"
        return subprocess.run([sys.executable, str(SOCIAL), *args], capture_output=True, text=True, env=env,
                              cwd=self.tmp.name)

    def says(self, obj, wrap=False):
        text = "Looked at both.\n" + json.dumps(obj)
        if wrap:   # the shape `claude -p --output-format json` prints
            text = json.dumps({"type": "result", "is_error": False, "result": text})
        f = self.dir / "answer.txt"
        f.write_text(text)
        return f"cat {f}"

    # -- the acceptance line ------------------------------------------------------------

    # B129: a text post is asked the change question now (tests/test_social_demo.py); the product question stays
    # for the pinned explainer, so these walk it there.

    def test_the_fixture_with_no_product_fails_a_pinned_post_with_its_reason(self):
        r = self.run_social("check", "--image", str(FIXTURE), "--kind", "pinned",
                            judge=self.says(answer(product="no", product_what="just the raccoon")))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no product in the picture", r.stdout)
        self.assertIn("just the raccoon", r.stdout)

    def test_a_product_and_the_same_raccoon_pass(self):
        r = self.run_social("check", "--image", str(FIXTURE), "--kind", "pinned", judge=self.says(answer(), wrap=True))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(r.stdout.startswith("pass:"))

    # -- the other answers -------------------------------------------------------------

    def test_a_different_raccoon_fails_any_kind(self):
        for kind in ("pinned", "raccoon"):
            r = self.run_social("check", "--image", str(FIXTURE), "--kind", kind,
                                judge=self.says(answer(raccoon="different")))
            self.assertEqual(r.returncode, 1, kind)
            self.assertIn("different raccoon", r.stdout)

    def test_unsure_is_never_a_fail(self):
        for a in (answer(product="unsure"), answer(raccoon="unsure")):
            r = self.run_social("check", "--image", str(FIXTURE), "--kind", "pinned", judge=self.says(a))
            self.assertEqual(r.returncode, 3, r.stdout)
            self.assertTrue(r.stdout.startswith("unsure:"))

    def test_a_judge_that_could_not_look_goes_to_taylor_with_its_reason(self):
        r = self.run_social("check", "--image", str(FIXTURE), "--kind", "text",
                            judge=self.says(answer(looked=False, why="the draft file would not open")))
        self.assertEqual(r.returncode, 4)
        self.assertIn("would not open", r.stdout)
        self.assertIn("Taylor", r.stdout)

    def test_a_garbled_or_silent_judge_is_couldnt_not_fail(self):
        for judge in ("echo 'I think it looks fine'", "exit 2"):
            r = self.run_social("check", "--image", str(FIXTURE), "--kind", "text", judge=judge)
            self.assertEqual(r.returncode, 4, judge)

    def test_the_prompt_allows_unsure_and_suggests_no_answer(self):
        self.run_social("check", "--image", str(FIXTURE), "--kind", "text", judge=self.says(answer()))
        prompt = self.prompt_file.read_text()
        self.assertIn('"unsure" is a good answer', prompt)
        self.assertIn("budget", prompt)
        self.assertIn("there is no answer we are hoping for", prompt)
        self.assertNotIn("MUST", prompt)

    def test_a_raccoon_post_may_show_no_product_but_must_show_the_raccoon(self):
        r = self.run_social("check", "--image", str(FIXTURE), "--kind", "raccoon",
                            judge=self.says(answer(product="no")))
        self.assertEqual(r.returncode, 0, r.stdout)
        r = self.run_social("check", "--image", str(FIXTURE), "--kind", "raccoon",
                            judge=self.says(answer(raccoon="absent")))
        self.assertEqual(r.returncode, 1, r.stdout)

    def test_a_second_raccoon_post_in_six_fails_without_asking_the_judge(self):
        with (self.social / "posted.jsonl").open("w") as f:
            for pillar in ("ask", "room", "number"):
                f.write(json.dumps({"date": "2026-10-01", "pillar": pillar, "status": "posted"}) + "\n")
        r = self.run_social("check", "--image", str(FIXTURE), "--kind", "raccoon", judge="exit 9")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("one in seven", r.stdout)
        self.assertFalse(self.prompt_file.exists())

    def test_a_data_post_skips_the_judge(self):
        r = self.run_social("check", "--image", str(FIXTURE), "--kind", "data", judge="exit 9")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse(self.prompt_file.exists())

    def test_fable_is_refused_as_the_judge(self):
        env = dict(os.environ, SOCIAL_DIR=str(self.social), CLAUDE_TOOLS_ENV=str(self.dir / "no-env"),
                   IMG_PATCH_REF=str(FIXTURE), SOCIAL_JUDGE_MODEL="fable", PATH="/usr/bin:/bin")
        env.pop("SOCIAL_JUDGE", None)
        r = subprocess.run([sys.executable, str(SOCIAL), "check", "--image", str(FIXTURE), "--kind", "text"],
                           capture_output=True, text=True, env=env, cwd=self.tmp.name)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("never runs on Fable", r.stderr)

    # -- the queue ---------------------------------------------------------------------

    def test_check_n_writes_the_verdict_on_the_draft_and_queue_ls_shows_it(self):
        r = self.run_social("queue", "add", "patchlamp", str(FIXTURE), "Ask for anything. Patched.",
                            "--pillar", "pinned", "--kind", "pinned", "--hold")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("held", r.stdout)
        r = self.run_social("check", "1", judge=self.says(answer()))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        [j] = (self.social / "queue").glob("*.json")
        d = json.loads(j.read_text())
        self.assertEqual(d["check"]["verdict"], "pass")
        self.assertEqual(d["kind"], "pinned")
        ls = self.run_social("queue")
        self.assertIn("[pinned] [held] [pass]", ls.stdout)

    def test_a_bare_post_skips_a_held_draft(self):
        self.run_social("queue", "add", "patchlamp", str(FIXTURE), "the explainer", "--hold")
        # with only a held draft, a bare post refuses before it reaches any network
        env = dict(os.environ, SOCIAL_DIR=str(self.social), CLAUDE_TOOLS_ENV=str(self.dir / "no-env"),
                   PATCHLAMP_URL="http://127.0.0.1:9", PATCHLAMP_RELAY_SHARED_SECRET="shh")
        r = subprocess.run([sys.executable, str(SOCIAL), "post", "patchlamp"], capture_output=True, text=True,
                           env=env, cwd=self.tmp.name)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("held", r.stderr)


if __name__ == "__main__":
    unittest.main()
