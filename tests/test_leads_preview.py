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
    (d / "index.html").write_text("<html>the template</html>")
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


def text_of(html):
    """What a reader sees: tags out, whitespace squeezed."""
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
        for name, body in (("site", FAKE_SITE), ("client", FAKE_CLIENT)):
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
                    "LEADS_PREVIEW_BIN": str(self.bin)}

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
            self.assertIn(p["preview_url"], p["message"], "the message carries the link")
        page = self.run_leads("kit", "--remote", "--segment", "services", "--fixture", str(DETAILS),
                              "--no-save").stdout
        self.assertIn("Their preview site: https://", page)
        self.assertIn("nothing to sign, and I'll take it down the moment you say so.", page)
        self.assertNotIn("$", page)

    # -- claiming one --------------------------------------------------------------------

    def test_claim_runs_client_new_and_site_new_from_the_same_files(self):
        self.build("Mike's Pool Care, American Fork")
        dry = self.run_leads("preview", "--claim", "Mike's Pool Care", "--slug", "mikes-pool-care", "--dry-run")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertIn("would run: client new mikes-pool-care", dry.stdout)
        self.assertIn("would run: site new mikes-pool-care-site --template service", dry.stdout)
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
        meta = json.loads((self.previews / "meta" / "mikes-pool-care-american-fork.json").read_text())
        self.assertEqual(meta["claimed"], "mikes-pool-care")
        self.assertNotIn("mikes-pool-care-american-fork",
                         self.run_leads("kit", "--remote", "--segment", "services", "--fixture", str(DETAILS),
                                        "--previews", "--json", "--no-save").stdout,
                         "a claimed preview is not offered again")

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
