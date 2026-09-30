"""The site watched (ROADMAP B72, plan ~/projects/plans/30-site-watch.md) — the toolbelt half.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

bin/site is loaded as a module; DNS, the HTTPS fetch and RDAP are faked, the clock is moved by hand,
`notify` is captured, and the TAYLOR-TODO § 7 entry goes through the relay's own helper
(relay/escalate.py append_todo) into a temp file. What's pinned: one failed check says nothing (a blip);
the second in a row opens an outage in uptime.json, tells Taylor once and files § 7 once; the first good
check closes it with its minutes; DNS pointing away and a page that isn't ours both count as down; a
preview is reported and never gets a § 7 entry (the relay texts nobody for it — it has no owner), one never
seen up is not an outage, and one past its 30 days still up is reported once; a custom domain inside 30
days of expiry files § 7 once and the RDAP read is weekly; --dry-run writes nothing; `site doctor` shows a
last check for every site, and inside a client workspace only that client's.
"""

import argparse
import contextlib
import datetime
import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELAY = Path(os.environ.get("RELAY_DIR") or Path.home() / "projects/sms-relay")
TZ = datetime.timezone(datetime.timedelta(hours=-6))
T0 = datetime.datetime(2026, 9, 29, 9, 0, tzinfo=TZ)

GOOD = '<html><body><header class="site-header"></header><p class="patchlamp-badge">Patched</p></body></html>'
PREVIEW = '<html><body><div class="preview-note">A preview Patchlamp made for Mike</div></body></html>'
PARKED = "<html><body>This domain is parked. Buy it now!</body></html>"
TODO = "# TODO\n\n## 1. Now\n\n- [ ] something\n\n## 7. Triage — filed by Patch, diagnosed, waiting on you\n\nIntro.\n"


