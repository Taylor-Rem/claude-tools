"""`site mail` (ROADMAP B75, plan ~/projects/plans/34-email.md § Split "toolbelt + template")
against one local server that plays Cloudflare, Resend and patchlamp.com — no network.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

What's pinned: the templates' Contact link filled (and left out cleanly with no address);
`site new`'s {{MAIL}} from the app's mailbox or the default; `site mail` PUTs the default
when the app has none, rewrites the data-mail links, commits, pushes and publishes; the
--dry-run writes nothing anywhere; the app without mail routes is one plain sentence and
a non-zero exit; --domain refuses an apex with MX and a zone the token can't see, and
otherwise creates the Resend domain with receiving on, writes its records, verifies and
PUTs exactly {address, kind, domains}; `mail platform` prints the Porkbun records; the
doctor lines; `connections` shows the gmail.send grant.
"""

import argparse
import contextlib
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
SITES = ROOT / "templates" / "sites"
TYPES = sorted(d.name for d in SITES.iterdir() if d.is_dir() and not d.name.startswith("_"))
ROUTE_404 = {"message": "The route internal/relay/mail/status could not be found."}


def load_site():
    loader = importlib.machinery.SourceFileLoader("site_tool_mail", str(ROOT / "bin" / "site"))
    spec = importlib.util.spec_from_loader("site_tool_mail", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


def resend_records(domain_is_sub=False):
    sfx = ".mail" if domain_is_sub else ""
    return [
        {"record": "DKIM", "name": f"resend._domainkey{sfx}", "type": "TXT", "value": "p=MIGfFAKEKEY", "ttl": "Auto", "status": "not_started"},
        {"record": "SPF", "name": f"send{sfx}", "type": "CNAME", "value": "send.forge.rmta.net", "ttl": "Auto", "status": "not_started"},
        {"record": "Receiving", "name": "mail" if domain_is_sub else "@", "type": "MX",
         "value": "inbound-smtp.us-east-1.amazonaws.com", "priority": 10, "ttl": "Auto", "status": "not_started"},
    ]


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

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode() or "null") if n else None

    def _route(self, method):
        S = self.S
        u = urlparse(self.path)
        p, q = u.path, parse_qs(u.query)
        body = self._body() if method in ("POST", "PUT", "PATCH") else None
        S["calls"].append((method, p, body))
        # ---- patchlamp.com
        if p.startswith("/internal/relay/"):
            if S.get("app_missing"):
                return self._send(404, ROUTE_404)
            if p == "/internal/relay/mail/status":
                return self._send(200, S["status"])
            if p.endswith("/mailbox"):
                if method == "GET":
                    return self._send(200, {"mailbox": S.get("mailbox")})
                S["mailbox"] = {**(S.get("mailbox") or {}), **body, "status": "active"}
                return self._send(200, {"mailbox": S["mailbox"]})
            if p.endswith("/connections"):
                return self._send(200, {"project": "acme", "google": {"configured": True, "granted": True},
                                        "connections": S.get("connections", [])})
            return self._send(404, {"error": "no such thing"})
        # ---- Cloudflare
        if p.startswith("/zones"):
            if p == "/zones":
                zones = S.get("zones", [])
                if "name" in q:
                    zones = [z for z in zones if z["name"] == q["name"][0]]
                return self._send(200, {"success": True, "result": zones})
            if p.endswith("/dns_records"):
                if method == "POST":
                    S["dns"].append(body)
                    return self._send(200, {"success": True, "result": {"id": "r1", **body}})
                rows = [r for r in S["dns"] if r["name"] == q["name"][0] and (not q.get("type") or r["type"] == q["type"][0])]
                return self._send(200, {"success": True, "result": [{**r, "content": r["content"]} for r in rows]})
        # ---- Resend
        if p == "/domains":
            if method == "POST":
                if S.get("resend_full"):
                    return self._send(403, {"name": "validation_error", "message": "You have reached your domain limit"})
                d = {"id": "dom-1", "name": body["name"], "status": "not_started", "capabilities": body.get("capabilities"),
                     "records": resend_records(body["name"].startswith("mail."))}
                S["resend"].append(d)
                return self._send(201, {"id": d["id"], "name": d["name"]})
            return self._send(200, {"data": [{k: v for k, v in d.items() if k != "records"} for d in S["resend"]]})
        if p.startswith("/domains/"):
            did = p.split("/")[2]
            d = next((d for d in S["resend"] if d["id"] == did), None)
            if d is None:
                return self._send(404, {"message": "not found"})
            if p.endswith("/verify"):
                d["status"] = "verified"
                return self._send(200, {"object": "domain", "id": did})
            if method == "PATCH":
                d["capabilities"] = {**(d.get("capabilities") or {}), **body["capabilities"]}
                return self._send(200, {"id": did})
            return self._send(200, d)
        self._send(404, {"message": "unknown"})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")

    def do_PATCH(self):
        self._route("PATCH")


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class SiteMailTest(unittest.TestCase):
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
        root = Path(self.tmp.name)
        self.envfile = root / "env"
        self.envfile.write_text("PATCHLAMP_RELAY_SHARED_SECRET=relay-secret\nRESEND_API_KEY=re_FAKE\n"
                                "CLOUDFLARE_API_TOKEN=cf-token\nCLOUDFLARE_ACCOUNT_ID=acct-1\n")
        (root / "sites.json").write_text(json.dumps({"acme": {"acme-site": {"host": "cloudflare", "project": "acme-site"}}}))
        self.ws = root / "acme"
        (self.ws / "repos").mkdir(parents=True)
        (self.ws / ".client.json").write_text(json.dumps({"slug": "acme", "name": "Acme Pools"}))
        # the site: the service template's home page as `site new` fills it, pushed to a bare remote
        remote = root / "remote.git"
        git("init", "-q", "--bare", "-b", "main", str(remote), cwd=root)
        self.repo = self.ws / "repos" / "acme-site"
        self.repo.mkdir()
        self.site = load_site()
        html = self.site.fill_mail((SITES / "service" / "index.html").read_text().replace("{{NAME}}", "Acme Pools"),
                                   "old@mail.patchlamp.com")
        (self.repo / "index.html").write_text(html)
        git("init", "-q", "-b", "main", cwd=self.repo)
        git("add", "-A", cwd=self.repo)
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "site", cwd=self.repo)
        git("remote", "add", "origin", str(remote), cwd=self.repo)
        git("push", "-q", "-u", "origin", "main", cwd=self.repo)

        self.site.ENV_FILE = self.envfile
        self.site.REGISTRY = root / "sites.json"
        self.site.CF_API = self.base
        self.site.RESEND_API = self.base
        self.published = []
        self.site.cmd_publish = lambda a: self.published.append((a.name, a.dry_run))
        self.dns = {}
        self.site.dig = lambda rtype, name: self.dns.get((rtype, name), [])
        Fake.S = {"calls": [], "dns": [], "resend": [], "zones": [], "mailbox": None,
                  "status": {"resend_key": "ok", "webhook_secret": True, "mail_domain": "mail.patchlamp.com",
                             "receiving": True, "gmail_send_scope": True, "mailboxes": 7, "pending": 0}}
        self.cwd = os.getcwd()
        os.chdir(self.ws)
        self.env = mock.patch.dict(os.environ, {"PATCHLAMP_URL": self.base, "SITE_MAIL_VERIFY_SECONDS": "1"})
        self.env.start()
        os.environ.pop("SITE_ADMIN", None)

    def tearDown(self):
        self.env.stop()
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def run_mail(self, *argv, admin=False):
        a = argparse.Namespace(name=None, domain=None, check=False, dry_run=False)
        it = iter(argv)
        for x in it:
            if x == "--domain":
                a.domain = next(it)
            elif x == "--check":
                a.check = True
            elif x == "--dry-run":
                a.dry_run = True
            else:
                a.name = x
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.dict(os.environ, {"SITE_ADMIN": "1"} if admin else {}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.site.cmd_mail(a)
            except SystemExit as exc:
                code = exc.code or 0
        return code, out.getvalue(), err.getvalue()

    def writes(self):
        return [c for c in Fake.S["calls"] if c[0] != "GET"]

    # ---------------------------------------------------------------- the templates

    def test_every_template_carries_the_link_and_fills_it(self):
        for t in TYPES:
            html = (SITES / t / "index.html").read_text()
            self.assertIn('data-mail', html, f"{t}: no data-mail link in the Contact block")
            self.assertIn('href="mailto:{{MAIL}}">{{MAIL}}</a>', html, t)
            filled = self.site.fill_mail(html, "acme@mail.patchlamp.com")
            self.assertNotIn("{{MAIL}}", filled, t)
            self.assertIn('href="mailto:acme@mail.patchlamp.com">acme@mail.patchlamp.com</a>', filled, t)
            self.assertNotIn("hello@example.com", filled, t)

    def test_no_address_leaves_the_line_out_cleanly(self):
        for t in TYPES:
            empty = self.site.fill_mail((SITES / t / "index.html").read_text(), "")
            self.assertNotIn("MAIL", empty, t)
            self.assertNotIn("data-mail", empty, t)
            self.assertNotIn("mailto:", empty, t)
            self.assertNotRegex(empty, r"<(li|p)>\s*</\1>", t)
            self.assertIn("</html>", empty, t)

    def test_doctor_knows_the_placeholder(self):
        src = (ROOT / "bin" / "site").read_text()
        self.assertIn('"TAGLINE", "MAIL"}', src)

    def test_site_new_fills_from_the_app_else_the_default(self):
        Fake.S["mailbox"] = {"address": "hello@acme.com", "kind": "domain", "status": "active"}
        self.assertEqual(self.site.mail_for_new_site("acme"), "hello@acme.com")
        Fake.S["mailbox"] = None
        self.assertEqual(self.site.mail_for_new_site("acme"), "acme@mail.patchlamp.com")
        Fake.S["mailbox"] = {"address": "acme@mail.patchlamp.com", "status": "off"}
        self.assertEqual(self.site.mail_for_new_site("acme"), "")
        Fake.S["app_missing"] = True
        self.assertEqual(self.site.mail_for_new_site("acme"), "acme@mail.patchlamp.com")

    # ---------------------------------------------------------------- site mail

    def test_site_mail_puts_the_default_rewrites_commits_and_publishes(self):
        code, out, err = self.run_mail()
        self.assertEqual(code, 0, out + err)
        puts = [c for c in Fake.S["calls"] if c[0] == "PUT"]
        self.assertEqual(puts, [("PUT", "/internal/relay/projects/acme/mailbox",
                                 {"address": "acme@mail.patchlamp.com", "kind": "platform"})])
        html = (self.repo / "index.html").read_text()
        self.assertIn('<a data-mail href="mailto:acme@mail.patchlamp.com">acme@mail.patchlamp.com</a>', html)
        self.assertNotIn("old@mail.patchlamp.com", html)
        self.assertEqual(git("log", "-1", "--format=%s", cwd=self.repo), "Contact: acme@mail.patchlamp.com")
        self.assertEqual(git("status", "--porcelain", cwd=self.repo), "")
        self.assertEqual(git("log", "--oneline", "@{u}..", cwd=self.repo), "", "pushed")
        self.assertEqual(self.published, [("acme-site", False)])
        # again: nothing to do, nothing written
        Fake.S["calls"].clear()
        code, out, _ = self.run_mail("acme-site")
        self.assertEqual(code, 0)
        self.assertIn("already say acme@mail.patchlamp.com", out)
        self.assertEqual(self.writes(), [])
        self.assertEqual(len(self.published), 1)

    def test_check_says_and_changes_nothing(self):
        Fake.S["mailbox"] = {"address": "acme@mail.patchlamp.com", "kind": "platform", "status": "active"}
        code, out, _ = self.run_mail("--check")
        self.assertEqual(code, 1)
        self.assertIn("says old@mail.patchlamp.com", out)
        self.assertIn("old@mail.patchlamp.com", (self.repo / "index.html").read_text())
        self.assertEqual(self.writes(), [])

    def test_dry_run_writes_nothing(self):
        before = (self.repo / "index.html").read_text()
        head = git("rev-parse", "HEAD", cwd=self.repo)
        code, out, err = self.run_mail("--dry-run")
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.writes(), [], "no PUT, no POST in a dry run")
        self.assertIn("would PUT /internal/relay/projects/acme/mailbox", out)
        self.assertEqual((self.repo / "index.html").read_text(), before)
        self.assertEqual(git("rev-parse", "HEAD", cwd=self.repo), head)
        self.assertEqual(self.published, [("acme-site", True)])
        self.assertIn("dry run: nothing changed", out)

    def test_the_app_without_mail_is_one_plain_sentence(self):
        Fake.S["app_missing"] = True
        code, out, err = self.run_mail()
        self.assertNotEqual(code, 0)
        self.assertIn("the app doesn't have mail yet", err)
        self.assertNotIn("Traceback", err + out)
        self.assertEqual(self.writes(), [])
        # and as a real process: no traceback either
        r = subprocess.run([str(ROOT / "bin" / "site"), "mail", "--dry-run"], cwd=self.ws, capture_output=True, text=True,
                           env={**os.environ, "CLAUDE_TOOLS_ENV": str(self.envfile), "PATCHLAMP_URL": self.base})
        self.assertEqual(r.returncode, 1)
        self.assertIn("site: the app doesn't have mail yet", r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_a_site_without_the_link_is_told_how(self):
        (self.repo / "index.html").write_text("<html><body><p>Contact: call us</p></body></html>\n")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "old site", cwd=self.repo)
        Fake.S["mailbox"] = {"address": "acme@mail.patchlamp.com", "status": "active"}
        code, out, _ = self.run_mail()
        self.assertEqual(code, 0)
        self.assertIn("no data-mail link", out)
        self.assertEqual(self.published, [])

    # ---------------------------------------------------------------- --domain

    def test_domain_is_taylors(self):
        code, _, err = self.run_mail("--domain", "acme.com")
        self.assertEqual(code, 1)
        self.assertIn("Taylor's work", err)
        self.assertEqual(Fake.S["calls"], [])

    def test_domain_zone_not_visible(self):
        Fake.S["zones"] = [{"id": "z-bg", "name": "bleugrave.com"}]
        code, _, err = self.run_mail("--domain", "acme.com", admin=True)
        self.assertEqual(code, 1)
        self.assertIn("acme.com isn't a zone our Cloudflare token can see (it sees: bleugrave.com)", err)
        self.assertEqual(self.writes(), [])

    def test_domain_with_mail_at_the_apex_is_refused(self):
        Fake.S["zones"] = [{"id": "z1", "name": "acme.com"}]
        Fake.S["dns"] = [{"type": "MX", "name": "acme.com", "content": "aspmx.l.google.com", "priority": 1}]
        code, _, err = self.run_mail("--domain", "acme.com", admin=True)
        self.assertEqual(code, 1)
        self.assertIn("they have mail there — the forward", err)
        self.assertEqual(self.writes(), [])
        # an MX only public DNS knows about (the zone isn't live on Cloudflare) refuses the same
        Fake.S["dns"] = []
        self.dns[("MX", "acme.com")] = ["10 mx.zoho.com."]
        code, _, err = self.run_mail("--domain", "acme.com", admin=True)
        self.assertIn("they have mail there — the forward", err)
        self.assertEqual(self.writes(), [])

    def test_domain_creates_writes_verifies_then_puts(self):
        Fake.S["zones"] = [{"id": "z1", "name": "acme.com"}]
        code, out, err = self.run_mail("--domain", "acme.com", admin=True)
        self.assertEqual(code, 0, out + err)
        created = [c for c in Fake.S["calls"] if c[:2] == ("POST", "/domains")]
        self.assertEqual(created[0][2], {"name": "acme.com", "capabilities": {"sending": "enabled", "receiving": "enabled"}})
        self.assertEqual(Fake.S["dns"], [
            {"type": "TXT", "name": "resend._domainkey.acme.com", "content": "p=MIGfFAKEKEY", "ttl": 1},
            {"type": "CNAME", "name": "send.acme.com", "content": "send.forge.rmta.net", "ttl": 1, "proxied": False},
            {"type": "MX", "name": "acme.com", "content": "inbound-smtp.us-east-1.amazonaws.com", "ttl": 1, "priority": 10},
        ])
        self.assertIn(("POST", "/domains/dom-1/verify", {}), Fake.S["calls"])
        puts = [c for c in Fake.S["calls"] if c[0] == "PUT"]
        self.assertEqual(puts, [("PUT", "/internal/relay/projects/acme/mailbox",
                                 {"address": "hello@acme.com", "kind": "domain", "domains": ["acme.com"]})])
        self.assertIn('href="mailto:hello@acme.com">hello@acme.com</a>', (self.repo / "index.html").read_text())
        self.assertEqual(self.published, [("acme-site", False)])
        # run again: the records are there, nothing is written twice
        n = len(Fake.S["dns"])
        code, out, _ = self.run_mail("--domain", "acme.com", admin=True)
        self.assertEqual(code, 0)
        self.assertEqual(len(Fake.S["dns"]), n)
        self.assertIn("already there", out)

    def test_domain_dry_run_writes_nothing(self):
        Fake.S["zones"] = [{"id": "z1", "name": "acme.com"}]
        code, out, err = self.run_mail("--domain", "acme.com", "--dry-run", admin=True)
        self.assertEqual(code, 0, out + err)
        self.assertEqual(self.writes(), [])
        self.assertEqual(Fake.S["dns"], [])
        self.assertIn("would create the Resend domain acme.com", out)
        self.assertIn('"address": "hello@acme.com", "kind": "domain", "domains": ["acme.com"]', out)

    def test_domain_when_resend_is_full(self):
        Fake.S["zones"] = [{"id": "z1", "name": "acme.com"}]
        Fake.S["resend_full"] = True
        code, _, err = self.run_mail("--domain", "acme.com", admin=True)
        self.assertEqual(code, 1)
        self.assertIn("free plan holds 3 domains", err)
        self.assertEqual(Fake.S["dns"], [])
        self.assertEqual([c for c in Fake.S["calls"] if c[0] == "PUT"], [])

    # ---------------------------------------------------------------- platform + doctor

    def test_platform_prints_the_porkbun_records(self):
        code, _, err = self.run_mail("platform")
        self.assertEqual(code, 1)
        self.assertIn("Taylor's work", err)
        code, out, err = self.run_mail("platform", admin=True)
        self.assertEqual(code, 0, out + err)
        created = [c for c in Fake.S["calls"] if c[:2] == ("POST", "/domains")]
        self.assertEqual(created[0][2]["name"], "mail.patchlamp.com")
        self.assertEqual(created[0][2]["capabilities"], {"sending": "enabled", "receiving": "enabled"})
        self.assertRegex(out, r"TXT\s+resend\._domainkey\.mail\s+p=MIGfFAKEKEY")
        self.assertRegex(out, r"CNAME\s+send\.mail\s+send\.forge\.rmta\.net")
        self.assertRegex(out, r"MX\s+mail\s+inbound-smtp\.us-east-1\.amazonaws\.com\s+priority 10")
        self.assertIn("Leave the apex MX", out)
        self.assertEqual(Fake.S["dns"], [], "patchlamp.com is at Porkbun: nothing is written")
        # --check: DNS doesn't answer yet
        code, out, _ = self.run_mail("platform", "--check", admin=True)
        self.assertEqual(code, 1)
        self.assertIn("NOT in DNS yet", out)
        # --check: DNS answers every record, Resend verifies
        self.dns = {("TXT", "resend._domainkey.mail.patchlamp.com"): ['"p=MIGfFAKEKEY"'],
                    ("CNAME", "send.mail.patchlamp.com"): ["send.forge.rmta.net."],
                    ("MX", "mail.patchlamp.com"): ["10 inbound-smtp.us-east-1.amazonaws.com."]}
        code, out, _ = self.run_mail("platform", "--check", admin=True)
        self.assertEqual(code, 0, out)
        self.assertIn("verified", out)

    def test_platform_dry_run_creates_nothing(self):
        code, out, _ = self.run_mail("platform", "--dry-run", admin=True)
        self.assertEqual(code, 0)
        self.assertEqual(self.writes(), [])
        self.assertIn("would create the Resend domain mail.patchlamp.com", out)

    def doctor(self, strict):
        lines = []
        ok = self.site.mail_doctor(lines.append, lambda m: lines.append(f"  FAIL {m}"), strict=strict)
        return ok, "\n".join(lines)

    def test_doctor_lines(self):
        Fake.S["mailbox"] = {"address": "acme@mail.patchlamp.com", "status": "active", "send_via": "resend"}
        self.dns[("MX", "mail.patchlamp.com")] = ["10 inbound-smtp.us-east-1.amazonaws.com."]
        ok, text = self.doctor(strict=True)
        self.assertFalse(ok, text)
        self.assertIn("app: resend key ok", text)
        self.assertIn("app: webhook secret set", text)
        self.assertIn("app: receiving on mail.patchlamp.com: yes", text)
        self.assertIn("7 mailbox(es), 0 mail(s) pending", text)
        self.assertIn("DNS: MX mail.patchlamp.com 10 inbound-smtp", text)
        self.assertIn("mailbox: acme@mail.patchlamp.com", text)
        self.assertIn("FAIL repos/acme-site: the Contact links say old@mail.patchlamp.com", text)
        self.run_mail()
        ok, text = self.doctor(strict=True)
        self.assertTrue(ok, text)
        self.assertIn("repos/acme-site: the Contact links say acme@mail.patchlamp.com", text)

    def test_doctor_before_the_app_has_mail(self):
        Fake.S["app_missing"] = True
        ok, text = self.doctor(strict=True)
        self.assertFalse(ok)
        self.assertIn("FAIL the app doesn't have mail yet", text)
        ok, text = self.doctor(strict=False)
        self.assertTrue(ok, "in `site doctor` it's a note until the app ships")
        self.assertIn("note: the app doesn't have mail yet", text)
        Fake.S["app_missing"] = False
        Fake.S["status"] = {**Fake.S["status"], "resend_key": "error: restricted key", "webhook_secret": False}
        ok, text = self.doctor(strict=False)
        self.assertFalse(ok)
        self.assertIn("FAIL app: resend key error: restricted key", text)
        self.assertIn("MISSING (RESEND_WEBHOOK_SECRET in Laravel Cloud)", text)

    # ---------------------------------------------------------------- connections

    def test_connections_shows_the_gmail_send_grant(self):
        Fake.S["connections"] = [
            {"id": 12, "kind": "google-mail", "status": "connected", "connected_at": "2026-10-01T15:00:00Z",
             "meta": {"email": "owner@gmail.com", "scopes": ["openid", "email", "https://www.googleapis.com/auth/gmail.send"]}},
        ]
        env = {**os.environ, "CLAUDE_TOOLS_ENV": str(self.envfile), "PATCHLAMP_URL": self.base}
        r = subprocess.run([str(ROOT / "bin" / "connections")], cwd=self.ws, capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("google-mail (gmail.send) connected  owner@gmail.com", r.stdout)
        r = subprocess.run([str(ROOT / "bin" / "connections"), "google", "show"], cwd=self.ws, capture_output=True,
                           text=True, env=env)
        self.assertIn("acme: google-mail (gmail.send) owner@gmail.com — connected", r.stdout)


if __name__ == "__main__":
    unittest.main()
