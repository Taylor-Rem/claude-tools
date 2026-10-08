"""social demo + the change question (B129, plan ~/projects/plans/51-feed-shows-the-change.md).

    python3 -m unittest tests.test_social_demo   (from claude-tools/)

A made-up demo repo with a `golden` tag stands in for the template demos, SOCIAL_DEMO_EDITOR for the
Sonnet change run (a shell command in the copy's directory, the prompt on stdin) and SOCIAL_JUDGE for
the judge. The shots are real (`shot`, headless Chromium on loopback); nothing is posted.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402

import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOCIAL = HERE.parent / "bin" / "social"
PORTRAIT = HERE / "fixtures" / "social" / "no-product.jpg"
BLANK_RIGHT = HERE / "fixtures" / "social" / "demo-blank-right.jpg"
HAVE_SHOT = bool(shutil.which("shot")) and bool(shutil.which("magick"))

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Fernway Lawn</title>
<style>body{font-family:sans-serif;margin:0;background:#f4f6f5;color:#123} .bar{background:#123;color:#fff;padding:12px}
section{padding:40px 24px;min-height:500px;border-top:1px solid #ccd} li{margin:8px 0}</style></head>
<body>
<div class="bar">This is a demo. Fernway Lawn is not a real company.</div>
<section><h1>Fernway Lawn</h1><p>Mowing, edging and leaves.</p></section>
<section><h2>What we do</h2><p>Weekly mowing.</p><p>Spring cleanup.</p></section>
<section><h2>Hours</h2><ul><li>Mon-Fri: 8am-5pm</li><li>Sat: 9am-1pm</li><li>Sun: closed</li></ul></section>
<section><p>Text the demo number to change anything here.</p></section>
</body></html>
"""