def load_site():
    loader = importlib.machinery.SourceFileLoader("site_tool_watch", str(ROOT / "bin" / "site"))
    spec = importlib.util.spec_from_loader("site_tool_watch", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class WatchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.d = d
        self.site = load_site()
        s = self.site
        s.REGISTRY = d / "sites.json"
        s.WATCH_FILE = d / "state" / "uptime.json"
        s.WATCH_PREVIEWS = d / "previews"
        s.WATCH_TODO = d / "TAYLOR-TODO.md"
        s.WATCH_TODO.write_text(TODO)
        s.WATCH_RELAY_DIR = RELAY
        s.WATCH_PRETEND.clear()
        s.HOSTS.clear() if hasattr(s, "HOSTS") else None
        self.registry = {
            "demo-service": {"demo-service": {"host": "cloudflare", "project": "demo-service"}},
            "acme": {"acme-site": {"host": "cloudflare", "project": "acme-site", "domains": ["acme.com", "www.acme.com"]}},
        }
        s.REGISTRY.write_text(json.dumps(self.registry))
        self.now = T0
        s.watch_now = lambda: self.now
        self.dns = {"demo-service.pages.dev": ["172.66.44.1"], "acme.com": ["104.21.3.4"],
                    "patchlamp-previews.pages.dev": ["172.66.47.9"]}
        self.pages = {}                      # (host, path) -> (status, body) ; default GOOD 200
        s.watch_resolve = lambda host: list(self.dns.get(host, []))
        s.watch_fetch = self.fake_fetch
        self.rdap_calls = []
        self.rdap = {"acme.com": {"name": "acme.com", "expires": "2027-06-01", "registrar": "Porkbun LLC", "error": ""}}
        s.watch_rdap = self.fake_rdap
        self.told = []
        s.watch_notify = self.told.append
        self.out = io.StringIO()

    def tearDown(self):
        self.tmp.cleanup()

    def fake_fetch(self, host, ip, path="/", hops=3):
        status, body = self.pages.get((host, path), (200, PREVIEW if "previews" in host else GOOD))
        return status, body, 80, ""

    def fake_rdap(self, domain):
        self.rdap_calls.append(domain)
        return dict(self.rdap[self.site.watch_registrable(domain)])

    def run_once(self, minutes=15, **kw):
        self.now = self.now + datetime.timedelta(minutes=minutes)
        with contextlib.redirect_stdout(self.out):
            data, events = self.site.watch_run(**kw)
        return data, events

    def row(self, key="demo-service/demo-service"):
        return json.loads(self.site.WATCH_FILE.read_text())["sites"][key]

    def down(self, status=404, key=("demo-service.pages.dev", "/")):
        self.pages[key] = (status, "")

    def todo_text(self):
        return self.site.WATCH_TODO.read_text()


class OutageTests(WatchCase):
    def test_a_blip_is_never_told(self):
        self.run_once()
        self.down()
        _, events = self.run_once()
        r = self.row()
        self.assertEqual(r["fails"], 1)
        self.assertIsNone(r["outage"])
        self.assertEqual(events, [])
        self.assertEqual(self.told, [])
        self.pages.clear()
        self.run_once()
        r = self.row()
        self.assertEqual((r["fails"], r["state"], r["outages"]), (0, "up", []))
        self.assertEqual(self.told, [], "one bad check and a good one: nobody hears anything")
        self.assertNotIn("demo-service's site is down", self.todo_text())

    @unittest.skipUnless((RELAY / "relay" / "escalate.py").exists(), "needs the relay checkout for append_todo")
    def test_two_in_a_row_open_an_outage_once_and_the_first_good_check_closes_it(self):
        self.run_once()
        self.down()
        self.run_once()                                   # 09:30, first failure
        _, events = self.run_once()                       # 09:45, confirmed
        r = self.row()
        self.assertEqual(r["state"], "down")
        self.assertEqual(r["outage"]["since"], (T0 + datetime.timedelta(minutes=30)).isoformat())
        self.assertEqual(r["outage"]["id"], f"demo-service/demo-service@{r['outage']['since']}")
        self.assertIn("HTTP 404", r["outage"]["problem"])
        self.assertEqual(len(self.told), 1)
        self.assertIn("DOWN demo-service/demo-service", self.told[0])
        todo = self.todo_text()
        self.assertEqual(todo.count("demo-service's site is down"), 1)
        seven = todo.split("## 7.")[1]
        self.assertIn("demo-service's site is down", seven, "filed under § 7 by the triage's own helper")
        self.assertIn("site publish demo-service", seven)
        self.assertIn(f"outage:{r['outage']['id']}", r["filed"])
        self.run_once()                                   # still down: nothing new
        self.assertEqual(len(self.told), 1)
        self.assertEqual(self.todo_text().count("demo-service's site is down"), 1)
        self.pages.clear()
        _, events = self.run_once()                       # 10:15, back
        r = self.row()
        self.assertIsNone(r["outage"])
        self.assertEqual(r["state"], "up")
        self.assertEqual(len(r["outages"]), 1)
        self.assertEqual(r["outages"][0]["minutes"], 45)
        self.assertEqual(r["outages"][0]["until"], self.now.isoformat())
        self.assertEqual(len(self.told), 2)
        self.assertIn("BACK demo-service/demo-service", self.told[1])

    def test_dns_pointing_away_is_down(self):
        self.dns["demo-service.pages.dev"] = ["93.184.216.34"]
        self.run_once()
        c = self.row()["last_check"]
        self.assertFalse(c["ok"])
        self.assertIn("points away from Cloudflare", c["problem"])
        self.assertTrue(c["dns"].startswith("elsewhere:"))
        self.dns["demo-service.pages.dev"] = []
        self.run_once()
        self.assertIn("does not resolve", self.row()["last_check"]["problem"])
        self.assertIsNotNone(self.row()["outage"])

    def test_a_page_that_is_not_ours_is_down(self):
        self.pages[("demo-service.pages.dev", "/")] = (200, PARKED)
        self.run_once()
        c = self.row()["last_check"]
        self.assertFalse(c["ok"])
        self.assertIn("not our page", c["problem"])

    def test_a_registry_marker_overrides_the_template_markers(self):
        self.registry["demo-service"]["demo-service"]["watch_marker"] = "Juniper Flats"
        self.site.REGISTRY.write_text(json.dumps(self.registry))
        self.run_once()
        self.assertFalse(self.row()["last_check"]["ok"])
        self.pages[("demo-service.pages.dev", "/")] = (200, "<h1>Juniper Flats Pool</h1>")
        self.run_once()
        self.assertTrue(self.row()["last_check"]["ok"])

    def test_pretend_down_is_a_rehearsal_that_opens_a_real_outage(self):
        self.site.WATCH_TODO.write_text(TODO)
        self.site.watch_file_todo = lambda entry: True
        self.site.WATCH_PRETEND.add("demo-service")
        self.run_once()
        self.run_once()
        r = self.row()
        self.assertIsNotNone(r["outage"])
        self.assertIn("rehearsal", r["outage"]["problem"])
        self.assertEqual(json.loads(self.site.WATCH_FILE.read_text())["last_run"]["pretend"], ["demo-service"])
        self.site.WATCH_PRETEND.clear()
        self.run_once()
        self.assertIsNone(self.row()["outage"])

    def test_a_gap_in_the_checks_is_recorded(self):
        self.run_once()
        self.run_once(minutes=120)
        g = self.row()["gaps"]
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0]["to"], self.now.isoformat())

    def test_dry_run_writes_nothing_and_tells_nobody(self):
        self.down()
        self.run_once(dry=True)
        self.run_once(dry=True)
        self.assertFalse(self.site.WATCH_FILE.exists())
        self.assertEqual(self.told, [])
        self.assertEqual(self.todo_text(), TODO)


