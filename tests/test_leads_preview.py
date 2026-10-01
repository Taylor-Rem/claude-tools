"""`leads preview` — a lead's own website, built from the census row (ROADMAP/GROWTH B45).

    python3 -m unittest discover -s tests -q   (from claude-tools/)

No network and no census writes: every business here is one of B44's made-up
fixture rows (FX_ ids, 555 numbers) and the listings come from
tests/fixtures/leads-services/details. The publish goes to a fake `site` on
PATH, so nothing reaches Cloudflare.

What's pinned: the fill is deterministic and costs nothing; the footer sentence
is the one in patchlamp/CLAIMS.md, word for word; every page is noindex twice
over and the project's `_headers` says so; no Google photo, no review text, no
street address and no price ever reach a page; a slug is stable, so a link
already sent keeps working when the preview is rebuilt; the 30 days expire on a
moved clock and `sweep` takes down exactly the expired one; `--remove` is a
takedown; `--claim` runs `client new` + `site new` and carries the same files
over with every preview-only block cut.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LEADS = ROOT / "bin" / "leads"
SERVICES = HERE / "fixtures" / "leads-services"
DETAILS = SERVICES / "details"
FOOTER = ("A preview Patchlamp made for {name}. Not their official site. "
          "Claim it, or ask us to take it down: founder@patchlamp.com")

# A `site` that records what it was asked to do instead of touching Cloudflare or GitHub.
FAKE_SITE = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
log = Path(os.environ["FAKE_SITE_LOG"])
argv = sys.argv[1:]
with open(log, "a") as f:
    f.write(json.dumps({"tool": "site", "argv": argv, "cwd": os.getcwd(),
                        "admin": os.environ.get("SITE_ADMIN")}) + "\\n")
if argv and argv[0] == "previews":
    print("pages host: patchlamp-previews.pages.dev")
elif argv and argv[0] == "new":
    ws = Path(os.getcwd())
    d = ws / "repos" / argv[1]
    (d / "css").mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(os.environ.get("FAKE_SITE_INDEX") or "<html>the template</html>")
    (d / "photos.html").write_text("<html>photos</html>")
    (d / "css" / "style.css").write_text("body{}")
    os.system("git -C %s init -q -b main" % d)
print("ok")
'''

FAKE_CLIENT = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
log = Path(os.environ["FAKE_SITE_LOG"])
argv = sys.argv[1:]
with open(log, "a") as f:
    f.write(json.dumps({"tool": "client", "argv": argv}) + "\\n")
if argv and argv[0] == "new":
    ws = Path(os.environ["PROJECTS_DIR"]) / "clients" / argv[1]
    (ws / "repos").mkdir(parents=True, exist_ok=True)
    (ws / ".client.json").write_text(json.dumps({"slug": argv[1], "name": argv[-1]}))
print("ok")
'''

# An `img` that answers from a small shared pool of made-up Pexels ids (the same twenty for every
# search, so two previews would collide without the registry) and writes a real tiny PNG; `gen`
# takes only a FILE for --out, the way leads must call it, and an aspect img accepts.
FAKE_IMG = r'''#!/usr/bin/env python3
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
        got.append({"path": str(path), "id": int(pid), "photographer": "A. Fixture", "alt": "a made-up photo", "url": "https://example.test/" + pid})
    print(json.dumps(got))
elif argv[0] == "gen":
    out = Path(opt("--out"))
    if out.is_dir() or opt("--aspect") not in ("1:1", "3:2", "4:3", "16:9", "9:16", "3:4"):
        sys.exit("fake img: --out must be a file and --aspect one img accepts")
    out.write_bytes(PNG)
    print("  [1] " + str(out))
'''


def text_of(html):
    """What a reader sees: comments, scripts and styles out, inline tags joined, block tags spaced,
    whitespace squeezed."""
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.S)
    html = re.sub(r"</?(a|span|strong|em|b|i)\b[^>]*>", "", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


class PreviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        import importlib.util
        spec = importlib.util.spec_from_file_location("leads_services_build", SERVICES / "build.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        self.db = m.build(t / "census.db")
        self.bin = t / "bin"
        self.bin.mkdir()
        self.log = t / "calls.jsonl"
        for name, body in (("site", FAKE_SITE), ("client", FAKE_CLIENT), ("img", FAKE_IMG)):
            p = self.bin / name
            p.write_text(body)
            p.chmod(0o755)
        self.previews = t / "previews"
        self.env = {"LEADS_DB": str(self.db), "LEADS_STATE": str(t / "state"),
                    "LEADS_LEDGER": str(t / "ledger.jsonl"), "LEADS_PREVIEWS": str(self.previews),
                    "LEADS_GROUPS_LOG": str(t / "groups.md"), "CLAUDE_TOOLS_ENV": str(t / "no-env"),
                    "LEADS_PIPELINE": str(t / "pipeline.jsonl"), "LEADS_MAIL_ADDRESS": "",
                    "GOOGLE_MAPS_API_KEY": "", "LEADS_SEGMENT": "services",
                    "PROJECTS_DIR": str(t / "projects"), "FAKE_SITE_LOG": str(self.log),
                    "LEADS_PREVIEW_BIN": str(self.bin), "LEADS_IMG_BIN": str(self.bin / "img"),
                    "FAKE_IMG_LOG": str(t / "img.jsonl")}

    def tearDown(self):
        self.tmp.cleanup()

    def run_leads(self, *args, env=None):
        e = dict(os.environ, **self.env, **(env or {}))
        return subprocess.run([sys.executable, str(LEADS), *args], capture_output=True, text=True, env=e)

    def build(self, *names, **kw):
        args = list(names) + ["--fixture", str(DETAILS), "--hero", "none"]
        if kw.pop("publish", False) is False:
            args.append("--no-publish")
        args += kw.pop("extra", [])
        r = self.run_leads("preview", *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def page(self, slug):
        return (self.previews / "site" / slug / "index.html").read_text()

    def calls(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    # -- the fill ------------------------------------------------------------------------

    def test_a_preview_is_the_listing_and_nothing_else(self):
        self.build("Mike's Pool Care, American Fork")
        slug = "mikes-pool-care-american-fork"
        html = self.page(slug)
        seen = text_of(html)
        self.assertIn("Mike's Pool Care", seen)
        self.assertIn("Pool and spa care in American Fork", seen)        # the category's tagline
        self.assertIn("Weekly service", seen)                            # the category's services
        self.assertIn("(801) 555-0101", seen)
        self.assertIn("4.9", seen)
        self.assertIn("14 reviews", seen)
        self.assertIn("maps.google.com", html)                           # the rating line links the listing
        self.assertIn("American Fork and the towns nearby", seen)        # the city, never the street
        self.assertNotIn("N Main St", seen)
        self.assertNotIn("$", seen)                                      # no price on a preview, ever
        self.assertNotIn("googleusercontent", html)                      # never their Google photos
        self.assertNotIn("places/", html)
        self.assertNotIn("Best pool guy", seen)                          # never a review's words
        self.assertNotIn("{{", html)
        meta = json.loads((self.previews / "meta" / f"{slug}.json").read_text())
        self.assertEqual((meta["place_id"], meta["template"], meta["category"]),
                         ("FX_S01", "service", "pool service"))
        self.assertEqual(meta["cost_usd"], 0.0)

    def test_the_footer_says_exactly_what_the_page_is(self):
        self.build("Mike's Pool Care, American Fork")
        seen = text_of(self.page("mikes-pool-care-american-fork"))
        self.assertIn(FOOTER.format(name="Mike's Pool Care"), seen)
        self.assertIn("A preview — not Mike's Pool Care's official website.", seen)
        self.assertIn("This preview comes down on", seen)

    def test_noindex_on_the_page_and_on_the_project(self):
        self.build("Mike's Pool Care, American Fork")
        self.assertIn('<meta name="robots" content="noindex, nofollow, noarchive">',
                      self.page("mikes-pool-care-american-fork"))
        site = self.previews / "site"
        headers = (site / "_headers").read_text()
        self.assertIn("X-Robots-Tag: noindex, nofollow, noarchive, nosnippet", headers)
        self.assertIn("Disallow: /", (site / "robots.txt").read_text())
        for f in ("index.html", "404.html"):
            self.assertIn('name="robots" content="noindex', (site / f).read_text())
        self.assertNotIn("Mike", text_of((site / "index.html").read_text()), "the root names nobody")

    def test_the_category_decides_the_template_and_the_words(self):
        self.build("Rosie's Florals", "Beat Drop DJs", "Sweet Crumb Cottage Bakery",
                   "Lehi Youth Soccer League")
        for slug, kind, word in (("rosies-florals-pleasant-grove", "portfolio", "Arrangements"),
                                 ("beat-drop-djs-lehi", "portfolio", "Weddings"),
                                 ("sweet-crumb-cottage-bakery-american-fork", "store", "Bread"),
                                 ("lehi-youth-soccer-league-lehi", "nonprofit", "Registration")):
            meta = json.loads((self.previews / "meta" / f"{slug}.json").read_text())
            self.assertEqual(meta["template"], kind, slug)
            self.assertIn(word, text_of(self.page(slug)), slug)
            self.assertIn(f"--accent", (self.previews / "site" / slug / "css" / "style.css").read_text())

    def test_hours_come_from_the_listing_or_the_page_says_so(self):
        self.build("Blue Canyon Landscaping", "Mike's Pool Care, American Fork")
        seen = text_of(self.page("blue-canyon-landscaping-lehi"))
        self.assertIn("Mon: 7:00 AM-5:00 PM", seen)     # Google's own wording, from weekdayDescriptions
        self.assertIn("Tue-Sun: closed", seen)          # the days it doesn't list are said, not left out
        self.assertIn("Google doesn't show hours for Mike's Pool Care yet",
                      text_of(self.page("mikes-pool-care-american-fork")))

    def test_a_preview_costs_nothing_and_leaves_one_ledger_row_each(self):
        self.build("Mike's Pool Care, American Fork", "Blue Canyon Landscaping")
        rows = [json.loads(x) for x in (Path(self.tmp.name) / "ledger.jsonl").read_text().splitlines()]
        made = [r for r in rows if r["kind"] == "preview"]
        self.assertEqual(len(made), 2)
        self.assertEqual(sum(r["cost_usd"] for r in rows), 0.0, "fixtures and stock photos are free")
        self.assertEqual({r["tool"] for r in made}, {"leads"})

    # -- the life of one -----------------------------------------------------------------

    def test_the_slug_is_stable_so_a_link_already_sent_keeps_working(self):
        self.build("Mike's Pool Care, American Fork")
        before = json.loads((self.previews / "meta" / "mikes-pool-care-american-fork.json").read_text())
        self.build("Mike's Pool Care, American Fork")
        self.assertEqual(len(list((self.previews / "meta").glob("*.json"))), 1)
        after = json.loads((self.previews / "meta" / "mikes-pool-care-american-fork.json").read_text())
        self.assertEqual(before["url"], after["url"])

    def test_thirty_days_expire_on_a_moved_clock_and_sweep_takes_the_one_down(self):
        self.build("Mike's Pool Care, American Fork")
        self.build("Blue Canyon Landscaping", extra=["--days", "3"])
        r = self.run_leads("preview", "sweep", "--no-publish")
        self.assertIn("nothing expired", r.stdout)
        r = self.run_leads("preview", "sweep", "--no-publish", env={"LEADS_NOW": "2026-10-05"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("removing blue-canyon-landscaping-lehi", r.stdout)
        self.assertNotIn("mikes-pool-care", r.stdout)
        self.assertEqual(r.stdout.strip().splitlines()[-1], "1 preview(s) removed; 1 left")
        self.assertFalse((self.previews / "site" / "blue-canyon-landscaping-lehi").exists())
        self.assertTrue((self.previews / "site" / "mikes-pool-care-american-fork").exists())

    def test_remove_is_a_takedown_and_it_publishes_again(self):
        self.build("Mike's Pool Care, American Fork")
        r = self.run_leads("preview", "--remove", "Mike's Pool Care")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("removed mikes-pool-care-american-fork", r.stdout)
        self.assertFalse((self.previews / "site" / "mikes-pool-care-american-fork").exists())
        self.assertFalse((self.previews / "meta" / "mikes-pool-care-american-fork.json").exists())
        pub = [c for c in self.calls() if c["tool"] == "site" and c["argv"][0] == "previews"]
        self.assertTrue(pub, "a takedown republishes the tree")
        self.assertEqual(pub[-1]["admin"], "1", "the previews project is an owner's to write")
        r = self.run_leads("preview", "--remove", "Nobody At All")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no preview for", r.stderr)

    def test_ls_says_how_long_each_has(self):
        self.build("Mike's Pool Care, American Fork")
        out = self.run_leads("preview", "ls").stdout
        self.assertIn("mikes-pool-care-american-fork", out)
        self.assertIn("30d left", out)
        self.assertIn("EXPIRED", self.run_leads("preview", "ls", env={"LEADS_NOW": "2026-12-01"}).stdout)

    # -- the kit carries the link --------------------------------------------------------

    def test_the_kit_only_builds_previews_when_it_is_asked(self):
        plain = self.run_leads("kit", "--remote", "--segment", "services", "--fixture", str(DETAILS),
                               "--json", "--no-save")
        self.assertEqual(plain.returncode, 0, plain.stderr)
        envelope = json.loads(plain.stdout)
        self.assertEqual(sorted(envelope), ["date", "picks", "segment"])
        self.assertEqual(envelope["segment"], "services")
        for k in ("place_id", "name", "first", "category", "segment", "city", "phone", "email",
                  "instagram", "facebook", "faults", "preview_url", "maps_url"):
            self.assertIn(k, envelope["picks"][0], k)
        self.assertTrue(all(p["preview_url"] is None for p in envelope["picks"]))
        self.assertFalse((self.previews / "meta").exists(), "no --previews, nothing built")

        with_ = self.run_leads("kit", "--remote", "--segment", "services", "--fixture", str(DETAILS),
                               "--previews", "--json", "--no-save")
        self.assertEqual(with_.returncode, 0, with_.stderr)
        picks = json.loads(with_.stdout)["picks"]
        self.assertTrue(all(p["preview_url"] for p in picks), [p["preview_url"] for p in picks])
        for p in picks:
            self.assertTrue(p["preview_url"].endswith("/"), p["preview_url"])
            # 2026-09-30, the register: message one says it is built and carries no link (the link is message two)
            self.assertNotIn(p["preview_url"], p["message"], "no link in message one")
            self.assertIn("So I went ahead and built you one", p["message"])
            self.assertTrue(p["message"].endswith("Want to see it?"), p["message"])
        page = self.run_leads("kit", "--remote", "--segment", "services", "--fixture", str(DETAILS),
                              "--no-save").stdout
        self.assertIn("Their preview site: https://", page)
        self.assertNotIn("I also built you a page", page)
        self.assertNotIn("$", page)

    # -- claiming one --------------------------------------------------------------------

    def test_claim_runs_client_new_and_site_new_from_the_same_files(self):
        self.build("Mike's Pool Care, American Fork")
        dry = self.run_leads("preview", "--claim", "Mike's Pool Care", "--slug", "mikes-pool-care", "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn("would run: client new mikes-pool-care", dry.stdout)
        self.assertIn("would run: site new mikes-pool-care-site --template service", dry.stdout)
        self.assertIn("would copy the whole rendered site", dry.stdout)
        self.assertIn("switch the forms on", dry.stdout)
        self.assertEqual(self.calls(), [], "a dry run runs nothing")

        r = self.run_leads("preview", "--claim", "Mike's Pool Care", "--slug", "mikes-pool-care")
        self.assertEqual(r.returncode, 0, r.stderr)
        ran = [(c["tool"], c["argv"][0]) for c in self.calls()]
        self.assertIn(("client", "new"), ran)
        self.assertIn(("site", "new"), ran)
        self.assertIn(("site", "publish"), ran)
        repo = Path(self.tmp.name) / "projects" / "clients" / "mikes-pool-care" / "repos" / "mikes-pool-care-site"
        built = (repo / "index.html").read_text()
        seen = text_of(built)
        self.assertIn("Weekly service", seen)                     # the same page
        self.assertIn("(801) 555-0101", seen)
        self.assertNotIn("preview", seen.lower())                 # none of the preview's words
        self.assertNotIn("noindex", built)
        self.assertNotIn("demo-bar", built)
        self.assertNotIn("preview.css", built)
        self.assertNotIn("founder@patchlamp.com", built)
        self.assertIn("<title>Mike's Pool Care</title>", built)
        self.assertIn('<a href="photos.html">Photos</a>', built)  # the template's other page is linked
        self.assertIn("&copy; ", built)
        self.assertIn('<p class="patchlamp-badge"><a href="https://patchlamp.com/for/home-services?from=badge"'
                      ' rel="noopener">Patched by Patchlamp</a></p>', built,
                      "B60: a claimed site carries the badge, with its segment's page")
        # the whole rendered site came over, the overlay cut, the forms switched on (B64)
        self.assertIn('action="/api/submissions"', built)
        self.assertIn('action="/api/bookings"', built, "the template's calendar is kept")
        self.assertNotIn("disabled", built)
        self.assertNotIn("goes live when the site is claimed", built)
        self.assertNotIn("<!--c:", built)
        self.assertNotIn("<!--p:", built)
        self.assertIn('<a href="/admin">Owner sign-in</a>', built)
        for f in ("photos.html", "404.html", "css/sections.css", "css/looks/sturdy.css", "css/looks/fresh.css",
                  "css/looks/classic.css", "fonts/OFL.txt", "js/main.js"):
            self.assertTrue((repo / f).exists(), f)
        self.assertFalse((repo / "claim").exists(), "the claim redirect stays on the previews host")
        self.assertFalse((repo / "css" / "preview.css").exists())
        self.assertNotIn("preview", text_of((repo / "photos.html").read_text()).lower())
        meta = json.loads((self.previews / "meta" / "mikes-pool-care-american-fork.json").read_text())
        self.assertEqual(meta["claimed"], "mikes-pool-care")
        self.assertNotIn("mikes-pool-care-american-fork",
                         self.run_leads("kit", "--remote", "--segment", "services", "--fixture", str(DETAILS),
                                        "--previews", "--json", "--no-save").stdout,
                         "a claimed preview is not offered again")

    # -- the section library, the looks, the renderer (plan 28, B64) ----------------------

    def content_of(self, slug):
        return json.loads((self.previews / "content" / slug / "content.json").read_text())

    def test_one_content_json_renders_in_every_look_with_nothing_from_a_third_party(self):
        self.build("Mike's Pool Care, American Fork", extra=["--hero", "stock"])
        src = self.previews / "content" / "mikes-pool-care-american-fork" / "content.json"
        content = json.loads(src.read_text())
        self.assertEqual((content["schema"], content["template"]), (1, "service"))
        self.assertEqual([x["type"] for x in content["sections"]][:3], ["hero", "proof", "services"])
        looks = sorted(p.stem for p in (ROOT / "templates/sites/service/css/looks").glob("*.css"))
        self.assertEqual(len(looks), 3)
        for look in looks:
            out = Path(self.tmp.name) / "looks" / look
            r = self.run_leads("preview", "--from", str(src), "--out", str(out), "--look", look)
            self.assertEqual(r.returncode, 0, r.stderr)
            html = (out / "index.html").read_text()
            self.assertIn(f'href="css/looks/{look}.css"', html)
            for f in ("photos.html", "404.html", "claim/index.html", "css/style.css", "css/sections.css",
                      "css/preview.css", "js/main.js", "images/hero.jpg"):
                self.assertTrue((out / f).exists(), f"{look}: {f}")
            css = (out / "css" / "looks" / f"{look}.css").read_text()
            for font in re.findall(r'url\("\.\./\.\./(fonts/[^"]+)"\)', css):
                self.assertTrue((out / font).exists(), font)
            for page in ("index.html", "photos.html"):
                h = (out / page).read_text()
                for ref in re.findall(r'(?:src|href)="([^"]+)"', h):
                    if ref.startswith(("http", "//")):
                        self.assertRegex(ref, r"^https://(patchlamp\.com|maps\.google\.com)", f"{page}: {ref}")
                    elif not ref.startswith(("#", "tel:", "mailto:", "/admin", "index.html#")):
                        self.assertTrue((out / ref.split("#")[0]).exists(), f"{look} {page}: {ref}")
            self.assertEqual(html.count('class="img-label"'), html.count("<img "), "every picture says what it is")
            self.assertIn("This form goes live when the site is claimed.", text_of(html))
            self.assertRegex(html, r'<fieldset class="form-fields" disabled>')
            self.assertIn('<a href="claim/">Claim it</a>', html)
        self.assertFalse((self.previews / "site" / "looks").exists(), "--out records nothing in the tree")

    def test_the_claim_link_opens_the_sign_up_filled(self):
        self.build("Mike's Pool Care, American Fork")
        page = (self.previews / "site" / "mikes-pool-care-american-fork" / "claim" / "index.html").read_text()
        self.assertIn('<meta name="robots" content="noindex, nofollow, noarchive">', page)
        url = re.search(r'url=([^"]+)"', page).group(1).replace("&amp;", "&")
        self.assertEqual(url, "https://patchlamp.com/start?business=Mike%27s+Pool+Care&city=American+Fork"
                              "&category=pool+service&preview=mikes-pool-care-american-fork")
        self.assertIn(url, json.loads((self.previews / "meta" / "mikes-pool-care-american-fork.json").read_text())["claim_url"])

    def test_from_holds_a_content_json_to_the_contract(self):
        self.build("Mike's Pool Care, American Fork")
        content = self.content_of("mikes-pool-care-american-fork")
        content["sections"][0].pop("heading")
        content["sections"].append({"type": "menu", "heading": {"text": "x", "facts": []}})
        content["sections"][2]["heading"] = {"text": "Something we made up", "facts": []}
        content["look"] = "neon"
        bad = Path(self.tmp.name) / "bad.json"
        bad.write_text(json.dumps(content))
        r = self.run_leads("preview", "--from", str(bad), "--out", str(Path(self.tmp.name) / "bad"))
        self.assertEqual(r.returncode, 1)
        for want in ("sections[0] hero: missing heading", "type 'menu' is not in the service library",
                     "no facts and not listed in generic[]", "look 'neon'"):
            self.assertIn(want, r.stderr)

    def test_two_previews_in_one_run_never_share_a_photo(self):
        self.build("Dave's Handyman Services", "ProCoat Painters", "Mike's Pool Care, American Fork",
                   extra=["--hero", "stock"])
        seen = {}
        for m in (json.loads(p.read_text()) for p in (self.previews / "meta").glob("*.json")):
            self.assertEqual(len(m["images"]), 5, m["slug"])               # a hero and four more
            for i in m["images"]:
                self.assertNotIn(i, seen, f"{m['slug']} reuses {i} from {seen.get(i)}")
                seen[i] = m["slug"]
        rows = [json.loads(x) for x in (self.previews / "images.jsonl").read_text().splitlines()]
        self.assertEqual(len(rows), 15)
        calls = [json.loads(x) for x in (Path(self.tmp.name) / "img.jsonl").read_text().splitlines()]
        self.assertTrue(all("--skip-file" in c and "--seed" in c for c in calls if c[0] == "stock"))
        # a rebuild keeps its own photos: its seed is its slug, and its own ids are not skipped
        before = json.loads((self.previews / "meta" / "procoat-painters-american-fork.json").read_text())["images"]
        self.build("ProCoat Painters", extra=["--hero", "stock"])
        after = json.loads((self.previews / "meta" / "procoat-painters-american-fork.json").read_text())["images"]
        self.assertEqual(before, after)

    def test_hero_gen_hands_img_a_file_and_an_aspect_it_takes(self):
        self.build("Mike's Pool Care, American Fork", extra=["--hero", "gen"])
        calls = [json.loads(x) for x in (Path(self.tmp.name) / "img.jsonl").read_text().splitlines()]
        gen = [c for c in calls if c[0] == "gen"]
        self.assertEqual(len(gen), 1)
        self.assertTrue(gen[0][gen[0].index("--out") + 1].endswith("/hero.png"))
        self.assertEqual(gen[0][gen[0].index("--aspect") + 1], "16:9")
        meta = json.loads((self.previews / "meta" / "mikes-pool-care-american-fork.json").read_text())
        self.assertEqual(meta["hero"], "generated")
        self.assertIn("Made with AI", self.page("mikes-pool-care-american-fork"))

    def test_hours_read_the_way_a_person_says_them(self):
        import importlib.machinery, importlib.util
        loader = importlib.machinery.SourceFileLoader("leads_t", str(LEADS))
        spec = importlib.util.spec_from_loader("leads_t", loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
        allday = {"regularOpeningHours": {"weekdayDescriptions": [
            f"{d}: Open 24 hours" for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]}}
        self.assertEqual(mod.hours_for_people(allday, {"segment": "services"}), ["Call or text any day"])
        self.assertEqual(mod.hours_for_people({"regularOpeningHours": {"periods": [{"open": {"day": 0}}]}},
                                              {"segment": "services"}), ["Call or text any day"])
        self.assertEqual(mod.hours_for_people(allday, {"segment": "retail"}), ["Mon-Sun: Open 24 hours"])
        self.assertEqual(mod.hours_for_people(allday, {"segment": "services"}, say="By appointment"), ["By appointment"])

    def test_a_claim_never_replaces_a_page_with_a_thinner_one(self):
        self.build("Mike's Pool Care, American Fork")
        content = self.content_of("mikes-pool-care-american-fork")
        content["sections"] = [x for x in content["sections"] if x["type"] != "booking"]
        thin = self.previews / "content" / "mikes-pool-care-american-fork" / "thin.json"
        thin.write_text(json.dumps(content))
        r = self.run_leads("preview", "--from", str(thin), "--no-publish")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_leads("preview", "--claim", "mikes-pool-care-american-fork", "--slug", "mikes-pool-care",
                           env={"FAKE_SITE_INDEX": '<form action="/api/bookings"></form><form action="/api/submissions"></form>'})
        self.assertEqual(r.returncode, 1)
        self.assertIn("no form for /api/bookings", r.stderr)
        repo = Path(self.tmp.name) / "projects" / "clients" / "mikes-pool-care" / "repos" / "mikes-pool-care-site"
        self.assertIn("/api/bookings", (repo / "index.html").read_text(), "nothing was copied")

    def test_the_library_is_one_file_set_for_both_templates(self):
        sites = ROOT / "templates" / "sites"
        for f in sorted((sites / "portfolio" / "sections").glob("*.html")) + [sites / "portfolio/css/sections.css"]:
            twin = sites / "service" / f.relative_to(sites / "portfolio")
            self.assertEqual(f.read_text(), twin.read_text(), f"{f.name} differs between service and portfolio")

    # -- the copy table and doctor -------------------------------------------------------

    def test_every_census_category_has_copy_and_a_template_that_exists(self):
        table = json.loads((ROOT / "templates" / "previews" / "categories.json").read_text())
        want = set()
        cats = json.loads((Path.home() / "projects/client-leads/scripts/services.json").read_text()) \
            if (Path.home() / "projects/client-leads/scripts/services.json").exists() else None
        if cats:
            for rows in cats["segments"].values():
                want |= set(rows)
            self.assertEqual(want - set(table["categories"]), set(), "a category with no copy row")
        kinds = {v["template"] for v in table["categories"].values()} | {table["_default"]["template"]}
        for k in kinds:
            self.assertTrue((ROOT / "templates" / "sites" / k / "index.html").exists(), k)
        for name, row in table["categories"].items():
            for key in ("template", "trade", "tagline", "intro", "services", "hero", "cta"):
                self.assertIn(key, row, name)
            self.assertTrue(3 <= len(row["services"]) <= 6, name)
            for head, line in row["services"]:
                self.assertTrue(head and line, name)
            for field in (row["tagline"], row["intro"]):
                for token in re.findall(r"\{(\w+)\}", field):
                    self.assertIn(token, ("name", "city", "category", "trade"), f"{name}: {{{token}}}")

    def test_doctor_reports_the_previews(self):
        self.build("Mike's Pool Care, American Fork")
        out = self.run_leads("doctor").stdout
        self.assertIn("previews:", out)
        self.assertIn("copy table: 33 categories", out)
        self.assertIn("built: 1 (1 live, 0 claimed)", out)
        self.assertIn("previews.patchlamp.com not attached yet", out)

    def test_an_unknown_name_says_so_instead_of_inventing_a_page(self):
        r = self.run_leads("preview", "Zzqx Nonexistent Roofing", "--no-publish")
        self.assertEqual(r.returncode, 1)
        self.assertIn("isn't in the census", r.stderr)
        self.assertFalse((self.previews / "meta").exists())


if __name__ == "__main__":
    unittest.main()