def load_social():
    loader = importlib.machinery.SourceFileLoader("social_mod", str(SOCIAL))
    spec = importlib.util.spec_from_loader("social_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def change_answer(**kw):
    base = {"looked": True, "change": "yes", "asked": "Saturday hours 8 to 3", "changed": "the Saturday line reads 8am-3pm",
            "why": "the bubble and the boxed line say the same thing"}
    base.update(kw)
    return base


class DemoBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.social = self.dir / "social"
        self.social.mkdir()
        self.clients = self.dir / "clients"
        self.repo = self.clients / "demo-lawn" / "repos" / "fernway"
        self.repo.mkdir(parents=True)
        (self.clients / "demo-lawn" / "CLAUDE.md").write_text("# demo-lawn workspace\nThe demo bar stays.\n")
        (self.repo / "index.html").write_text(PAGE)
        git = ["git", "-C", str(self.repo), "-c", "user.email=t@example.com", "-c", "user.name=t"]
        subprocess.run(git[:3] + ["init", "-q"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-qm", "golden"], check=True)
        subprocess.run(git[:3] + ["tag", "golden"], check=True)
        self.golden_sha = subprocess.run(git[:3] + ["rev-parse", "golden"], capture_output=True, text=True).stdout.strip()
        self.out = self.dir / "tiles"
        self.prompt_file = self.dir / "editor-prompt.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def env(self, **extra):
        env = dict(os.environ, SOCIAL_DIR=str(self.social), CLAUDE_TOOLS_ENV=str(self.dir / "no-env"),
                   IMG_PATCH_REF=str(PORTRAIT), SOCIAL_CLIENTS=str(self.clients), SOCIAL_LEDGER=str(self.dir / "ledger.jsonl"))
        env.update(extra)
        return env

    def editor(self, edit="", said=None, done=True, couldnt=""):
        """A stand-in change run: keeps its prompt, makes EDIT (a shell line, in the copy's directory), answers."""
        ans = {"done": done, "changed": said or "the Saturday line", "couldnt": couldnt}
        f = self.dir / "editor-answer.txt"
        f.write_text(json.dumps({"type": "result", "is_error": False, "total_cost_usd": 0.01,
                                 "result": "Done.\n" + json.dumps(ans)}))
        return f"cat > {self.prompt_file}; {edit} cat {f}"

    def demo(self, *args, editor=None, **env):
        e = self.env(**env)
        if editor is not None:
            e["SOCIAL_DEMO_EDITOR"] = editor
        return subprocess.run([sys.executable, str(SOCIAL), "demo", "--project", "demo-lawn", "--out", str(self.out), *args],
                              capture_output=True, text=True, env=e, cwd=self.tmp.name, timeout=300)


SAT = "sed -i 's/Sat: 9am-1pm/Sat: 8am-3pm/' repos/fernway/index.html;"


@unittest.skipUnless(HAVE_SHOT, "shot and ImageMagick are needed for the demo tile")
class SocialDemoTest(DemoBase):
    def test_a_tile_is_made_from_a_copy_of_golden_and_the_live_demo_is_untouched(self):
        r = self.demo("--ask", "Saturday hours are 8 to 3 now", editor=self.editor(SAT))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        [tile] = self.out.glob("*.jpg")
        size = subprocess.run(["magick", "identify", "-format", "%w %h", str(tile)], capture_output=True, text=True).stdout
        self.assertEqual(size, "1080 1350")
        side = json.loads(tile.with_suffix(".json").read_text())
        self.assertEqual(side["kind"], "demo")
        self.assertEqual(side["project"], "demo-lawn")
        self.assertEqual(side["page"], "/")
        self.assertEqual(side["ask"], "Saturday hours are 8 to 3 now")
        self.assertEqual(side["golden"], self.golden_sha)
        self.assertIn("not a customer", side["what"])
        self.assertNotIn("customer", side["ask"])
        # the box is the one changed line: about one line tall, somewhere in the hours section, not the page
        self.assertLess(side["box"]["h"], 120)
        self.assertGreater(side["box"]["y"], 1000)
        # the live repo is as golden left it
        self.assertEqual((self.repo / "index.html").read_text(), PAGE)
        self.assertEqual(subprocess.run(["git", "-C", str(self.repo), "status", "--porcelain"], capture_output=True,
                                        text=True).stdout, "")
        # the change run was told its budget, that "I couldn't" is fine, and given the ask; the workspace notes were beside it
        prompt = self.prompt_file.read_text()
        self.assertIn("ten minutes", prompt)
        self.assertIn("I couldn't", prompt)
        self.assertIn("Saturday hours are 8 to 3 now", prompt)
        self.assertIn("repos/fernway/", prompt)
        self.assertIn("never read as a real customer", prompt)
        self.assertNotIn("MUST", prompt)
        # one ledger line for the run
        [row] = [json.loads(x) for x in (self.dir / "ledger.jsonl").read_text().splitlines()]
        self.assertEqual(row["kind"], "social-demo")
        self.assertEqual(row["cost_usd"], 0)            # notional: books counts cost_usd as money spent
        self.assertEqual(row["plan_usd_list"], 0.01)
        self.assertFalse(list((self.social / "queue").glob("*.json")) if (self.social / "queue").exists() else [])

    def test_the_run_saw_the_workspace_notes(self):
        r = self.demo("--ask", "Saturday hours are 8 to 3 now",
                      editor=self.editor(f"cp CLAUDE.md {self.dir}/seen.md; " + SAT))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("The demo bar stays.", (self.dir / "seen.md").read_text())

    def test_an_added_line_marks_the_new_line_not_everything_below_it(self):
        add = "sed -i 's|<li>Sun: closed</li>|<li>Sun: closed</li><li>Holidays: by appointment</li>|' repos/fernway/index.html;"
        r = self.demo("--ask", "Add that holidays are by appointment", "--json", editor=self.editor(add))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        side = json.loads(Path(out["tile"]).with_suffix(".json").read_text())
        self.assertLess(side["box"]["h"], 120, side["box"])

    def test_a_style_change_with_no_text_falls_back_to_the_pixel_box(self):
        css = "sed -i 's|li{margin:8px 0}|li{margin:8px 0} h2{color:#c00}|' repos/fernway/index.html;"
        r = self.demo("--ask", "Make the headings red", editor=self.editor(css))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_i_couldnt_is_passed_on_as_it_is(self):
        r = self.demo("--ask", "Put our Yelp reviews on the site",
                      editor=self.editor(done=False, couldnt="there are no Yelp reviews in the demo to put up"))
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("I couldn't: there are no Yelp reviews in the demo to put up", r.stdout)
        self.assertFalse(self.out.exists() and list(self.out.glob("*.jpg")))

    def test_an_unchanged_page_is_i_couldnt(self):
        r = self.demo("--ask", "Saturday hours are 8 to 3 now", editor=self.editor("", said="changed the hours"))
        self.assertEqual(r.returncode, 4)
        self.assertIn("looks the same", r.stdout)
        self.assertIn("changed the hours", r.stdout)

    def test_most_of_the_page_changed_is_i_couldnt(self):
        allp = ("python3 -c \"import re,sys; f='repos/fernway/index.html'; s=open(f).read(); "
                "open(f,'w').write(re.sub(r'>([^<]+)<', lambda m: '>' + m.group(1).upper() + '<', s))\";")
        r = self.demo("--ask", "Make it all bigger", editor=self.editor(allp))
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("no one thing to mark", r.stdout)

    def test_a_run_past_its_budget_is_i_couldnt(self):
        r = self.demo("--ask", "Saturday hours are 8 to 3 now", editor="sleep 30", SOCIAL_DEMO_TIMEOUT="2")
        self.assertEqual(r.returncode, 4)
        self.assertIn("did not finish within 2 seconds", r.stdout)

    def test_after_skips_the_run(self):
        after = self.dir / "by-hand"
        shutil.copytree(self.repo, after, ignore=shutil.ignore_patterns(".git"))
        (after / "index.html").write_text(PAGE.replace("Sat: 9am-1pm", "Sat: 8am-3pm"))
        r = self.demo("--ask", "Saturday hours are 8 to 3 now", "--after", str(after), editor="exit 9")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.prompt_file.exists())

    def test_queue_makes_a_demo_draft_that_waits_for_checked_words_on_a_text_day(self):
        r = self.demo("--ask", "Saturday hours are 8 to 3 now", "--queue", "Hours by text. Patched.", editor=self.editor(SAT))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        [j] = (self.social / "queue").glob("*.json")
        d = json.loads(j.read_text())
        self.assertEqual(d["kind"], "demo")
        self.assertEqual(d["demo"]["project"], "demo-lawn")
        # a Monday: a demo draft is a text day's post, so B133's gate holds its unchecked words
        p = subprocess.run([sys.executable, str(SOCIAL), "post", "patchlamp", "1"], capture_output=True, text=True,
                           env=self.env(SOCIAL_TODAY="2026-10-05", PATCHLAMP_URL="http://127.0.0.1:9",
                                        PATCHLAMP_RELAY_SHARED_SECRET="shh"), cwd=self.tmp.name)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("unchecked words", p.stderr)


class SocialDemoRefusals(DemoBase):
    def test_a_repo_without_golden_is_not_a_demo(self):
        subprocess.run(["git", "-C", str(self.repo), "tag", "-d", "golden"], check=True, capture_output=True)
        r = self.demo("--ask", "Saturday hours are 8 to 3 now", editor="exit 9")
        self.assertEqual(r.returncode, 1)
        self.assertIn("isn't one of the template demos", r.stderr)

    def test_a_long_ask_is_refused(self):
        r = self.demo("--ask", "word " * 60, editor="exit 9")
        self.assertEqual(r.returncode, 1)
        self.assertIn("feed size", r.stderr)


class MarkChanged(unittest.TestCase):
    def test_only_the_new_or_changed_elements_are_marked(self):
        s = load_social()
        after = PAGE.replace("<li>Sat: 9am-1pm</li>", "<li>Sat: 8am-3pm</li>").replace(
            "<p>Spring cleanup.</p>", "<p>Spring cleanup.</p><p>Aeration in April.</p>")
        html = s.mark_changed(PAGE, after)
        self.assertEqual(html.count("data-patch-mark>"), 2)
        self.assertIn("<li>Sat: <span data-patch-mark>8am-3pm</span></li>", html)   # the edited words, not the line
        self.assertIn("<p data-patch-mark>Aeration in April.</p>", html)            # a new element whole
        self.assertIn("[data-patch-mark]", html.split("</head>")[0])
        self.assertIsNone(s.mark_changed(PAGE, PAGE.replace("li{margin:8px 0}", "li{margin:9px 0}")))

    def test_words_added_to_a_paragraph_are_marked_alone_and_a_rewrite_marks_the_element(self):
        s = load_social()
        self.assertEqual(s._mark_words("Weekly mowing. Edging too.", "Weekly mowing."),
                         "Weekly mowing. <span data-patch-mark>Edging too.</span>")
        self.assertEqual(s._mark_words("a b c d new1 e f new2 new3", "a b c d old e f"),
                         "a b c d <span data-patch-mark>new1</span> e f <span data-patch-mark>new2 new3</span>")
        self.assertIsNone(s._mark_words("all new words", "nothing alike here"))
        html = s.mark_changed(PAGE, PAGE.replace("<p>Mowing, edging and leaves.</p>", "<p>Mowing, <b>edging</b> and snow.</p>"))
        self.assertIn("<p data-patch-mark>Mowing, ", html)    # child tags inside: the element whole


class ChangeQuestion(unittest.TestCase):
    """social check for demo and text posts: "can you see what changed on the page?" (B129)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "social").mkdir()
        self.prompt_file = self.dir / "prompt.txt"
        self.seen = self.dir / "seen.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, kind, ans, image=BLANK_RIGHT):
        f = self.dir / "answer.txt"
        f.write_text(ans if isinstance(ans, str) else "Looked.\n" + json.dumps(ans))
        env = dict(os.environ, SOCIAL_DIR=str(self.dir / "social"), CLAUDE_TOOLS_ENV=str(self.dir / "no-env"),
                   IMG_PATCH_REF=str(PORTRAIT), SOCIAL_JUDGE=f"cat > {self.prompt_file}; ls > {self.seen}; cat {f}")
        return subprocess.run([sys.executable, str(SOCIAL), "check", "--image", str(image), "--kind", kind],
                              capture_output=True, text=True, env=env, cwd=self.tmp.name)

    def test_the_blank_right_tile_fails_when_the_judge_sees_no_change(self):
        r = self.check("demo", change_answer(change="no", changed="", why="the right half is empty"))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("can't see what changed on the page", r.stdout)
        self.assertIn("the right half is empty", r.stdout)

    def test_a_demo_the_judge_can_read_passes_with_what_it_read(self):
        r = self.check("demo", change_answer())
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("asked: Saturday hours 8 to 3", r.stdout)
        self.assertIn("changed: the Saturday line reads 8am-3pm", r.stdout)

    def test_the_demo_prompt_asks_the_change_question_alone_and_without_the_portrait(self):
        self.check("demo", change_answer())
        prompt = self.prompt_file.read_text()
        self.assertIn("Can you see what changed on the page?", prompt)
        self.assertIn("drawn phone", prompt)
        self.assertNotIn("portrait", prompt)
        self.assertNotIn("Does the picture show what Patchlamp sells", prompt)
        self.assertIn('"unsure" is a good answer', prompt)
        self.assertIn("budget", prompt)
        self.assertIn("there is no answer we are hoping for", prompt)
        self.assertNotIn("MUST", prompt)
        self.assertEqual(self.seen.read_text().split(), ["draft.jpg"])

    def test_unsure_is_never_a_fail(self):
        r = self.check("demo", change_answer(change="unsure"))
        self.assertEqual(r.returncode, 3)
        self.assertTrue(r.stdout.startswith("unsure:"))

    def test_a_judge_that_could_not_look_goes_to_taylor(self):
        r = self.check("demo", change_answer(looked=False, why="the file would not open"))
        self.assertEqual(r.returncode, 4)
        self.assertIn("would not open", r.stdout)
        self.assertIn("Taylor", r.stdout)

    def test_an_answer_off_the_choices_is_couldnt(self):
        for ans in (change_answer(change="maybe"), "no json here"):
            self.assertEqual(self.check("demo", ans).returncode, 4)

    def test_a_text_post_is_asked_the_change_question_and_the_raccoon_question(self):
        r = self.check("text", change_answer(raccoon="same"), image=PORTRAIT)
        self.assertEqual(r.returncode, 0, r.stdout)
        prompt = self.prompt_file.read_text()
        self.assertIn("Can you see what changed on the page?", prompt)
        self.assertIn("same character as the portrait", prompt)
        self.assertNotIn("Does the picture show what Patchlamp sells", prompt)
        self.assertNotIn("drawn phone", prompt)        # the reason doesn't describe the text post's own picture as a fault
        self.assertEqual(sorted(self.seen.read_text().split()), ["draft.jpg", "portrait.jpg"])

    def test_no_change_on_a_text_post_is_unsure_and_a_different_raccoon_fails(self):
        # a text post's picture is still a generated raccoon with a drawn phone, so "no" posts with the doubt shown
        r = self.check("text", change_answer(change="no", raccoon="same"), image=PORTRAIT)
        self.assertEqual(r.returncode, 3, r.stdout)
        self.assertTrue(r.stdout.startswith("unsure: the judge can't see what changed on the page"), r.stdout)
        r = self.check("text", change_answer(raccoon="different"), image=PORTRAIT)
        self.assertEqual(r.returncode, 1)
        self.assertIn("different raccoon", r.stdout)
        r = self.check("text", change_answer(raccoon="unsure"), image=PORTRAIT)
        self.assertEqual(r.returncode, 3)

    def test_raccoon_and_data_posts_keep_their_questions(self):
        r = self.check("raccoon", {"looked": True, "product": "no", "product_what": "-", "raccoon": "same", "why": "-"},
                       image=PORTRAIT)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("Does the picture show what Patchlamp sells", self.prompt_file.read_text())


if __name__ == "__main__":
    unittest.main()