class PreviewTests(WatchCase):
    def previews(self, expires="2026-10-28", claimed=None):
        p = self.site.WATCH_PREVIEWS
        (p / "meta").mkdir(parents=True, exist_ok=True)
        (p / "project.json").write_text(json.dumps({"pages_host": "patchlamp-previews.pages.dev",
                                                    "project": "patchlamp-previews"}))
        (p / "meta" / "mikes-pool.json").write_text(json.dumps({"slug": "mikes-pool", "name": "Mike's Pool",
                                                                "expires": expires, "claimed": claimed}))

    def test_no_previews_until_the_project_is_published(self):
        (self.site.WATCH_PREVIEWS / "meta").mkdir(parents=True)
        (self.site.WATCH_PREVIEWS / "meta" / "x.json").write_text(json.dumps({"slug": "x", "expires": "2026-10-28"}))
        self.assertFalse(any(t["kind"] == "preview" for t in self.site.watch_targets()))

    def test_a_preview_down_is_reported_and_never_filed(self):
        self.previews()
        self.run_once()
        self.assertEqual(self.row("preview/mikes-pool")["state"], "up")
        self.pages[("patchlamp-previews.pages.dev", "/mikes-pool/")] = (404, "")
        self.run_once()
        self.run_once()
        r = self.row("preview/mikes-pool")
        self.assertIsNotNone(r["outage"])
        self.assertEqual(r["kind"], "preview")
        self.assertEqual(len(self.told), 1)
        self.assertIn("reported, not texted", self.told[0])
        self.assertEqual(self.todo_text(), TODO, "a preview is Taylor's to know, not a § 7 entry")

    def test_a_preview_never_seen_up_is_not_an_outage(self):
        self.previews()
        self.dns.pop("patchlamp-previews.pages.dev")
        self.run_once()
        self.run_once()
        r = self.row("preview/mikes-pool")
        self.assertEqual(r["state"], "pending")
        self.assertIsNone(r["outage"])
        self.assertEqual(self.told, [])

    def test_a_preview_left_to_expire_is_reported_once(self):
        self.previews(expires="2026-09-20")
        _, events = self.run_once()
        self.assertEqual(self.row("preview/mikes-pool")["state"], "expired")
        self.assertEqual(len(self.told), 1)
        self.assertIn("EXPIRED preview/mikes-pool", self.told[0])
        self.assertIn("leads preview sweep", self.told[0])
        self.assertIn("not texted", self.told[0])
        self.run_once()
        self.assertEqual(len(self.told), 1, "once per preview, not every fifteen minutes")

    def test_a_swept_preview_is_no_longer_watched(self):
        self.previews()
        self.run_once()
        (self.site.WATCH_PREVIEWS / "meta" / "mikes-pool.json").unlink()
        self.run_once()
        self.assertNotIn("preview/mikes-pool", json.loads(self.site.WATCH_FILE.read_text())["sites"])


