"""`site domain`, the free address and the 90-day forward (ROADMAP B58, plan
~/projects/plans/27-domain-without-taylor.md § 7) against one local server that plays
Cloudflare's zones, DNS and Pages APIs — no network, no real zone.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

What's pinned: the zone made once and reused, apex + www attached and their CNAMEs written in
it, the two nameservers printed, no SITE_ADMIN and no FORWARD-TO-TAYLOR; `--records` prints
ALIAS/CNAME and makes no zone, and the tool takes that path by itself for a subdomain, for a
domain with mail and when the zone can't be made (saying why); the picture chosen by NS, the help
page alone when there is no picture; a demo refuses, outside a workspace refuses, the GitHub
Pages path still wants SITE_ADMIN; `--dry-run` makes no write; the free address on a fake
patchlamp.site zone (slug first, then the site's name; missing zone = pages.dev, said plainly),
`site new` born on it, Codex's site-live sentence word for word; `retire --forward` keeps the
address as a 301 for 90 days and the sweep ends it; a plain retire deletes the address's record;
the doctor's zone line.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import argparse
import contextlib
import datetime
import importlib.machinery
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
NS = ["ada.ns.cloudflare.com", "bob.ns.cloudflare.com"]


def load_site():
    loader = importlib.machinery.SourceFileLoader("site_tool_domain", str(ROOT / "bin" / "site"))
    spec = importlib.util.spec_from_loader("site_tool_domain", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Fake(BaseHTTPRequestHandler):
    S = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def ok(self, result):
        return self._send(200, {"success": True, "errors": [], "result": result})

    def _route(self, method):
        S = self.S
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode() or "null") if n else None
        S["calls"].append((method, p, body))
        parts = p.strip("/").split("/")
        if p == "/zones":
            if method == "POST":
                if S.get("zone_refused"):
                    return self._send(403, {"success": False, "errors": [{"code": 9109, "message": "Unauthorized to access requested resource"}]})
                z = {"id": f"z{len(S['zones']) + 1}", "name": body["name"], "status": "pending", "name_servers": NS}
                S["zones"].append(z)
                return self.ok(z)
            if S.get("zones_unlistable"):
                return self._send(403, {"success": False, "errors": [{"code": 9109, "message": "Unauthorized"}]})
            zones = [z for z in S["zones"] if "name" not in q or z["name"] == q["name"][0]]
            return self.ok(zones)
        if parts[0] == "zones" and len(parts) == 2:
            return self.ok(next(z for z in S["zones"] if z["id"] == parts[1]))
        if parts[0] == "zones" and parts[2] == "dns_records":
            zid = parts[1]
            if method == "POST":
                rec = {"id": f"r{len(S['dns']) + 1}", "zone": zid, **body}
                S["dns"].append(rec)
                return self.ok(rec)
            if method == "PUT":
                rec = next(r for r in S["dns"] if r["id"] == parts[3])
                rec.update(body)
                return self.ok(rec)
            if method == "DELETE":
                S["dns"] = [r for r in S["dns"] if r["id"] != parts[3]]
                return self.ok({"id": parts[3]})
            return self.ok([r for r in S["dns"] if r["zone"] == zid and r["name"] == q["name"][0]])
        if parts[:3] == ["accounts", "acct-1", "pages"]:
            proj = parts[4] if len(parts) > 4 else None
            if len(parts) == 5:
                if method == "DELETE":
                    S["projects"].pop(proj, None)
                    return self.ok(None)
                if proj not in S["projects"]:
                    return self._send(404, {"success": False, "errors": [{"code": 8000007, "message": "not found"}]})
                return self.ok({"name": proj, "subdomain": f"{proj}.pages.dev"})
            if len(parts) >= 6 and parts[5] == "domains":
                doms = S["projects"].setdefault(proj, [])
                if method == "POST":
                    doms.append(body["name"])
                    return self.ok({"name": body["name"], "status": "pending"})
                if method == "DELETE":
                    S["projects"][proj] = [d for d in doms if d != parts[6]]
                    return self.ok(None)
                return self.ok([{"name": d, "status": "active"} for d in doms])
            if p.endswith("/pages/projects"):
                return self.ok([{"name": k} for k in S["projects"]])
        self._send(404, {"success": False, "errors": [{"code": 404, "message": "unknown " + p}]})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_DELETE(self):
        self._route("DELETE")


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class SiteDomainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.root = Path(self.tmp.name)
        self.envfile = root / "env"
        self.envfile.write_text("CLOUDFLARE_API_TOKEN=cf-token\nCLOUDFLARE_ACCOUNT_ID=acct-1\nSITE_ORG=patchlamp-sites\n")
        self.registry = root / "sites.json"
        self.registry.write_text(json.dumps({"acme": {"acme-site": {"host": "cloudflare", "project": "acme-site"}}}))
        self.ws = root / "acme"
        (self.ws / "repos").mkdir(parents=True)
        (self.ws / ".client.json").write_text(json.dumps({"slug": "acme", "name": "Acme Pools",
                                                          "live_url": "https://acme-site.pages.dev/"}))
        remote = root / "remote.git"
        git("init", "-q", "--bare", "-b", "main", str(remote), cwd=root)
        self.repo = self.ws / "repos" / "acme-site"
        self.repo.mkdir()
        (self.repo / "index.html").write_text("<html><head><title>Acme</title></head><body>Acme Pools</body></html>\n")
        (self.repo / "CLAUDE.md").write_text("Live at https://acme-site.pages.dev/\n")
        git("init", "-q", "-b", "main", cwd=self.repo)
        git("add", "-A", cwd=self.repo)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "site", cwd=self.repo)
        git("remote", "add", "origin", str(remote), cwd=self.repo)
        git("push", "-q", "-u", "origin", "main", cwd=self.repo)

        s = self.site = load_site()
        s.ENV_FILE = self.envfile
        s.REGISTRY = self.registry
        s.CF_API = self.base
        s.DNS_PICTURES = root / "dns"
        s.ADDRESS_WAIT = 0
        self.published, self.deployed, self.restamped = [], [], []
        s.cmd_publish = lambda a: self.published.append(a.name)
        s.restamp = lambda ws, meta: self.restamped.append(meta.get("live_url"))
        self.dns = {}
        s.dig = lambda rtype, name: self.dns.get((rtype, name), [])
        s.doh = lambda rtype, name: []

        def fake_wrangler(*args, env_extra=None, cwd=None):
            pub = Path(args[2])
            self.deployed.append({"args": args, "files": {f.name: f.read_text() for f in pub.iterdir()}})
            return 0, "Deployment complete"
        s.wrangler = fake_wrangler
        s.http_status = lambda url, timeout=10: (200, "")
        Fake.S = {"calls": [], "zones": [], "dns": [], "projects": {"acme-site": []}}
        self.cwd = os.getcwd()
        os.chdir(self.ws)
        self.env = mock.patch.dict(os.environ, {"CLAUDE_TOOLS_ENV": str(self.envfile)})
        self.env.start()
        for k in ("SITE_ADMIN", "RELAY_ROLE"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()
        os.chdir(self.cwd)
        self.tmp.cleanup()

    # ---------------------------------------------------------------- helpers

    def call(self, fn, ns, env=None):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.dict(os.environ, env or {}), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                fn(argparse.Namespace(**ns))
            except SystemExit as exc:
                code = exc.code or 0
        return code, out.getvalue(), err.getvalue()

    def domain(self, *argv, env=None):
        ns = {"name": "acme-site", "domain": None, "records": False, "picture": False, "https": False, "dry_run": False}
        pos = [x for x in argv if not x.startswith("--")]
        if pos:
            ns["domain"] = pos[0]
        for flag in ("records", "picture", "dry_run"):
            if "--" + flag.replace("_", "-") in argv:
                ns[flag] = True
        return self.call(self.site.cmd_domain, ns, env)

    def writes(self):
        return [c for c in Fake.S["calls"] if c[0] != "GET"]

    def reg(self):
        return json.loads(self.registry.read_text())

    def brand_zone(self, status="active"):
        Fake.S["zones"].append({"id": "zb", "name": "patchlamp.site", "status": status, "name_servers": NS})

    # ---------------------------------------------------------------- site domain: the nameserver move

    def test_the_default_makes_the_zone_once_attaches_and_prints_the_nameservers(self):
        code, out, err = self.domain("example.com")
        self.assertEqual(code, 0, out + err)
        posts = [c for c in Fake.S["calls"] if c[:2] == ("POST", "/zones")]
        self.assertEqual(posts, [("POST", "/zones", {"name": "example.com", "account": {"id": "acct-1"}, "type": "full"})])
        self.assertEqual(Fake.S["projects"]["acme-site"], ["example.com", "www.example.com"])
        cnames = {(r["name"], r["content"], r["proxied"]) for r in Fake.S["dns"]}
        self.assertEqual(cnames, {("example.com", "acme-site.pages.dev", True), ("www.example.com", "acme-site.pages.dev", True)})
        for n in NS:
            self.assertIn(f"  {n}", out)
        self.assertIn("set example.com's nameservers to these two", out)
        self.assertNotIn("FORWARD-TO-TAYLOR", out + err)
        self.assertNotIn("Taylor", out + err)
        row = self.reg()["acme"]["acme-site"]
        self.assertEqual(row["domains"], ["example.com", "www.example.com"])
        self.assertEqual(row["zone"]["id"], "z1")
        self.assertEqual(row["zone"]["name_servers"], NS)
        self.assertEqual(json.loads((self.ws / ".client.json").read_text())["live_url"], "https://example.com/")
        self.assertIn('<link rel="canonical" href="https://example.com/">', (self.repo / "index.html").read_text())
        self.assertEqual(self.published, ["acme-site"])
        # again: the zone is reused, nothing attached twice
        Fake.S["calls"].clear()
        code, out, _ = self.domain("example.com")
        self.assertEqual(code, 0)
        self.assertNotIn(("POST", "/zones"), [c[:2] for c in Fake.S["calls"]])
        self.assertIn("already in the account", out)
        self.assertEqual(Fake.S["projects"]["acme-site"], ["example.com", "www.example.com"])
        self.assertEqual(len(Fake.S["dns"]), 2)

    def test_status_shows_the_zone_and_the_domains(self):
        self.domain("example.com")
        code, out, _ = self.domain()
        self.assertEqual(code, 0)
        self.assertIn("zone example.com: pending", out)
        self.assertIn(NS[0], out)
        self.assertIn("www.example.com", out)

    def test_records_prints_alias_and_cname_and_makes_no_zone(self):
        code, out, err = self.domain("example.com", "--records")
        self.assertEqual(code, 0, out + err)
        self.assertNotIn(("POST", "/zones"), [c[:2] for c in Fake.S["calls"]])
        self.assertIn("ALIAS  @      acme-site.pages.dev", out)
        self.assertIn("CNAME  www    acme-site.pages.dev", out)
        self.assertEqual(Fake.S["projects"]["acme-site"], ["example.com", "www.example.com"])
        self.assertNotIn("zone", self.reg()["acme"]["acme-site"])

    def test_a_domain_with_mail_gets_the_records_and_the_reason(self):
        self.dns[("MX", "example.com")] = ["10 mx.zoho.com."]
        code, out, _ = self.domain("example.com")
        self.assertEqual(code, 0)
        self.assertIn("receives mail (mx.zoho.com)", out)
        self.assertNotIn(("POST", "/zones"), [c[:2] for c in Fake.S["calls"]])
        self.assertIn("ALIAS  @", out)

    def test_a_subdomain_gets_one_cname(self):
        code, out, _ = self.domain("shop.example.com")
        self.assertEqual(code, 0)
        self.assertIn("is a subdomain", out)
        self.assertIn("CNAME  shop   acme-site.pages.dev", out)
        self.assertEqual(Fake.S["projects"]["acme-site"], ["shop.example.com"])

    def test_a_zone_the_token_cant_make_falls_back_and_says_why(self):
        Fake.S["zone_refused"] = True
        code, out, err = self.domain("example.com")
        self.assertEqual(code, 0, out + err)
        self.assertIn("the token can't create zones yet (it needs Zone · Zone · Edit", out)
        self.assertIn("ALIAS  @      acme-site.pages.dev", out)
        self.assertEqual(Fake.S["projects"]["acme-site"], ["example.com", "www.example.com"])

    def test_the_picture_is_chosen_by_the_nameservers(self):
        self.dns[("NS", "example.com")] = ["ns51.domaincontrol.com.", "ns52.domaincontrol.com."]
        self.site.DNS_PICTURES.mkdir()
        (self.site.DNS_PICTURES / "godaddy.png").write_bytes(b"png")
        code, out, _ = self.domain("example.com", "--picture")
        self.assertEqual(code, 0)
        self.assertIn("At GoDaddy, set example.com's nameservers", out)
        self.assertIn("replace the ones there: ns51.domaincontrol.com, ns52.domaincontrol.com", out)
        self.assertIn("https://www.godaddy.com/help/change-nameservers-for-my-domains-664", out)
        self.assertEqual(out.strip().splitlines()[-1], f"picture: {self.site.DNS_PICTURES / 'godaddy.png'}")

    def test_no_picture_means_the_help_page_alone(self):
        self.dns[("NS", "example.com")] = ["dns1.registrar-servers.com."]
        code, out, _ = self.domain("example.com", "--picture")
        self.assertEqual(code, 0)
        self.assertIn("registrar: Namecheap", out)
        self.assertIn("namecheap.com/support", out)
        self.assertEqual(out.strip().splitlines()[-1], "picture: (none for this registrar yet; send the help page)")
        self.assertEqual(self.site.registrar_of("x.example.org")[0], "generic")

    def test_dry_run_writes_nothing(self):
        before = (self.repo / "index.html").read_text()
        code, out, err = self.domain("example.com", "--dry-run")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.writes(), [])
        self.assertIn("would POST /zones", out)
        self.assertIn("would POST /pages/projects/acme-site/domains", out)
        self.assertIn("would write CNAME example.com -> acme-site.pages.dev", out)
        self.assertEqual((self.repo / "index.html").read_text(), before)
        self.assertNotIn("domains", self.reg()["acme"]["acme-site"])
        self.assertEqual(json.loads((self.ws / ".client.json").read_text())["live_url"], "https://acme-site.pages.dev/")

    def test_who_may_attach(self):
        # a demo refuses (strangers text those), unless Taylor
        meta = json.loads((self.ws / ".client.json").read_text())
        code, _, err = self.domain("example.com", env={"RELAY_ROLE": "demo"})
        self.assertNotEqual(code, 0)
        self.assertIn("demo site", err)
        self.assertEqual(self.writes(), [])
        # outside a workspace: refused before anything
        os.chdir(self.root)
        code, _, err = self.domain("example.com")
        self.assertNotEqual(code, 0)
        self.assertIn("not in a client workspace", err)
        os.chdir(self.ws)
        # a GitHub Pages site (not in the registry) is still Taylor's
        self.registry.write_text(json.dumps({}))
        code, _, err = self.domain("example.com")
        self.assertNotEqual(code, 0)
        self.assertIn("SITE_ADMIN=1", err)
        self.assertEqual(self.writes(), [])
        self.assertEqual(meta["slug"], "acme")

    def test_the_free_address_is_not_a_domain_to_attach(self):
        code, _, err = self.domain("acme.patchlamp.site")
        self.assertNotEqual(code, 0)
        self.assertIn("free address of ours", err)

    # ---------------------------------------------------------------- the free address

    def address(self, name=None, dry=False):
        return self.call(self.site.cmd_address, {"name": name, "dry_run": dry})

    def test_no_zone_yet_means_pages_dev_said_plainly(self):
        code, out, _ = self.address()
        self.assertEqual(code, 0)
        self.assertIn("free address: not yet — patchlamp.site is missing", out)
        self.assertEqual(self.writes(), [])
        Fake.S["zones_unlistable"] = True
        code, out, _ = self.address()
        self.assertIn("unreadable: the token can't list zones", out)
        Fake.S["zones_unlistable"] = False
        self.brand_zone("pending")
        code, out, _ = self.address()
        self.assertIn("patchlamp.site is pending", out)
        self.assertEqual(self.writes(), [])

    def test_site_address_attaches_slug_first_then_the_site_name(self):
        self.brand_zone()
        code, out, err = self.address()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(Fake.S["projects"]["acme-site"], ["acme.patchlamp.site"])
        self.assertEqual([(r["zone"], r["name"], r["content"]) for r in Fake.S["dns"]],
                         [("zb", "acme.patchlamp.site", "acme-site.pages.dev")])
        self.assertEqual(self.reg()["acme"]["acme-site"]["address"], "acme.patchlamp.site")
        self.assertEqual(json.loads((self.ws / ".client.json").read_text())["live_url"], "https://acme.patchlamp.site/")
        # a second site in the same workspace takes its own name
        reg = self.reg()
        reg["acme"]["x-site"] = {"host": "cloudflare", "project": "x-site"}
        self.registry.write_text(json.dumps(reg))
        Fake.S["projects"]["x-site"] = []
        self.assertEqual(self.site.address_label({"slug": "acme"}, "x-site"), "x-site")
        self.assertEqual(self.site.address_label({"slug": "acme"}, "acme-site"), "acme")

    def test_site_new_is_born_on_the_address(self):
        self.brand_zone()
        s = self.site
        s.owner = lambda: "patchlamp-sites"
        s.gh = lambda *a, **k: (1, "", "not found")
        s.token_source = lambda: ("gh", None)
        s.mail_for_new_site = lambda slug: ""
        (self.ws / ".client.json").write_text(json.dumps({"slug": "acme", "name": "Acme Pools", "sites": 3}))
        ns = {"name": "x-site", "template": None, "tagline": None, "primary": False, "no_wait": True,
              "dry_run": True, "gh_pages": False, "db": False, "owner": None}
        code, out, err = self.call(s.cmd_new, ns)
        self.assertEqual(code, 0, out + err)
        self.assertIn("expect https://x-site.patchlamp.site/", out)
        self.assertIn("would POST /pages/projects/x-site/domains", out)
        self.assertEqual(self.writes(), [])

    def test_the_site_live_text_is_codexs_sentence(self):
        self.assertEqual(self.site.live_text("https://highlandpool.patchlamp.site/"),
                         "Your site's live: https://highlandpool.patchlamp.site. Patched.")
        self.assertTrue(self.site.address_serving("https://x.patchlamp.site/", seconds=0))
        self.site.http_status = lambda url, timeout=10: (526, "")
        self.assertFalse(self.site.address_serving("https://x.patchlamp.site/", seconds=0))

    def test_publish_and_ls_name_the_address(self):
        reg = self.reg()
        reg["acme"]["acme-site"]["address"] = "acme.patchlamp.site"
        self.registry.write_text(json.dumps(reg))
        self.assertEqual(self.site.site_host(reg["acme"]["acme-site"], "acme-site"), "acme.patchlamp.site")
        code, out, _ = self.call(self.site.cmd_ls, {})
        self.assertIn("https://acme.patchlamp.site/", out)
        t = [x for x in self.site.watch_targets() if x["key"] == "acme/acme-site"][0]
        self.assertEqual((t["host"], t["domain"]), ("acme.patchlamp.site", None), "the address is watched, never RDAP'd")

    # ---------------------------------------------------------------- leaving: the 90-day forward

    def retire(self, forward=None, dry=False):
        return self.call(self.site.cmd_retire, {"name": "acme-site", "delete_repo": False, "keep_local": True,
                                               "dry_run": dry, "forward": forward}, env={"SITE_ADMIN": "1"})

    def test_retire_forward_keeps_the_address_as_a_redirect_for_90_days(self):
        self.brand_zone()
        self.address()
        Fake.S["projects"]["acme-site"].append("acmepools.com")
        code, out, err = self.retire(forward="https://acmepools.example/")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(Fake.S["projects"]["acme-site"], ["acme.patchlamp.site"], "the owner's domain detached, the address kept")
        files = self.deployed[-1]["files"]
        self.assertEqual(files["_redirects"], "/* https://acmepools.example/:splat 301\n")
        self.assertIn('url=https://acmepools.example/', files["index.html"])
        row = self.reg()["acme"]["acme-site"]
        until = (datetime.date.today() + datetime.timedelta(days=90)).isoformat()
        self.assertEqual(row["forward"], {"to": "https://acmepools.example/", "since": datetime.date.today().isoformat(),
                                          "until": until})
        self.assertIs(row["watch"], False)
        self.assertIn("acme-site", Fake.S["projects"], "the project stays while it forwards")
        self.assertEqual(len(Fake.S["dns"]), 1, "the address's record stays")
        # not due yet: the sweep leaves it
        self.assertEqual(self.site.forward_sweep(), 0)
        # day 91: the sweep ends it
        reg = self.reg()
        reg["acme"]["acme-site"]["forward"]["until"] = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        self.registry.write_text(json.dumps(reg))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(self.site.forward_sweep(), 1)
        self.assertNotIn("acme-site", Fake.S["projects"])
        self.assertEqual(Fake.S["dns"], [], "no record of ours left pointing at a pages.dev host")
        self.assertNotIn("acme", self.reg())

    def test_forward_sweep_by_hand_is_taylors(self):
        code, _, err = self.call(self.site.cmd_forward, {"sweep": True, "dry_run": False})
        self.assertNotEqual(code, 0)
        self.assertIn("SITE_ADMIN=1", err)

    def test_a_plain_retire_deletes_the_address_record(self):
        self.brand_zone()
        self.address()
        code, out, err = self.retire()
        self.assertEqual(code, 0, out + err)
        self.assertEqual(Fake.S["dns"], [])
        self.assertNotIn("acme-site", Fake.S["projects"])

    # ---------------------------------------------------------------- doctor

    def test_doctor_says_where_the_zone_is(self):
        s = self.site
        s.gh = lambda *a, **k: (0, "patch", "")
        s.gh_json = lambda *a, **k: {"login": "x"}
        s.watch_doctor = lambda fail: None
        s.mail_doctor = lambda say_, fail_: None
        s.handover_doctor = lambda say_, fail_: None
        s.site_visits = lambda *a, **k: None
        s.curl_header = lambda *a, **k: None
        os.chdir(self.root)
        code, out, _ = self.call(s.cmd_doctor, {})
        self.assertIn("zone patchlamp.site missing from the account", out)
        Fake.S["zones_unlistable"] = True
        code, out, _ = self.call(s.cmd_doctor, {})
        self.assertIn("the token can't list zones", out)
        Fake.S["zones_unlistable"] = False
        self.brand_zone()
        code, out, _ = self.call(s.cmd_doctor, {})
        self.assertIn("zone patchlamp.site present and active", out)


if __name__ == "__main__":
    unittest.main()
