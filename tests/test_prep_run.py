"""The prep run, end to end (ROADMAP B67, plan ~/projects/plans/28-prep-run.md § Acceptance): the
pick, the conductor's stages, the gates, the message, the batch pass, finish — all against a fake
`claude` (tests/fixtures/prep/fake-claude, which really runs the renderer and `prep check` inside the
boundary) and fake `shot`, `notify`, `site`, `client` and `img`. No network, no model, no money, and
nothing published: the census is B44's fixture rows, the listings are fixtures, and the previews tree
is a temporary directory.

    python3 -m unittest tests.test_prep_run -q   (from claude-tools/)

What's pinned: the pick's order and what it leaves out; a run reaches ten (here three) ready sites
through research → build → check → judge → batch → finish; a business whose gates keep failing is
fixed once and then dropped, and the reserve takes its place; the judge's fix list comes back to the
same builder and its drop is final; every session's usage is kept by stage and none of it on Fable;
a build session cannot publish or message anyone; the publish, the 56-day hold, the ledger row and
`notify` are code's, after the gates pass a second time; `sent 1 3 4` logs three of them; a second
run picks others; a killed run finishes under `prep resume`; and a run that would publish refuses
until Taylor has approved the frame and made the previews project.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import json
import os
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
PREP = TOOLS / "bin" / "prep"
LEADS = TOOLS / "bin" / "leads"
FIX = HERE / "fixtures" / "prep"
FAKE = FIX / "fake-claude"
SERVICES = HERE / "fixtures" / "leads-services"

# The three fixture businesses a run is proved on: a service site and two portfolio ones.
POOL, JENNA, ROSIE = "FX_S01", "FX_C01", "FX_C03"
SLUGS = {POOL: "mikes-pool-care", JENNA: "photography-by-jenna", ROSIE: "rosies-florals"}

FAKE_SHOT = r'''#!/usr/bin/env python3
"""A fake `shot`: no browser. `shot doctor` passes (FAKE_SHOT_NO_BROWSER makes it fail, as an install
without Playwright does), `shot check` passes, `shot <page> [--out F]` writes a tiny PNG, and every call
is logged to FAKE_SHOT_LOG. FAKE_SHOT_FAIL is a substring: a target holding it fails check."""
import base64, json, os, sys
from pathlib import Path
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAQAAAADCAIAAAA7ljmRAAAAEklEQVR4nGNgYGD4z8DAwMDAAAAMAAHKhOSVAAAAAElFTkSuQmCC")
VALUED = {"--out", "--selector", "--width", "--height", "--dpr", "--wait", "--timeout", "--wait-for", "--scroll-to"}
argv = sys.argv[1:]
if os.environ.get("FAKE_SHOT_LOG"):
    with open(os.environ["FAKE_SHOT_LOG"], "a") as f:
        f.write(json.dumps({"argv": argv, "cwd": os.getcwd()}) + "\n")
if argv[:1] == ["doctor"]:
    print("shot doctor (fake)")
    print("  OK   headless Chromium launches (fake 1.0)")
    sys.exit(1 if os.environ.get("FAKE_SHOT_NO_BROWSER") else 0)
sub = argv[0] if argv and argv[0] in ("check", "text", "site", "css", "diff") else None
rest = argv[1:] if sub else argv
targets, out, i = [], None, 0
while i < len(rest):
    a = rest[i]
    if a in VALUED and i + 1 < len(rest):
        if a == "--out":
            out = rest[i + 1]
        i += 2
    elif a.startswith("-"):
        i += 1
    else:
        targets.append(a)
        i += 1
bad = os.environ.get("FAKE_SHOT_FAIL")
if sub == "check":
    if bad and any(bad in t for t in targets):
        print(f"✗ {targets[0]}: a console error (fake)")
        sys.exit(1)
    for t in targets or ["."]:
        print(f"✓ {t}: no console errors, no broken images, no sideways scroll")
    sys.exit(0)
dest = Path(out) if out else Path("shots") / ((Path(targets[0]).stem if targets else "shot") + ".png")
dest.parent.mkdir(parents=True, exist_ok=True)
dest.write_bytes(PNG)
print(dest)
'''

FAKE_NOTIFY = r'''#!/usr/bin/env python3
"""A fake `notify`: appends each message to FAKE_NOTIFY_LOG and sends nothing."""
import json, os, sys
p = os.environ.get("FAKE_NOTIFY_LOG")
if p:
    with open(p, "a") as f:
        f.write(json.dumps({"argv": sys.argv[1:], "text": sys.argv[1] if len(sys.argv) > 1 else ""}) + "\n")
print("sent")
'''

FAKE_SITE = r'''#!/usr/bin/env python3
"""A fake `site`: records the call, touches no Cloudflare project. FAKE_SITE_FAIL makes the publish
fail the way a missing project does."""
import json, os, sys
from pathlib import Path
argv = sys.argv[1:]
with open(os.environ["FAKE_SITE_LOG"], "a") as f:
    f.write(json.dumps({"tool": "site", "argv": argv, "cwd": os.getcwd(),
                        "admin": os.environ.get("SITE_ADMIN")}) + "\n")
if argv[:1] == ["previews"]:
    if "--ls" in argv and not os.environ.get("FAKE_SITE_PROJECT"):
        print("no Pages project patchlamp-previews yet (publish once to make it)", file=sys.stderr)
        sys.exit(1)
    if os.environ.get("FAKE_SITE_FAIL"):
        print("wrangler pages deploy failed: no such project", file=sys.stderr)
        sys.exit(1)
    print("pages host: patchlamp-previews.pages.dev")
print("ok")
'''

FAKE_IMG = r'''#!/usr/bin/env python3
"""A fake `img`: twenty made-up Pexels ids for every search (so two previews would collide without
the registry) and a real tiny PNG on disk. `gen` is never reached here: prep is stock only."""
import base64, json, os, random, sys
from pathlib import Path
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAQAAAADCAIAAAA7ljmRAAAAEklEQVR4nGNgYGD4z8DAwMDAAAAMAAHKhOSVAAAAAElFTkSuQmCC")
argv = sys.argv[1:]
with open(os.environ["FAKE_IMG_LOG"], "a") as f:
    f.write(json.dumps(argv) + "\n")
def opt(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default
if argv[0] == "stock":
    skip = set()
    if opt("--skip-file"):
        skip = {l.strip() for l in Path(opt("--skip-file")).read_text().splitlines() if l.strip()}
    pool = [str(900 + i) for i in range(20) if str(900 + i) not in skip]
    random.Random(opt("--seed")).shuffle(pool)
    out = Path(opt("--out")); out.mkdir(parents=True, exist_ok=True)
    got = []
    for pid in pool[:1]:
        path = out / f"photo-{pid}.jpg"
        path.write_bytes(PNG)
        got.append({"path": str(path), "id": int(pid), "photographer": "A. Fixture",
                    "alt": "a made-up photo", "url": "https://example.test/" + pid})
    print(json.dumps(got))
else:
    sys.exit("fake img: prep runs `img stock` only")
'''


def fixture_census(path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("leads_services_build_run", SERVICES / "build.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.build(path, businesses=True)


def prep_module():
    import importlib.util
    from importlib.machinery import SourceFileLoader
    spec = importlib.util.spec_from_loader("prep_run_mod", SourceFileLoader("prep_run_mod", str(PREP)))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


P = prep_module()


class Base(unittest.TestCase):
    """One temporary world a run happens in: the fixture census, the fixture listings on disk, the
    fake tools on their own PATH-free hooks, and every state directory inside the temporary dir."""

    listings = (POOL, JENNA, ROSIE)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.t = Path(self.tmp.name)
        self.db = fixture_census(t / "census.db")
        (t / "leads" / "details").mkdir(parents=True)
        for pid in self.listings:
            shutil.copy(FIX / "details" / f"{pid}.json", t / "leads" / "details" / f"{pid}.json")
        self.bin = t / "bin"
        self.bin.mkdir()
        for name, body in (("shot", FAKE_SHOT), ("notify", FAKE_NOTIFY), ("site", FAKE_SITE), ("img", FAKE_IMG)):
            p = self.bin / name
            p.write_text(body)
            p.chmod(0o755)
        self.plan = t / "plan.json"
        self.write_plan({})
        self.env = dict(os.environ)
        for k in list(self.env):
            if k.startswith(("PREP_", "FAKE_", "LEADS_")):
                self.env.pop(k)
        self.env.update({
            "LEADS_DB": str(self.db), "LEADS_STATE": str(t / "leads"), "LEADS_LEDGER": str(t / "ledger.jsonl"),
            "LEADS_PREVIEWS": str(t / "previews"), "LEADS_PIPELINE": str(t / "pipeline.jsonl"),
            "LEADS_GROUPS_LOG": str(t / "groups.md"), "LEADS_MAIL_ADDRESS": "", "LEADS_SEGMENT": "",
            "LEADS_PREVIEW_BIN": str(self.bin), "LEADS_IMG_BIN": str(self.bin / "img"),
            "PREP_STATE": str(t / "prep"), "PREP_LEDGER": str(t / "ledger.jsonl"),
            "PREP_REQUESTS": str(t / "requests"), "PREP_CLAUDE": str(FAKE),
            "PREP_SHOT": str(self.bin / "shot"), "PREP_NOTIFY": str(self.bin / "notify"),
            "PREP_TODAY": "2026-09-29", "PREP_PARALLEL": "2", "PREP_RESERVE": "1",
            "PROJECTS_DIR": str(t / "projects"), "CLAUDE_TOOLS_ENV": str(t / "no-env"),
            "GOOGLE_MAPS_API_KEY": "", "OUTREACH_STATE": str(t / "outreach"),
            "FAKE_CLAUDE_LOG": str(t / "fake.jsonl"), "FAKE_CLAUDE_FACTS": str(FIX / "facts-good.json"),
            "FAKE_CLAUDE_FACTS_DIR": str(FIX / "facts"), "FAKE_PLAN": str(self.plan),
            "FAKE_SHOT_LOG": str(t / "shot.jsonl"), "FAKE_NOTIFY_LOG": str(t / "notify.jsonl"),
            "FAKE_SITE_LOG": str(t / "site.jsonl"), "FAKE_IMG_LOG": str(t / "img.jsonl"),
            "ANTHROPIC_API_KEY": "sk-ant-FAKEkeyNEVERreal000",   # proves every session strips it
        })

    def tearDown(self):
        self.tmp.cleanup()

    # -- the world's levers --------------------------------------------------------------

    def write_plan(self, plan):
        self.plan.write_text(json.dumps(plan))

    def approve_and_make_the_project(self):
        """Taylor's two: the frame approved, and the previews project on record."""
        (self.t / "previews").mkdir(exist_ok=True)
        (self.t / "previews" / "project.json").write_text(json.dumps(
            {"project": "patchlamp-previews", "pages_host": "patchlamp-previews.pages.dev"}))
        r = self.run_prep("approve")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def run_prep(self, *args, env=None, timeout=300):
        return subprocess.run([sys.executable, str(PREP), *args], capture_output=True, text=True,
                              env=dict(self.env, **(env or {})), timeout=timeout)

    def run_leads(self, *args, env=None):
        return subprocess.run([sys.executable, str(LEADS), *args], capture_output=True, text=True,
                              env=dict(self.env, **(env or {})))

    def night(self, *places, n=None, publish=False, extra=(), env=None):
        """One whole night in the foreground. Returns (result, run_dir)."""
        args = ["run", "--foreground", "--places", *places]
        if n is not None:
            args += ["--n", str(n)]
        if not publish:
            args.append("--no-publish")
        r = self.run_prep(*args, *extra, env=env)
        return r, self.run_dir()

    # -- reading it back ------------------------------------------------------------------

    def run_dir(self, name=None):
        runs = sorted(p for p in (self.t / "prep").iterdir() if (p / "run.json").exists())
        self.assertTrue(runs, "no run directory")
        return (self.t / "prep" / name) if name else runs[-1]

    def rj(self, run_dir=None):
        return json.loads(((run_dir or self.run_dir()) / "run.json").read_text())

    def stages(self, run_dir=None):
        return {s: b.get("stage") for s, b in self.rj(run_dir)["businesses"].items()}

    def rows(self, path):
        p = self.t / path
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def sessions(self, stage=None):
        return [r for r in self.rows("fake.jsonl") if "-p" in (r.get("argv") or [])
                and (stage is None or r.get("stage") == stage)]

    def notices(self):
        return [r["text"] for r in self.rows("notify.jsonl")]