class DomainTests(WatchCase):
    @unittest.skipUnless((RELAY / "relay" / "escalate.py").exists(), "needs the relay checkout for append_todo")
    def test_a_domain_inside_thirty_days_files_the_entry_once(self):
        self.rdap["acme.com"]["expires"] = (T0 + datetime.timedelta(days=20)).date().isoformat()
        _, events = self.run_once()
        r = self.row("acme/acme-site")
        self.assertEqual(r["url"], "https://acme.com/")
        self.assertEqual(r["domain"]["days_left"], 20)
        self.assertEqual(r["domain"]["registrar"], "Porkbun LLC")
        todo = self.todo_text()
        self.assertIn("acme.com expires", todo)
        self.assertIn("Registered with Porkbun LLC", todo)
        self.assertIn("## 7.", todo.split("acme.com expires")[0])
        self.assertEqual(len(self.told), 1)
        self.assertIn("DOMAIN acme.com", self.told[0])
        self.run_once()
        self.assertEqual(self.todo_text().count("acme.com expires"), 1)
        self.assertEqual(len(self.told), 1)

    def test_rdap_is_read_once_a_week(self):
        self.run_once()
        self.run_once()
        self.assertEqual(self.rdap_calls, ["acme.com"])
        self.run_once(minutes=7 * 24 * 60)
        self.assertEqual(self.rdap_calls, ["acme.com", "acme.com"])
        self.assertEqual(self.row("acme/acme-site")["domain"]["days_left"], 238)
        self.assertEqual(self.told, [], "a year away: nothing to say")

    def test_registrable_names(self):
        self.assertEqual(self.site.watch_registrable("www.acme.com"), "acme.com")
        self.assertEqual(self.site.watch_registrable("shop.acme.co.uk"), "acme.co.uk")


class DoctorTests(WatchCase):
    def doctor(self, cwd=None):
        fails = []
        buf = io.StringIO()
        old = os.getcwd()
        try:
            if cwd:
                os.chdir(cwd)
            with contextlib.redirect_stdout(buf):
                self.site.watch_doctor(fails.append)
        finally:
            os.chdir(old)
        return buf.getvalue(), fails

    def test_every_site_shows_its_last_check(self):
        self.run_once()
        text, fails = self.doctor()
        self.assertIn("demo-service/demo-service: up · last check 2026-09-29T09:15", text)
        self.assertIn("acme/acme-site: up · last check 2026-09-29T09:15", text)
        self.assertIn("acme.com expires 2027-06-01 (Porkbun LLC)", text)
        self.assertEqual(fails, [])

    def test_a_site_down_or_a_stopped_watch_fails_doctor(self):
        self.run_once()
        self.down()
        self.run_once()
        self.run_once()
        _, fails = self.doctor()
        self.assertTrue(any("demo-service/demo-service: down" in f for f in fails))
        self.now += datetime.timedelta(hours=3)
        _, fails = self.doctor()
        self.assertTrue(any("the watch has stopped" in f for f in fails))

    def test_a_client_workspace_sees_only_its_own_sites(self):
        self.run_once()
        ws = self.d / "clients" / "acme"
        ws.mkdir(parents=True)
        (ws / ".client.json").write_text(json.dumps({"slug": "acme", "name": "Acme"}))
        text, _ = self.doctor(cwd=ws)
        self.assertIn("acme/acme-site", text)
        self.assertNotIn("demo-service", text)

    def test_the_cli_refuses_a_pass_from_a_client_workspace(self):
        ws = self.d / "clients" / "acme"
        ws.mkdir(parents=True)
        (ws / ".client.json").write_text(json.dumps({"slug": "acme", "name": "Acme"}))
        a = argparse.Namespace(once=True, dry_run=False, pretend_down=None, rdap=False, site=None, json=False)
        old, env = os.getcwd(), os.environ.pop("SITE_ADMIN", None)
        try:
            os.chdir(ws)
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                self.site.cmd_watch(a)
        finally:
            os.chdir(old)
            if env is not None:
                os.environ["SITE_ADMIN"] = env
        self.assertFalse(self.site.WATCH_FILE.exists())


class ProbeTests(WatchCase):
    def test_cloudflare_ranges(self):
        on = self.site.watch_on_cloudflare
        self.assertTrue(on("104.21.3.4"))
        self.assertTrue(on("172.66.44.1"))
        self.assertFalse(on("93.184.216.34"))
        self.assertFalse(on("not-an-ip"))

    def test_a_preview_url_is_fetched_at_its_own_path(self):
        seen = []
        self.site.watch_fetch = lambda host, ip, path="/", hops=3: (seen.append((host, ip, path)) or (200, PREVIEW, 80, ""))
        t = {"key": "preview/x", "slug": "x", "host": "patchlamp-previews.pages.dev",
             "url": "https://patchlamp-previews.pages.dev/x/", "markers": list(self.site.PREVIEW_MARKERS)}
        c = self.site.watch_probe(t)
        self.assertTrue(c["ok"])
        self.assertEqual(seen, [("patchlamp-previews.pages.dev", "172.66.47.9", "/x/")])


if __name__ == "__main__":
    unittest.main()