# ---- the pick -------------------------------------------------------------------------------------

class PickTest(Base):
    def test_fit_first_then_a_reach_with_evidence_then_miles(self):
        """B73: strength first (strong, good, weak), then the fit, a reach with evidence and miles as the tie-break."""
        env = {"LEADS_STRENGTH": str(self.t / "no-strength.md")}           # bin/leads' default weights
        r = self.run_prep("pick", "--n", "3", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = [l for l in r.stdout.splitlines() if re.match(r"^\s*\d+\.", l)]
        names = [re.sub(r"^\s*\d+\.\s*", "", l).split(" · ")[0] for l in lines]
        # Jenna is strong; Mike and Rosie good (the fit, then nearest); Glacier weak (6 reviews), so it is last
        self.assertEqual(names[:3], ["Photography by Jenna", "Mike's Pool Care", "Rosie's Florals"])
        self.assertEqual(names[3], "Glacier Snow Removal")
        self.assertIn(" — strong · ", lines[0])
        self.assertIn(" — weak · ", lines[3])
        self.assertIn("no reach (Instagram, Facebook or email)", r.stdout)
        j = json.loads(self.run_prep("pick", "--n", "3", "--json", env=env).stdout)
        self.assertEqual([p["strength"] for p in j["picks"]], ["strong", "good", "good", "weak"])
        self.assertTrue(j["picks"][0]["reasons"])

    def test_a_strong_lead_outranks_a_weak_one_that_is_nearer(self):
        env = {"LEADS_STRENGTH": str(self.t / "no-strength.md")}
        j = json.loads(self.run_prep("pick", "--n", "20", "--allow-calls", "--json", env=env).stdout)
        by = {p["name"]: (i, p) for i, p in enumerate(j["picks"])}
        wasatch, glacier = by["Wasatch Pest Pros"], by["Glacier Snow Removal"]
        self.assertEqual((wasatch[1]["strength"], glacier[1]["strength"]), ("strong", "weak"))
        self.assertLess(glacier[1]["miles"], wasatch[1]["miles"])                # the weak one is nearer…
        self.assertLess(wasatch[0], glacier[0])                                   # …and still comes after
        ranks = [{"strong": 0, "good": 1, "weak": 2}[p["strength"]] for p in j["picks"]]
        self.assertEqual(ranks, sorted(ranks))

    def test_only_segments_whose_template_has_looks_and_three_of_a_category_at_most(self):
        j = json.loads(self.run_prep("pick", "--n", "10", "--json").stdout)
        self.assertTrue(all(p["segment"] in ("services", "creatives") for p in j["picks"]), j["picks"])
        self.assertTrue(all(p["template"] in ("service", "portfolio") for p in j["picks"]))
        self.assertIn("its template has no looks yet", " ".join(j["skipped"]))
        cats = {}
        for p in j["picks"]:
            cats[p["category"]] = cats.get(p["category"], 0) + 1
        self.assertTrue(all(v <= 3 for v in cats.values()), cats)

    def test_a_segment_that_has_no_looks_is_refused(self):
        r = self.run_prep("pick", "--segment", "retail")
        self.assertEqual(r.returncode, 1)
        self.assertIn("the templates with looks", r.stderr)

    def test_the_hold_the_pipeline_and_the_suppressed_are_left_out(self):
        (self.t / "leads").mkdir(exist_ok=True)
        (self.t / "leads" / "remote.jsonl").write_text(json.dumps(
            {"ts": "2026-09-27T20:00:00", "for": "2026-09-27", "place_ids": [JENNA], "names": ["Photography by Jenna"],
             "mode": "prep"}) + "\n")
        (self.t / "outreach").mkdir(exist_ok=True)
        (self.t / "outreach" / "suppress.jsonl").write_text(json.dumps({"value": ROSIE}) + "\n")
        j = json.loads(self.run_prep("pick", "--n", "5", "--json").stdout)
        ids = [p["place_id"] for p in j["picks"]]
        self.assertNotIn(JENNA, ids)
        self.assertNotIn(ROSIE, ids)
        self.assertIn(POOL, ids)
        self.assertIn("held (messaged or kitted in the last 56 days)", j["skipped"])
        self.assertIn("suppressed", j["skipped"])

    def test_a_business_in_a_run_that_is_still_going_is_left_out(self):
        rd = self.t / "prep" / "2026-09-29-x"
        rd.mkdir(parents=True)
        (rd / "run.json").write_text(json.dumps({"kind": "prep", "state": "running", "created": "2026-09-29",
                                                 "businesses": {"x": {"place_id": POOL, "stage": "build"}}}))
        j = json.loads(self.run_prep("pick", "--n", "5", "--json").stdout)
        self.assertNotIn(POOL, [p["place_id"] for p in j["picks"]])
        self.assertIn("in another prep run", j["skipped"])


# ---- the whole night, the rehearsal ---------------------------------------------------------------

class RehearsalTest(Base):
    def test_three_businesses_reach_ready_and_the_outline_is_written(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        r, run_dir = self.night(POOL, JENNA, ROSIE, n=3)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rj = self.rj(run_dir)
        self.assertEqual(rj["state"], "rehearsed")
        self.assertEqual(sorted(self.stages(run_dir).values()), ["ready", "ready", "ready"])
        for slug in SLUGS.values():
            wd = run_dir / slug
            for f in ("facts.json", "content.json", "content.draft.json", "message.json", "check.json",
                      "review.json", "site/index.html", "site/claim/index.html", "shots/phone.png",
                      "shots/desktop.png"):
                self.assertTrue((wd / f).exists(), f"{slug}/{f}")
            self.assertTrue(json.loads((wd / "check.json").read_text())["ok"],
                            json.loads((wd / "check.json").read_text())["gates"])
        # the batch pass ran once over the three and set the outline's order
        batch = json.loads((run_dir / "batch.json").read_text())
        self.assertTrue(batch["ran"])
        self.assertEqual(sorted(batch["order"]), sorted(SLUGS.values()))
        self.assertEqual(rj["outline_order"], batch["order"])
        self.assertTrue(batch["looks_ok"])
        # the looks are spread: no two of the two portfolio sites share one
        looks = {s: b["look"] for s, b in rj["businesses"].items()}
        self.assertEqual(len({looks[SLUGS[JENNA]], looks[SLUGS[ROSIE]]}), 2, looks)
        # the outline: two messages a business, the header first, the dropped last
        notes = json.loads((run_dir / "outline.notify.json").read_text())
        self.assertTrue(notes[0].startswith("Prep 2026-09-29-a · 3 ready · 3 researched, 0 dropped"))
        self.assertEqual(len(notes), 1 + 2 * 3)          # the header, then two notes a business
        self.assertIn("Dropped: none.", (run_dir / "outline.md").read_text())
        for i, slug in enumerate(batch["order"]):
            entry, message = notes[1 + 2 * i], notes[2 + 2 * i]
            self.assertTrue(entry.startswith(f"{i + 1}. "), entry)
            self.assertIn("Sign-up: https://patchlamp.com/start?business=", entry)
            self.assertIn("Site: https://", entry)
            self.assertIn("To finish it they'd send:", entry)
            self.assertTrue(message.startswith("Hi, I'm Taylor."), message)
            self.assertIn(" up on Google and ", message)                   # named in the sentence, not the greeting
            self.assertNotIn("{", message)
        # each message is its own note, not a mail merge
        msgs = [notes[2 + 2 * i] for i in range(3)]
        self.assertEqual(len(set(msgs)), 3)
        md = (run_dir / "outline.md").read_text()
        self.assertIn("Reply `sent 1 3 4`", md)
        self.assertEqual(self.run_prep("last").stdout.rstrip(), md.rstrip())

    def test_a_rehearsal_publishes_nothing_holds_nobody_and_notifies_nobody(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        _, run_dir = self.night(POOL, JENNA, n=2)
        self.assertFalse([c for c in self.rows("site.jsonl") if c["argv"][:1] == ["previews"]])
        self.assertFalse((self.t / "leads" / "remote.jsonl").exists())
        self.assertEqual(self.notices(), [])
        self.assertEqual(self.rj(run_dir)["state"], "rehearsed")
        # the pages are on disk all the same, so they can be read: noindex, the bar, the footer
        page = (self.t / "previews" / "site" / "mikes-pool-care-american-fork" / "index.html").read_text()
        self.assertIn('<meta name="robots" content="noindex', page)
        self.assertIn("A preview Patchlamp made for Mike's Pool Care.", page)
        self.assertIn("noindex", (self.t / "previews" / "site" / "_headers").read_text())
        self.assertIn("Disallow: /", (self.t / "previews" / "site" / "robots.txt").read_text())

    def test_every_session_is_kept_by_stage_with_its_model_and_none_of_it_on_fable(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        _, run_dir = self.night(POOL, JENNA, n=2)
        usage = self.rj(run_dir)["usage"]
        self.assertEqual(sorted(k for k, v in usage.items() if v.get("sessions")),
                         ["batch", "build", "judge", "research"])
        self.assertEqual(usage["research"]["models"], ["claude-sonnet-5-5"])
        self.assertEqual(usage["build"]["models"], ["claude-sonnet-5-5"])
        self.assertEqual(usage["judge"]["models"], ["claude-opus-5-5"])
        self.assertEqual(usage["batch"]["models"], ["claude-opus-5-5"])
        for stage, u in usage.items():
            self.assertFalse([m for m in u.get("models") or [] if "fable" in m], stage)
            if u.get("sessions"):
                self.assertGreater(u["plan_usd_list"], 0, stage)
        self.assertTrue(all(not s["api_key_seen"] for s in self.sessions()))
        # the judge sees the screenshots code took, the same four for every site
        self.assertTrue(any(c["argv"][:1] == ["check"] for c in self.rows("shot.jsonl")))
        outs = [c["argv"][c["argv"].index("--out") + 1] for c in self.rows("shot.jsonl") if "--out" in c["argv"]]
        self.assertEqual(sorted({Path(o).name for o in outs}),
                         ["desktop-full.png", "desktop.png", "phone-full.png", "phone.png"])

    def test_a_build_session_can_neither_publish_nor_message_anyone(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        self.night(POOL, n=1)
        builds = self.sessions("build")
        self.assertTrue(builds)
        for s in builds:
            self.assertTrue(s["publish_refused"], s["hooks"])
            self.assertTrue(s["notify_refused"], s["hooks"])
            self.assertEqual(s["render_exit"], 0)
            self.assertEqual(s["check_exit"], 0)
        hooks = [json.loads(x) for x in
                 (self.run_dir() / SLUGS[POOL] / "log" / "build.hook.jsonl").read_text().splitlines()]
        refused = [h for h in hooks if not h["allow"]]
        self.assertEqual(sorted(h["target"] for h in refused),
                         ["notify \"the site is up\"", "site previews site --yes"])
        self.assertFalse([c for c in self.rows("site.jsonl") if c["argv"][:1] == ["previews"]])
        self.assertEqual(self.notices(), [])


# ---- the real night: publish, hold, notify, the ledger --------------------------------------------

class FinishTest(Base):
    def test_the_publish_the_hold_the_ledger_and_the_outline_by_notify(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        self.approve_and_make_the_project()
        r, run_dir = self.night(POOL, JENNA, ROSIE, n=3, publish=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        rj = self.rj(run_dir)
        self.assertEqual(rj["state"], "done")
        self.assertEqual(len(rj["delivered"]), 3)
        # the publish is code's, through `site previews`, and never with --yes
        pub = [c for c in self.rows("site.jsonl") if c["argv"][:1] == ["previews"]]
        self.assertEqual(len(pub), 1)
        self.assertEqual(pub[0]["admin"], "1")
        self.assertNotIn("--yes", pub[0]["argv"])
        self.assertEqual(rj["host"], "patchlamp-previews.pages.dev")
        # the 56-day hold, for the delivered only, in the shape `leads sent` reads
        held = self.rows("leads/remote.jsonl")
        self.assertEqual(len(held), 1)
        self.assertEqual(held[0]["mode"], "prep")
        self.assertEqual(held[0]["run"], run_dir.name)
        self.assertEqual(len(held[0]["place_ids"]), 3)
        self.assertEqual(held[0]["place_ids"], [rj["businesses"][s]["place_id"] for s in rj["delivered"]])
        # the outline, by notify: a header and two messages a business
        notices = self.notices()
        self.assertEqual(len(notices), 1 + 2 * 3)
        self.assertTrue(notices[0].startswith("Prep "))
        self.assertEqual(rj["notified"], len(notices))
        # the ledger: the usage by stage, notional, and the Places spend (none here)
        row = [x for x in self.rows("ledger.jsonl") if x["kind"] == "prep"]
        self.assertEqual(len(row), 1)
        self.assertEqual((row[0]["delivered"], row[0]["researched"], row[0]["dropped"]), (3, 3, 0))
        self.assertEqual(row[0]["cost_usd"], 0)
        self.assertGreater(row[0]["plan_usd_list"], 0)
        self.assertEqual(row[0]["billed_to"], "plan:claude.ai")
        self.assertFalse(row[0]["rehearsal"])
        self.assertEqual(sorted(row[0]["models"]), ["claude-opus-5-5", "claude-sonnet-5-5"])
        self.assertEqual(sorted(k for k in row[0]["usage"]), ["batch", "build", "check", "judge", "research"])

    def test_sent_1_2_3_logs_three_and_a_second_run_picks_others(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        self.approve_and_make_the_project()
        self.night(POOL, JENNA, ROSIE, n=3, publish=True)
        r = self.run_leads("sent", "1", "2", "3", "--channel", "facebook")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pipeline = self.rows("pipeline.jsonl")
        self.assertEqual(len(pipeline), 3)
        self.assertTrue(all(e["outcome"] == "messaged" for e in pipeline))
        # the next night picks other businesses: these three are held and in the pipeline
        j = json.loads(self.run_prep("pick", "--n", "3", "--json").stdout)
        self.assertFalse(set(p["place_id"] for p in j["picks"]) & {POOL, JENNA, ROSIE}, j["picks"])
        self.assertEqual(j["skipped"]["held (messaged or kitted in the last 56 days)"], 3)

    def test_a_failed_publish_holds_the_messages_back_and_publish_retries(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        self.approve_and_make_the_project()
        r, run_dir = self.night(POOL, n=1, publish=True, env={"FAKE_SITE_FAIL": "1"})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.rj(run_dir)["state"], "publish_failed")
        self.assertIn("HELD: the publish failed, nothing sent", (run_dir / "outline.md").read_text())
        self.assertFalse((self.t / "leads" / "remote.jsonl").exists())
        self.assertEqual(len(self.notices()), 1)                    # only "the publish failed"
        self.assertIn("the publish failed", self.notices()[0])
        # `prep resume` sends them nowhere: only `prep publish` retries
        self.assertIn("the publish failed", self.run_prep("resume").stderr)
        r = self.run_prep("publish")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.rj(run_dir)["state"], "done")
        self.assertEqual(len(self.rows("leads/remote.jsonl")), 1)
        self.assertTrue(len(self.notices()) >= 3)

    def test_a_run_that_would_publish_refuses_until_taylor_has_given_his_two(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        r = self.run_prep("run", "--n", "1", "--places", POOL, "--foreground")
        self.assertEqual(r.returncode, 1)
        self.assertIn("the message frame isn't approved", r.stderr)
        self.assertIn("the previews project isn't there yet", r.stderr)
        self.assertFalse((self.t / "prep").exists() and any((self.t / "prep").iterdir()))
        self.assertFalse(self.sessions())

    def test_editing_the_frame_un_approves_it(self):
        self.approve_and_make_the_project()
        self.assertEqual(self.run_prep("doctor").returncode, 1)     # the fixture env has no Places key
        self.assertIn("ok  message frame: approved", self.run_prep("doctor").stdout)
        frame = self.t / "frame.md"
        frame.write_text((TOOLS / "templates" / "prep" / "message.md").read_text()
                         .replace("Nothing to sign", "No obligation"))
        out = self.run_prep("doctor", env={"PREP_FRAME": str(frame)}).stdout
        self.assertIn("BAD message frame: not approved", out)


# ---- the fix rounds, the drop, the reserve --------------------------------------------------------

class FixAndDropTest(Base):
    def test_a_gate_that_fails_comes_back_as_a_fix_round_and_then_passes(self):
        self.write_plan({"build": {SLUGS[POOL]: ["bad", "good"]}, "judge": "pass", "batch": "good"})
        _, run_dir = self.night(POOL, n=1)
        b = self.rj(run_dir)["businesses"][SLUGS[POOL]]
        self.assertEqual(b["stage"], "ready")
        self.assertEqual(b["rounds"], 1)
        self.assertEqual(b["fix_from"], "prep check")
        self.assertTrue(any("gate 4" in f and "best" in f for f in b["fixes"]), b["fixes"])
        # the fix went to the same session, resumed, with the failing lines in the prompt
        builds = self.sessions("build")
        self.assertEqual(len(builds), 2)
        self.assertIsNone(builds[0]["resume"])
        self.assertEqual(builds[1]["resume"], b["build_session"])
        self.assertIn("Round 1 of fixes", builds[1]["prompt"])
        self.assertIn("gate 4", builds[1]["prompt"])
        self.assertTrue(json.loads((run_dir / SLUGS[POOL] / "check.json").read_text())["ok"])

    def test_the_judge_asks_for_a_fix_the_builder_gets_the_list_and_the_second_look_passes(self):
        self.write_plan({"build": "good", "judge": {SLUGS[POOL]: ["fix", "pass"]}, "batch": "good"})
        _, run_dir = self.night(POOL, n=1)
        b = self.rj(run_dir)["businesses"][SLUGS[POOL]]
        self.assertEqual((b["stage"], b["rounds"]), ("ready", 1))
        self.assertEqual(len(self.sessions("judge")), 2)
        fix = self.sessions("build")[1]
        self.assertIn("The judge asks", fix["prompt"])
        self.assertIn("Cut the about section", fix["prompt"])
        self.assertEqual(b["glad"], "Yes — it reads as their own site.")
        self.assertTrue((run_dir / SLUGS[POOL] / "log" / "review-1.json").exists())
        self.assertTrue((run_dir / SLUGS[POOL] / "log" / "review-2.json").exists())

    def test_the_judges_drop_is_final_and_says_why(self):
        self.write_plan({"build": "good", "judge": "drop", "batch": "good"})
        _, run_dir = self.night(POOL, n=1)
        b = self.rj(run_dir)["businesses"][SLUGS[POOL]]
        self.assertEqual(b["stage"], "dropped")
        self.assertIn("the judge:", b["why"])
        self.assertIn("too thin", b["why"])
        self.assertEqual(len(self.sessions("build")), 1)              # no fix round after a drop
        self.assertIn("Nothing ready tonight", (run_dir / "outline.md").read_text())

    def test_a_site_that_never_lints_is_dropped_after_two_rounds_and_the_reserve_takes_its_place(self):
        self.write_plan({"build": {SLUGS[JENNA]: "thin", "default": "good"}, "judge": "pass", "batch": "good"})
        _, run_dir = self.night(POOL, JENNA, ROSIE, n=2)
        stages = self.stages(run_dir)
        self.assertEqual(stages[SLUGS[JENNA]], "dropped")
        self.assertEqual(stages[SLUGS[POOL]], "ready")
        self.assertEqual(stages[SLUGS[ROSIE]], "ready")             # the reserve, promoted
        rj = self.rj(run_dir)
        self.assertEqual(rj["businesses"][SLUGS[ROSIE]]["role"], "active")
        self.assertIn("the gates still fail after 2 fix rounds", rj["businesses"][SLUGS[JENNA]]["why"])
        self.assertEqual(rj["businesses"][SLUGS[JENNA]]["rounds"], 2)
        notes = json.loads((run_dir / "outline.notify.json").read_text())
        self.assertIn("Dropped: Photography by Jenna", notes[-1])
        self.assertEqual(len(notes), 1 + 2 * 2 + 1)

    def test_thin_facts_are_dropped_at_the_gate_before_a_site_is_built(self):
        _, run_dir = self.night(POOL, n=1, env={"FAKE_CLAUDE_MODE": "skip", "FAKE_CLAUDE_FACTS_DIR": ""})
        b = self.rj(run_dir)["businesses"][SLUGS[POOL]]
        self.assertEqual(b["stage"], "dropped")
        self.assertIn("research said skip", b["why"])
        self.assertFalse(self.sessions("build"))

    def test_the_batch_pass_may_hold_one_back(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "drop-last"})
        _, run_dir = self.night(POOL, JENNA, n=2)
        dropped = [s for s, st in self.stages(run_dir).items() if st == "dropped"]
        self.assertEqual(len(dropped), 1)
        self.assertIn("the batch pass:", self.rj(run_dir)["businesses"][dropped[0]]["why"])
        self.assertEqual(len(json.loads((run_dir / "batch.json").read_text())["drop"]), 1)


# ---- stopping, resuming, the marker --------------------------------------------------------------

class ResumeTest(Base):
    def wait_for(self, want, seconds=40):
        end = time.time() + seconds
        while time.time() < end:
            try:
                if want(self.rj()):
                    return self.rj()
            except (OSError, ValueError, AssertionError):
                pass
            time.sleep(0.2)
        self.fail(f"the run never got there (state {self.rj().get('state')})")

    def test_a_killed_run_finishes_under_resume(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        r = self.run_prep("run", "--n", "3", "--places", POOL, JENNA, ROSIE, "--no-publish",
                          env={"FAKE_CLAUDE_SLEEP": "1.5"})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Prep 2026-09-29-a: 3 picked", r.stdout)
        run_dir = self.run_dir()
        marker = self.t / "requests" / f"prep-{run_dir.name}.running"
        self.assertTrue(marker.exists())
        rj = self.wait_for(lambda j: j.get("state") == "running" and j.get("pid"))
        os.kill(rj["pid"], signal.SIGKILL)                          # the laptop sleeps, the night stops
        time.sleep(1)
        self.assertTrue(any(st != "ready" for st in self.stages().values()), self.stages())
        # the marker's pid is dead, so `doctor` clears it and `resume` is not blocked by it
        out = self.run_prep("doctor").stdout
        self.assertIn("marker: none in", out)
        self.assertFalse(marker.exists())
        r = self.run_prep("resume", "--foreground")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("resumed", r.stdout)
        self.assertEqual(self.rj()["state"], "rehearsed")
        self.assertEqual(sorted(self.stages().values()), ["ready", "ready", "ready"])
        self.assertEqual(self.rj()["resumed"], 1)
        self.assertEqual(len(json.loads((run_dir / "outline.json").read_text())), 3)

    def test_stop_ends_it_and_resume_carries_on(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        self.run_prep("run", "--n", "3", "--places", POOL, JENNA, ROSIE, "--no-publish",
                      env={"FAKE_CLAUDE_SLEEP": "1.5"})
        self.wait_for(lambda j: j.get("state") == "running" and j.get("pid"))
        r = self.run_prep("stop")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("stopped", r.stdout)
        self.assertEqual(self.rj()["state"], "stopped")
        self.assertFalse((self.t / "requests" / f"prep-{self.run_dir().name}.running").exists())
        r = self.run_prep("resume", "--foreground")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.rj()["state"], "rehearsed")
        self.assertEqual(sorted(self.stages().values()), ["ready", "ready", "ready"])

    def test_status_says_where_every_business_is(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        _, run_dir = self.night(POOL, JENNA, n=2)
        out = self.run_prep("status").stdout
        self.assertIn(f"Prep {run_dir.name} · rehearsed · n 2 · no conductor running · rehearsal", out)
        self.assertIn(f"1. {SLUGS[POOL]}: ready [service/", out)
        self.assertIn("usage by stage", out)
        self.assertIn("research   2 sessions", out)
        self.assertIn("claude-opus-5-5", out)
        self.assertIn("outline:", out)

    def test_a_second_run_will_not_start_while_one_is_going(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        self.approve_and_make_the_project()
        self.run_prep("run", "--n", "1", "--places", POOL, env={"FAKE_CLAUDE_SLEEP": "2"})
        self.wait_for(lambda j: j.get("state") == "running" and j.get("pid"))
        r = self.run_prep("run", "--n", "1", "--places", JENNA)
        self.assertEqual(r.returncode, 1)
        self.assertIn("is still going", r.stderr)
        self.run_prep("stop")


# ---- the gates and the message, in the code ------------------------------------------------------

class GateTest(Base):
    """The gates over a directory a run really built, each broken one at a time."""

    def build_one(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        _, run_dir = self.night(POOL, n=1)
        return run_dir / SLUGS[POOL]

    def check(self, wd, env=None):
        r = self.run_prep("check", str(wd), "--json", env=env)
        return json.loads(r.stdout), r.returncode

    def edit(self, wd, fn):
        c = json.loads((wd / "content.json").read_text())
        fn(c)
        (wd / "content.json").write_text(json.dumps(c))

    def failures(self, res, gate):
        return " | ".join(res["gates"][gate]["problems"])

    def test_the_gates_pass_on_what_the_run_built(self):
        wd = self.build_one()
        res, code = self.check(wd)
        self.assertTrue(res["ok"], res["gates"])
        self.assertEqual(code, 0)
        self.assertEqual(res["message"]["channel"]["kind"], "facebook")

    def test_a_price_a_review_run_a_name_and_a_street_address_all_fail(self):
        wd = self.build_one()
        for text, want in (("Openings from $180.", "a price"),
                           ("Weekly cleaning all season and the pump too.", "a fact's source words"),
                           ("The water has never been this clear here.", "shares a run of 6 words"),
                           ("Ask for Jorge when you call.", "a person's name"),
                           ("Find us at 101 N Main St.", "a street address")):
            self.edit(wd, lambda c, t=text: c["sections"][0].update(sub={"text": t, "facts": ["f2"]}))
            res, code = self.check(wd)
            self.assertEqual(code, 1, text)
            self.assertIn(want, self.failures(res, "3"), text)

    def test_a_guarded_word_needs_a_high_credential_or_since_fact(self):
        wd = self.build_one()
        self.edit(wd, lambda c: c["sections"][0].update(sub={"text": "Licensed and insured.", "facts": ["f2"]}))
        res, _ = self.check(wd)
        self.assertIn("needs a high credential or since fact", self.failures(res, "4"))

    def test_a_medium_fact_and_a_fact_that_does_not_exist_both_fail(self):
        wd = self.build_one()
        self.edit(wd, lambda c: c["sections"][0].update(sub={"text": "Weekly visits.", "facts": ["f4"]}))
        res, _ = self.check(wd)
        self.assertIn("is medium — the site uses high facts only", self.failures(res, "5"))
        self.edit(wd, lambda c: c["sections"][0].update(sub={"text": "Weekly visits.", "facts": ["f99"]}))
        res, _ = self.check(wd)
        self.assertIn("doesn't exist", self.failures(res, "5"))

    def test_too_many_generic_sentences_fail(self):
        wd = self.build_one()

        def more(c):
            extra = ["We answer the phone every day.", "Our work speaks for itself here.",
                     "Quality service you can trust always.", "Your satisfaction is our priority here."]
            c["sections"][0]["note"] = {"text": extra[0], "facts": []}
            c["sections"][1]["items"].append({"text": extra[1], "facts": []})
            c["sections"][2]["intro"] = {"text": extra[2], "facts": []}
            c["sections"][-1]["heading"] = {"text": extra[3], "facts": []}
            c["generic"] = sorted(set(c.get("generic") or []) | set(extra))
        self.edit(wd, more)
        res, _ = self.check(wd)
        self.assertIn("generic sentences (at most 3)", self.failures(res, "5"))

    def test_a_service_site_keeps_its_quote_and_booking_sections(self):
        wd = self.build_one()
        self.edit(wd, lambda c: c.update(sections=[s for s in c["sections"] if s["type"] != "booking"]))
        res, _ = self.check(wd)
        self.assertIn("a service site keeps its quote and booking sections", self.failures(res, "5"))

    def test_the_look_and_the_slug_are_the_runs_to_set(self):
        wd = self.build_one()
        self.edit(wd, lambda c: c.update(look="sturdy" if c["look"] != "sturdy" else "fresh"))
        res, _ = self.check(wd)
        self.assertIn("it balances the looks over the night", self.failures(res, "5"))

    def test_a_console_error_fails_gate_one(self):
        wd = self.build_one()
        res, _ = self.check(wd, env={"FAKE_SHOT_FAIL": "index.html"})
        self.assertIn("a console error", self.failures(res, "1"))

    def test_a_hero_photo_another_site_in_the_run_shows_fails(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        _, run_dir = self.night(POOL, JENNA, n=2)
        a, b = run_dir / SLUGS[POOL], run_dir / SLUGS[JENNA]
        ca, cb = (json.loads((x / "content.json").read_text()) for x in (a, b))
        self.assertNotEqual(ca["images"]["hero"]["id"], cb["images"]["hero"]["id"])
        cb["images"]["hero"]["id"] = ca["images"]["hero"]["id"]
        (b / "content.json").write_text(json.dumps(cb))
        res, _ = self.check(b)
        self.assertIn("is another site's in this run", self.failures(res, "6"))


class MessageTest(Base):
    def test_the_message_is_the_frame_filled_and_its_lint_is_code(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        _, run_dir = self.night(POOL, n=1)
        wd = run_dir / SLUGS[POOL]
        r = self.run_prep("message", str(wd))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("send by: Facebook message to facebook.com/mikespoolcare → https://m.me/mikespoolcare", r.stdout)
        self.assertIn("why: their Google listing's website link is their Facebook page", r.stdout)
        self.assertIn("lint OK", r.stdout)
        m = json.loads(self.run_prep("message", str(wd), "--json").stdout)
        self.assertTrue(m["text"].startswith("Hi, I'm Taylor."), m["text"])
        self.assertIn("I looked Mike's Pool Care up on Google and ", m["text"])
        self.assertTrue(m["text"].endswith("Worth a look?"), m["text"])   # message one asks for a reply
        self.assertLess(m["chars"], 700)
        self.assertEqual(re.findall(r"https?://\S+", m["text"]), [m["preview_url"]])
        self.assertNotIn("!", m["text"])

    def test_a_specific_line_over_the_cap_a_guarded_word_and_a_medium_fact_all_fail_the_lint(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        _, run_dir = self.night(POOL, n=1)
        wd = run_dir / SLUGS[POOL]
        for spec, want in (({"text": "x" * 141, "facts": ["f2"]}, "at most 140"),
                           ({"text": "The best pool work in town.", "facts": ["f2"]}, "a guarded word"),
                           ({"text": "Weekly visits.", "facts": ["f4"]}, "is medium"),
                           ({"text": "Nice work.", "facts": []}, "names no facts")):
            (wd / "message.json").write_text(json.dumps({"specific": spec}))
            r = self.run_prep("message", str(wd), "--json")
            self.assertEqual(r.returncode, 1, spec)
            self.assertIn(want, " | ".join(json.loads(r.stdout)["problems"]), spec)

    def test_a_phone_only_business_gets_the_call_opener(self):
        # Dave's Handyman has no Instagram, Facebook or email: --allow-calls lets him in by phone
        listing = json.loads((FIX / "details" / "FX_S01.json").read_text().replace("FX_S01", "FX_S05"))
        listing["displayName"] = {"text": "Dave's Handyman Services"}
        listing["websiteUri"] = "https://daveshandyman.wixsite.com/home"
        (self.t / "leads" / "details" / "FX_S05.json").write_text(json.dumps(listing))
        src = self.t / "facts-s05.json"
        src.write_text((FIX / "facts-good.json").read_text().replace("FX_S01", "FX_S05"))
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        r, run_dir = self.night("FX_S05", n=1, extra=["--allow-calls"],
                             env={"FAKE_CLAUDE_FACTS": str(src), "FAKE_CLAUDE_FACTS_DIR": ""})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        slug = next(iter(self.rj(run_dir)["businesses"]))
        m = json.loads(self.run_prep("message", str(run_dir / slug), "--json").stdout)
        self.assertEqual(m["channel"]["kind"], "phone")
        self.assertEqual(m["section"], "call")
        self.assertTrue(m["text"].startswith('Say: "Hi, is this Dave'), m["text"])
        self.assertFalse(re.findall(r"https?://\S+", m["text"]))
        self.assertFalse(m["problems"], m["problems"])


class ApproveTest(Base):
    def test_approve_shows_the_frame_filled_and_records_its_hash(self):
        r = self.run_prep("approve", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("───── message ─────", r.stdout)
        self.assertIn("I looked Pinnacle Painting up on Google and ", r.stdout)
        self.assertIn("───── call ─────", r.stdout)
        self.assertIn("[dry-run] not recorded.", r.stdout)
        self.assertFalse((self.t / "prep" / "approved.json").exists())
        r = self.run_prep("approve")
        self.assertEqual(r.returncode, 0, r.stderr)
        row = json.loads((self.t / "prep" / "approved.json").read_text())
        self.assertEqual(len(row["message.md"]), 64)

    def test_a_frame_with_a_price_or_an_exclamation_mark_is_not_approved(self):
        frame = self.t / "frame.md"
        frame.write_text("## message\n\nHi {business}! {fault} {specific} From $49: {preview_url}\n\n## call\n\n"
                         "Say: \"Hi, is this {business}? {fault} {specific}\"\n")
        r = self.run_prep("approve", env={"PREP_FRAME": str(frame)})
        self.assertEqual(r.returncode, 1)
        for want in ("an exclamation mark", "a price"):
            self.assertIn(want, r.stderr)
        self.assertFalse((self.t / "prep" / "approved.json").exists())


class ModelTest(Base):
    def test_a_run_without_a_browser_is_refused_before_it_starts(self):
        # gate 1 is `shot check`: without a browser every site would fail it twice and be dropped
        r = self.run_prep("run", "--n", "1", "--places", POOL, "--no-publish", "--foreground",
                          env={"FAKE_SHOT_NO_BROWSER": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("gate 1 is `shot check`, so every site would be dropped", r.stderr)
        self.assertFalse(self.sessions())
        self.assertIn("BAD shot:", self.run_prep("doctor", env={"FAKE_SHOT_NO_BROWSER": "1"}).stdout)
        self.assertIn("ok  shot: a browser", self.run_prep("doctor").stdout)

    def test_fable_is_refused_before_a_run_starts(self):
        r = self.run_prep("run", "--n", "1", "--places", POOL, "--no-publish", "--foreground",
                          env={"PREP_MODEL_JUDGE": "claude-fable-5"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("never runs on Fable", r.stderr)
        self.assertFalse(self.sessions())

    def test_a_session_that_answers_on_fable_drops_that_business(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        _, run_dir = self.night(POOL, n=1, env={"FAKE_CLAUDE_MODE": "fable"})
        b = self.rj(run_dir)["businesses"][SLUGS[POOL]]
        self.assertEqual(b["stage"], "dropped")
        self.assertIn("Fable is never a prep model", b["why"])

    def test_dry_run_picks_and_starts_nothing(self):
        r = self.run_prep("run", "--n", "2", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("prep run --dry-run: 2 picked, 1 in reserve — nothing started", r.stdout)
        self.assertFalse((self.t / "prep").exists() and any((self.t / "prep").iterdir()))
        self.assertFalse(self.sessions())
        self.assertFalse((self.t / "requests").exists() and any((self.t / "requests").iterdir()))


# ---- B92: one business on Taylor's word -----------------------------------------------------------

class OneTest(Base):
    """`prep one PLACE_ID` (plan 37 § 4): the run's machinery for one named business, never a fork of it."""

    def one(self, *args, env=None):
        return self.run_prep("one", *args, env=env)

    def test_one_delivers_one_judged_site_with_the_gates_green_and_the_outline_by_notify(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        self.approve_and_make_the_project()
        r = self.one(POOL, "--foreground", "--why", "outreach build: Mike's Pool Care replied")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Prep 2026-09-29-a: building Mike's Pool Care", r.stdout)
        run_dir = self.run_dir()
        rj = self.rj(run_dir)
        self.assertEqual(rj["state"], "done")
        self.assertEqual(rj["n"], 1)
        self.assertTrue(rj["opts"]["one"])
        self.assertEqual(rj["opts"]["why"], "outreach build: Mike's Pool Care replied")
        self.assertEqual(rj["delivered"], [SLUGS[POOL]])
        wd = run_dir / SLUGS[POOL]
        self.assertTrue(json.loads((wd / "check.json").read_text())["ok"])          # the gates, green
        self.assertTrue(json.loads((wd / "review.json").read_text()))                # judged
        usage = rj["usage"]
        self.assertEqual(usage["research"]["models"], ["claude-sonnet-5-5"])
        self.assertEqual(usage["build"]["models"], ["claude-sonnet-5-5"])
        self.assertEqual(usage["judge"]["models"], ["claude-opus-5-5"])
        self.assertFalse((usage.get("batch") or {}).get("sessions"))   # one site: no batch pass to compare
        pub = [c for c in self.rows("site.jsonl") if c["argv"][:1] == ["previews"]]
        self.assertEqual(len(pub), 1)
        self.assertNotIn("--yes", pub[0]["argv"])
        notices = self.notices()
        self.assertEqual(len(notices), 3)                 # the header, the entry, the message
        self.assertTrue(notices[0].startswith("Prep 2026-09-29-a (one business, on your word) · 1 ready"),
                        notices[0])
        self.assertIn("Site: https://", notices[1])
        self.assertEqual(self.rows("leads/remote.jsonl")[0]["place_ids"], [POOL])

    def test_a_second_build_says_what_exists_instead_of_building_twice(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        self.approve_and_make_the_project()
        self.one(POOL, "--foreground")
        sessions = len(self.sessions())
        r = self.one(POOL, "--foreground")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"is already built: prep 2026-09-29-a delivered it \d{4}-\d\d-\d\d, https://")
        self.assertIn("`prep last 2026-09-29-a`", r.stdout)
        self.assertEqual(len(self.sessions()), sessions)
        self.assertEqual(len([d for d in (self.t / "prep").iterdir() if (d / "run.json").exists()]), 1)

    def test_a_business_a_run_still_holds_is_not_started_again(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        self.run_prep("run", "--n", "1", "--places", POOL, "--no-publish", env={"FAKE_CLAUDE_SLEEP": "2"})
        end = time.time() + 40
        while time.time() < end and self.rj().get("state") != "running":
            time.sleep(0.2)
        r = self.one(POOL, "--no-publish")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("is already being built in prep 2026-09-29-a", r.stdout)
        self.run_prep("stop")

    def test_it_refuses_before_spending_anything_until_taylor_has_given_his_two(self):
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        r = self.one(POOL, "--foreground")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not starting Mike's Pool Care", r.stderr)
        self.assertIn("the message frame isn't approved", r.stderr)
        self.assertIn("the previews project isn't there yet", r.stderr)
        self.assertFalse((self.t / "prep").exists() and any((self.t / "prep").iterdir()))
        self.assertFalse(self.sessions())

    def test_a_place_outside_the_census_is_refused_plainly(self):
        r = self.one("FX_NOT_THERE")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not in the services census", r.stderr)
        self.assertFalse(self.sessions())

    def test_dry_run_says_what_it_would_do_and_spend_and_starts_nothing(self):
        r = self.one(POOL, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("prep one --dry-run: Mike's Pool Care", out)
        self.assertIn("one claude-sonnet-5-5 session", out)
        self.assertIn("a fresh claude-opus-5-5 session a round", out)
        self.assertIn("the listing is on disk: no Places read", out)
        self.assertIn("Taylor's subscription", out)
        self.assertIn("would refuse:", out)                      # nothing approved in this world yet
        self.assertNotIn("fable", out.lower())
        self.assertFalse((self.t / "prep").exists() and any((self.t / "prep").iterdir()))
        self.assertFalse(self.sessions())
        self.assertFalse([c for c in self.rows("site.jsonl")])   # a dry run asks Cloudflare nothing

    def test_a_dropped_site_comes_back_as_a_plain_why_by_notify(self):
        self.write_plan({"build": "good", "judge": "drop", "batch": "good"})
        self.approve_and_make_the_project()
        r = self.one(POOL, "--foreground")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        notices = self.notices()
        self.assertIn("0 ready", notices[0])
        self.assertTrue(notices[-1].startswith("Dropped: "), notices)
        # a dropped attempt holds nothing: Taylor may ask again
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        r = self.one(POOL, "--foreground")
        self.assertEqual(self.rj()["state"], "done", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()


# ---- B107: a handle that belongs to a namesake (plan ~/projects/plans/44-wrong-business-handles.md) ---------
# On 2026-10-02 the outline named @valdezbrothersplumbing for an Orem plumber; it and the Facebook page were a
# New Mexico company's. These pin that research's verdict reaches the outline and the reach table: only a `high`
# route is a DM line, `not_theirs` always wins, `unsure` is said as "look before sending", and a business whose
# only routes were taken away is dropped unless the run allows calls.

VALDEZ = "ChIJ2XdYeSWbTYcRzcl5fw_nC20"
VALDEZ_FIX = FIX / "valdez-2026-10-02"
REACH_STUB = FIX / "reach-stub.py"
REAL_REACH = Path.home() / "projects" / ".worktrees" / "client-leads-b104" / "scripts" / "reach.py"
REACH_DDL = """CREATE TABLE IF NOT EXISTS reach (place_id TEXT PRIMARY KEY, instagram TEXT, facebook TEXT, email TEXT,
    source TEXT, checked TEXT, evidence TEXT, unconfirmed TEXT)"""
NM_WHY = "the Facebook page and valdezbrothersplumbing.com are a New Mexico business"


def real_reach_ok():
    return REAL_REACH.exists() and "def set_verdict" in REAL_REACH.read_text()


def with_reach_py(path):
    """In-process: point leads' place check at `path` and forget the one it imported before."""
    L = P.leads()
    old = os.environ.get("LEADS_REACH_PY")
    os.environ["LEADS_REACH_PY"] = str(path)
    L._REACH_MOD = None

    def undo():
        if old is None:
            os.environ.pop("LEADS_REACH_PY", None)
        else:
            os.environ["LEADS_REACH_PY"] = old
        L._REACH_MOD = None
    return undo


def low_packet(value="bluecanyonlandscaping", confidence="low", place=None, why="nothing ties it to the place"):
    return {"place_id": "FX_S02", "name": "Blue Canyon Landscaping", "city": "Lehi",
            "listing": {"phone": "(801) 555-0102", "website": None}, "census": {},
            "reach": {"instagram": value if confidence == "high" else None, "facebook": None, "email": None,
                      "judged": {"instagram": {"value": value, "confidence": confidence, "place": place,
                                               "why": None if confidence == "high" else why, "by": "reach.py"}}}}


class HandleRouteTest(unittest.TestCase):
    """The precedence table, in process (plan 44 § Change 11)."""

    def setUp(self):
        self.addCleanup(with_reach_py(REACH_STUB))

    def test_the_valdez_packet_replayed_gives_no_instagram_route(self):
        pkt = json.loads((VALDEZ_FIX / "packet.json").read_text())        # the original row: no confidence
        facts = json.loads((VALDEZ_FIX / "facts.json").read_text())
        for f in (facts, None):                                             # with research's verdicts, and without
            ch = P.channel_for(pkt, f)
            self.assertEqual(ch["kind"], "phone", ch)
            self.assertNotIn("valdezbrothersplumbing", ch["label"])
            self.assertNotIn("their Instagram", ch["why"])
        ch = P.channel_for(pkt, facts)
        self.assertIn(f"Facebook refused (research: {NM_WHY})", ch["refused"])
        self.assertTrue(any(t.startswith("facebook not theirs (") for t in ch["taken"]), ch["taken"])
        self.assertTrue(any(t.startswith("instagram unsure (") for t in ch["taken"]), ch["taken"])

    def test_an_unsure_on_a_high_row_is_look_before_sending_never_the_route(self):
        pkt = low_packet(confidence="high", place="names Lehi (the result's title)")
        self.assertEqual(P.channel_for(pkt)["kind"], "instagram")          # no verdict: the reach table's high stands
        ch = P.channel_for(pkt, {"reach": {"instagram": {"verdict": "unsure", "why": "two accounts by this name"}}})
        self.assertEqual(ch["kind"], "phone")
        self.assertEqual(ch["unconfirmed"], [
            "Instagram @bluecanyonlandscaping: unconfirmed, look before sending (research unsure: two accounts by "
            "this name) https://www.instagram.com/bluecanyonlandscaping/"])
        ch = P.channel_for(pkt, {"reach": {"instagram": {"verdict": "not_theirs", "why": "a Boise landscaper"}}})
        self.assertEqual(ch["kind"], "phone")
        self.assertEqual(ch["refused"], ["Instagram refused (research: a Boise landscaper)"])

    def test_theirs_promotes_a_low_row_only_when_the_cited_words_tie_it(self):
        pkt = low_packet()
        tied = {"reach": {"instagram": {"verdict": "theirs", "why": "bio names the towns",
                                        "source": {"words": "Serving Orem and Provo, Utah"}}}}
        rt = P.route_confidence(pkt, tied, "instagram")
        self.assertEqual(rt["confidence"], "high", rt)
        ch = P.channel_for(pkt, tied)
        self.assertEqual(ch["kind"], "instagram")
        self.assertIn("research cited words that tie it to the place", ch["why"])
        untied = {"reach": {"instagram": {"verdict": "theirs", "why": "the name matches",
                                          "source": {"words": "Blue Canyon Landscaping, lawns and yards"}}}}
        self.assertEqual(P.route_confidence(pkt, untied, "instagram")["confidence"], "low")
        self.assertEqual(P.channel_for(pkt, untied)["kind"], "phone")
        bare = {"reach": {"instagram": {"verdict": "theirs", "why": "looks right"}}}
        self.assertEqual(P.route_confidence(pkt, bare, "instagram")["confidence"], "low")
        rej = low_packet(confidence="rejected", why="another state")
        self.assertEqual(P.route_confidence(rej, tied, "instagram")["confidence"], "rejected")

    @unittest.skipUnless(real_reach_ok(), f"no B104 reach.py at {REAL_REACH}")
    def test_theirs_against_the_real_place_check(self):
        self.addCleanup(with_reach_py(REAL_REACH))
        pkt = low_packet()
        for words, want in (("Serving Orem and Provo, Utah", "high"), ("lawns and yards", "low"),
                            ("Lawn care in Boise, ID 83702", "low")):
            facts = {"reach": {"instagram": {"verdict": "theirs", "why": "w", "source": {"words": words}}}}
            self.assertEqual(P.route_confidence(pkt, facts, "instagram")["confidence"], want, words)


class HandleRunTest(Base):
    """A whole night, the verdicts written through `reach.py --verdict` at finish."""

    def add_valdez(self):
        pkt = json.loads((VALDEZ_FIX / "packet.json").read_text())
        rc = pkt["reach"]
        conn = sqlite3.connect(self.db)
        conn.execute("""INSERT INTO place_cache (place_id, name, address, phone, website, has_website, rating, reviews,
                        lat, lng, refreshed_at, locality, postal_code, primary_type, types, business_status,
                        google_maps_uri) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (VALDEZ, "Valdez Brothers Plumbing", pkt["listing"]["address_never_publish"], "(385) 332-8356",
                      None, "no", 4.9, 265, 40.296, -111.716, "2026-09-28T16:14:38", "Orem", "84058", "plumber",
                      json.dumps(["plumber", "service"]), "OPERATIONAL", pkt["census"]["google_maps_uri"]))
        conn.execute("""INSERT INTO businesses (place_id, segment, category, categories, city, first_seen, source,
                        presence_class, presence_url, presence_checked, is_chain, chain_override)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                     (VALDEZ, "services", "plumber", json.dumps(["plumber"]), "Orem, Utah", "2026-09-28",
                      "scan_services", "none", None, "2026-09-28T12:00:00", 0, None))
        conn.execute(REACH_DDL)
        conn.execute("INSERT INTO reach VALUES (?,?,?,?,?,?,?,NULL)",     # the row as it was on 2026-10-02
                     (VALDEZ, rc["instagram"], rc["facebook"], None, rc["source"], rc["checked"],
                      json.dumps(rc["evidence"])))
        conn.commit()
        conn.close()
        shutil.copy(VALDEZ_FIX / "listing.json", self.t / "leads" / "details" / f"{VALDEZ}.json")

    def stub_env(self):
        return {"LEADS_REACH_PY": str(REACH_STUB), "REACH_STUB_LOG": str(self.t / "reach-stub.jsonl"),
                "FAKE_CLAUDE_FACTS": str(VALDEZ_FIX / "facts.json"), "FAKE_CLAUDE_FACTS_DIR": "",
                "PREP_VERIFY": "off"}            # its sources are real hosts: the suite reads none of them

    def test_valdez_replayed_records_both_verdicts_and_is_dropped_with_no_route_left(self):
        self.add_valdez()
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        r, run_dir = self.night(VALDEZ, n=1, env=self.stub_env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        slug, b = next(iter(self.rj(run_dir)["businesses"].items()))
        self.assertEqual(b["stage"], "dropped", b)
        self.assertTrue(b["why"].startswith("no route left: "), b["why"])
        self.assertIn(f"facebook not theirs ({NM_WHY})", b["why"])
        self.assertIn("instagram unsure (Whether the Instagram account is theirs)", b["why"])
        self.assertTrue(b["why"].endswith("; phone only"), b["why"])
        calls = self.rows("reach-stub.jsonl")
        verdicts = {c[2]: c for c in calls if c[:1] == ["--verdict"]}
        self.assertEqual(sorted(verdicts), ["facebook", "instagram"])      # no call for the website: no column
        by = f"prep {run_dir.name}/{slug}"
        self.assertEqual(verdicts["facebook"][:8], ["--verdict", VALDEZ, "facebook", "not_theirs", NM_WHY, "--by", by,
                                                    "--value"])
        # reach.py stores the page URL and compares --value with it, so leads sends the page URL form
        self.assertEqual(verdicts["facebook"][8], "https://www.facebook.com/valdezbrothersplumbingandheating")
        self.assertEqual(verdicts["instagram"][:5], ["--verdict", VALDEZ, "instagram", "unsure",
                                                     "Whether the Instagram account is theirs"])
        md = (run_dir / "outline.md").read_text()
        self.assertIn("Dropped: Valdez Brothers Plumbing — no route left: ", md)
        self.assertIn("Refused handles:", md)
        self.assertIn(f"- Valdez Brothers Plumbing: Facebook facebook.com/valdezbrothersplumbingandheating — not "
                      f"theirs: {NM_WHY} (recorded)", md)
        self.assertIn("- Valdez Brothers Plumbing: Instagram @valdezbrothersplumbing — unsure: Whether the Instagram "
                      "account is theirs (recorded)", md)
        self.assertIn(f"- Valdez Brothers Plumbing: Website valdezbrothersplumbing.com — not theirs: {NM_WHY}", md)
        self.assertNotIn("Instagram DM", md)

    def test_a_refusal_from_reach_py_is_said_and_finish_carries_on(self):
        self.add_valdez()
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        env = dict(self.stub_env(), REACH_STUB_REFUSE="facebook")
        r, run_dir = self.night(VALDEZ, n=1, extra=["--allow-calls"], env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        _, b = next(iter(self.rj(run_dir)["businesses"].items()))
        self.assertEqual(b["stage"], "ready", b)                           # --allow-calls: the call opener
        out = json.loads((run_dir / "outline.json").read_text())
        self.assertEqual(out[0]["channel"]["kind"], "phone")
        md = (run_dir / "outline.md").read_text()
        self.assertIn("(not recorded: --verdict refused: ", md)
        self.assertIn("Not used: ", md)
        self.assertNotIn("Instagram DM", md)

    def blue_canyon(self):
        """FX_S02 with a listing, a `high` Instagram in the reach table, and research's not_theirs about it."""
        listing = json.loads((FIX / "details" / "FX_S01.json").read_text().replace("FX_S01", "FX_S02"))
        listing["displayName"] = {"text": "Blue Canyon Landscaping"}
        listing.pop("websiteUri", None)
        (self.t / "leads" / "details" / "FX_S02.json").write_text(json.dumps(listing))
        conn = sqlite3.connect(self.db)
        conn.execute(REACH_DDL)
        ev = {"query": "\"Blue Canyon Landscaping\" Lehi Utah",
              "instagram": {"url": "https://www.instagram.com/bluecanyonlandscaping/", "value": "bluecanyonlandscaping",
                            "title": "Blue Canyon Landscaping (@bluecanyonlandscaping) · Lehi, Utah",
                            "confidence": "high", "place": "names Lehi (the result's title)", "by": "reach.py"}}
        conn.execute("INSERT INTO reach VALUES (?,?,?,?,?,?,?,NULL)",
                     ("FX_S02", "bluecanyonlandscaping", None, None, "search; instagram=result #2",
                      "2026-10-01T12:00:00", json.dumps(ev)))
        conn.commit()
        conn.close()
        facts = json.loads((FIX / "facts-good.json").read_text().replace("FX_S01", "FX_S02"))
        facts["schema"] = 2
        facts["reach"] = {"instagram": {"verdict": "not_theirs", "why": "the profile's own result says Boise, Idaho"}}
        src = self.t / "facts-s02.json"
        src.write_text(json.dumps(facts))
        return src

    def check_not_theirs(self, env):
        src = self.blue_canyon()
        self.write_plan({"build": "good", "judge": "pass", "batch": "good"})
        r, run_dir = self.night("FX_S02", n=1, extra=["--allow-calls"],
                             env=dict(env, FAKE_CLAUDE_FACTS=str(src), FAKE_CLAUDE_FACTS_DIR=""))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        _, b = next(iter(self.rj(run_dir)["businesses"].items()))
        self.assertEqual(b["stage"], "ready", b)
        out = json.loads((run_dir / "outline.json").read_text())
        self.assertEqual(out[0]["channel"]["kind"], "phone")
        md = (run_dir / "outline.md").read_text()
        self.assertNotIn("Instagram DM", md)
        self.assertIn("Not used: Instagram refused (research: the profile's own result says Boise, Idaho)", md)
        self.assertIn("- Blue Canyon Landscaping: Instagram @bluecanyonlandscaping — not theirs: the profile's own "
                      "result says Boise, Idaho (recorded)", md)
        return run_dir

    def test_not_theirs_on_a_high_row_gets_no_dm_line_and_the_verdict_goes_to_reach_py(self):
        env = {"LEADS_REACH_PY": str(REACH_STUB), "REACH_STUB_LOG": str(self.t / "reach-stub.jsonl")}
        run_dir = self.check_not_theirs(env)
        calls = [c for c in self.rows("reach-stub.jsonl") if c[:1] == ["--verdict"]]
        self.assertEqual(len(calls), 1, calls)
        self.assertEqual(calls[0][:7], ["--verdict", "FX_S02", "instagram", "not_theirs",
                                        "the profile's own result says Boise, Idaho", "--by",
                                        f"prep {run_dir.name}/{next(iter(self.rj(run_dir)['businesses']))}"])

    @unittest.skipUnless(real_reach_ok(), f"no B104 reach.py at {REAL_REACH}")
    def test_not_theirs_nulls_the_row_with_the_reason_through_the_real_reach_py(self):
        self.check_not_theirs({"LEADS_REACH_PY": str(REAL_REACH)})
        conn = sqlite3.connect(self.db)
        ig, ev, unconf = conn.execute("SELECT instagram, evidence, unconfirmed FROM reach WHERE place_id='FX_S02'").fetchone()
        conn.close()
        self.assertIsNone(ig)
        e = json.loads(ev)["instagram"]
        self.assertEqual(e["confidence"], "rejected", e)
        self.assertIn("Boise, Idaho", json.dumps(e))
        self.assertTrue(str(e.get("by") or "").startswith("prep "), e)
        self.assertIn("instagram=", unconf or "")
