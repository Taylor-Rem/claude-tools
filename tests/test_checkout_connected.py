"""The site side of Stripe Connect (ROADMAP B22, plan 16 § Contract C, D):
`site checkout --connected` against a fake patchlamp.com + Stripe and a
captured Cloudflare, and the catalog Functions under node.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

bin/site is loaded as a module so Cloudflare (`cf_api`) and the publish
are captured instead of called; patchlamp.com and Stripe are one local
HTTP server. The node half proves checkout.js puts Stripe-Account on the
session create when the site is connected (and nothing else changes), that
/api/catalog says how it's switched on, and that stripe-webhook.js — not
changed by B22 — verifies an event signed the way patchlamp.com's Connect
endpoint forwards it (§ Contract C), signed here by Python's hmac, not by
the code under test.
"""

import argparse
import contextlib
import io
import hashlib
import hmac
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SHELL = ROOT / "templates" / "sites" / "_shell"
CATALOG = ROOT / "templates" / "collections" / "catalog"
LIVE = "sk_live_FAKEplatformKEY000"
TEST = "sk_test_FAKEplatformKEY000"
ACCT = "acct_1TestOwner00001"
FWD = "0123456789abcdef0123456789abcdef"


def load_site():
    loader = importlib.machinery.SourceFileLoader("site_tool_connect", str(ROOT / "bin" / "site"))
    spec = importlib.util.spec_from_loader("site_tool_connect", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class Fake(BaseHTTPRequestHandler):
    state = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.state["sent"].append({"path": self.path, "account": self.headers.get("Stripe-Account"),
                                   "auth": self.headers.get("Authorization")})
        if self.path.startswith("/internal/relay/projects/"):
            return self._send(200, {"connections": self.state["rows"]})
        if self.path == "/v1/account":
            return self._send(200, {"id": ACCT, "charges_enabled": self.state.get("charges", True)})
        self._send(404, {})


def row(status="connected", livemode=False):
    r = {"id": 9, "kind": "stripe", "status": status, "external_id": ACCT, "stripe_account": ACCT,
         "livemode": livemode, "requirements": [] if status == "connected" else ["external_account"]}
    if status == "connected":
        r["env"] = {"STRIPE_CONNECTED_ACCOUNT": ACCT}
        r["webhook_secret"] = FWD
    return r


class SiteCheckoutConnectedTest(unittest.TestCase):
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
        (root / "env").write_text(f"STRIPE_KEY_PATCHLAMP={LIVE}\nSTRIPE_TEST_KEY={TEST}\n"
                                  f"PATCHLAMP_RELAY_SHARED_SECRET=relay-secret\nOWNER_KEY=sk_test_ownerKEY\n")
        (root / "sites.json").write_text(json.dumps({"demo-store": {"demo-store": {
            "host": "cloudflare", "project": "demo-store", "pages_host": "demo-store-1bm.pages.dev",
            "d1": {"name": "demo-store", "id": "d1-id"}}}}))
        self.ws = root / "demo-store"
        self.ws.mkdir()
        (self.ws / ".client.json").write_text(json.dumps({"slug": "demo-store", "name": "Fernhill Candle Co."}))
        self.site = load_site()
        self.site.ENV_FILE = root / "env"
        self.site.REGISTRY = root / "sites.json"
        self.site.STRIPE_API = self.base
        self.cf, self.published = [], []
        self.site.cf_api = lambda method, path, body=None, ok404=False: self.cf.append((method, path, body)) or {}
        self.site.cmd_publish = lambda a: self.published.append(a.name)
        Fake.state = {"sent": [], "rows": [row()]}
        self.cwd = os.getcwd()
        os.chdir(self.ws)
        self.env = mock.patch.dict(os.environ, {"SITE_ADMIN": "1", "PATCHLAMP_URL": self.base})
        self.env.start()
        for k in ("STRIPE_KEY_PATCHLAMP", "STRIPE_TEST_KEY", "PATCHLAMP_RELAY_SHARED_SECRET"):
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def checkout(self, **kw):
        a = argparse.Namespace(name="demo-store", connected=False, test=False, key_from=None, webhook=False,
                               live=False, off=False, dry_run=False)
        for k, v in kw.items():
            setattr(a, k, v)
        self.out = io.StringIO()
        with contextlib.redirect_stdout(self.out), contextlib.redirect_stderr(self.out):
            self.site.cmd_checkout(a)

    def env_vars(self):
        self.assertEqual(len(self.cf), 1)
        method, path, body = self.cf[0]
        self.assertEqual((method, path), ("PATCH", "/pages/projects/demo-store"))
        prod = body["deployment_configs"]["production"]["env_vars"]
        self.assertEqual(prod, body["deployment_configs"]["preview"]["env_vars"])
        return prod

    def test_connected_sets_the_three_secrets_and_republishes(self):
        self.checkout(connected=True, test=True)
        v = self.env_vars()
        self.assertEqual(v["STRIPE_SECRET_KEY"], {"type": "secret_text", "value": TEST}, "the platform key, by name")
        self.assertEqual(v["STRIPE_ACCOUNT"], {"type": "secret_text", "value": ACCT})
        self.assertEqual(v["STRIPE_WEBHOOK_SECRET"], {"type": "secret_text", "value": FWD}, "the forward secret")
        self.assertEqual(self.published, ["demo-store"])
        acct = [s for s in Fake.state["sent"] if s["path"] == "/v1/account"]
        self.assertEqual(acct[0]["account"], ACCT)
        self.assertFalse([s for s in Fake.state["sent"] if "webhook_endpoints" in s["path"]], "no Stripe webhook made")

    def test_refuses_unless_connected(self):
        for rows in ([row(status="invited")], []):
            Fake.state["rows"] = rows
            with self.assertRaises(SystemExit):
                self.checkout(connected=True, test=True)
        self.assertEqual(self.cf, [])
        self.assertEqual(self.published, [])

    def test_refuses_a_mode_mismatch_and_an_account_that_cannot_charge(self):
        with self.assertRaises(SystemExit):
            self.checkout(connected=True)                  # a test-mode account without --test
        Fake.state["rows"] = [row(livemode=True)]
        with self.assertRaises(SystemExit):
            self.checkout(connected=True, test=True)       # a live account with --test
        Fake.state["charges"] = False
        with self.assertRaises(SystemExit):
            self.checkout(connected=True)
        self.assertEqual(self.cf, [])

    def test_live_connected_uses_the_live_platform_key(self):
        Fake.state["rows"] = [row(livemode=True)]
        self.checkout(connected=True)
        self.assertEqual(self.env_vars()["STRIPE_SECRET_KEY"]["value"], LIVE)

    def test_off_clears_all_three(self):
        self.checkout(off=True)
        self.assertEqual(self.env_vars(), {"STRIPE_SECRET_KEY": None, "STRIPE_ACCOUNT": None, "STRIPE_WEBHOOK_SECRET": None})

    def test_the_key_from_fallback_still_works_and_clears_a_stale_account(self):
        self.checkout(key_from="OWNER_KEY")
        v = self.env_vars()
        self.assertEqual(v["STRIPE_SECRET_KEY"]["value"], "sk_test_ownerKEY")
        self.assertIsNone(v["STRIPE_ACCOUNT"])
        self.assertNotIn("STRIPE_WEBHOOK_SECRET", v)
        self.assertFalse([s for s in Fake.state["sent"] if s["path"].startswith("/internal/")], "no patchlamp call")

    def test_one_way_at_a_time(self):
        with self.assertRaises(SystemExit):
            self.checkout(connected=True, key_from="OWNER_KEY")
        with self.assertRaises(SystemExit):
            self.checkout(key_from="OWNER_KEY", test=True)


class CatalogConnectedNodeTest(unittest.TestCase):
    def setUp(self):
        self.node = shutil.which("node")
        if not self.node:
            self.skipTest("no node")
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        shutil.copytree(SHELL / "functions", self.work / "functions")
        shutil.copytree(CATALOG / "functions", self.work / "functions", dirs_exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_node(self, src, extra=None):
        script = self.work / "run.mjs"
        script.write_text(src)
        r = subprocess.run([self.node, str(script)], capture_output=True, text=True, cwd=self.work,
                           env=dict(os.environ, **(extra or {})))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_checkout_on_a_connected_site_carries_stripe_account_and_nothing_else_changes(self):
        out = self.run_node(r"""
import { onRequestPost as checkout } from "./functions/api/checkout.js";
import { onRequestGet as catalog, checkoutMode, checkoutVia } from "./functions/api/catalog.js";
const db = { prepare(sql) { const st = { bind() { return st; }, async first() { return { n: 0 }; },
  async all() { if (/FROM products/.test(sql)) return { results: [{ id: 3, name: "Candle", price_cents: 2400, status: "on sale" }] }; return { results: [] }; },
  async run() { return { meta: { changes: 1 } }; } }; return st; } };
const seen = [];
globalThis.fetch = async (url, init) => { seen.push({ url, headers: init.headers, body: init.body.toString() });
  return new Response(JSON.stringify({ id: "cs_test_1", url: "https://checkout.stripe.com/x" }), { status: 200 }); };
const req = () => new Request("https://shop.example/api/checkout", { method: "POST", headers: { "content-type": "application/json" },
  body: JSON.stringify({ items: [{ id: 3, qty: 1 }], name: "Sam", email: "s@x.test" }) });
const connected = { DB: db, STRIPE_SECRET_KEY: "sk_test_platform", STRIPE_ACCOUNT: "acct_1TestOwner00001", STRIPE_WEBHOOK_SECRET: "f" };
const keyed = { DB: db, STRIPE_SECRET_KEY: "sk_test_owner" };
await checkout({ request: req(), env: connected });
await checkout({ request: req(), env: keyed });
const out = { connected: seen[0], keyed: seen[1] };
out.via = [checkoutVia({}), checkoutVia(keyed), checkoutVia(connected), checkoutVia({ STRIPE_ACCOUNT: "acct_x" })];
out.mode = [checkoutMode(connected), checkoutMode({ STRIPE_SECRET_KEY: "sk_live_p", STRIPE_ACCOUNT: "acct_x" })];
out.catalog = await (await catalog({ env: connected })).json();
console.log(JSON.stringify(out));
""")
        c, k = out["connected"], out["keyed"]
        self.assertEqual(c["headers"]["stripe-account"], ACCT)
        self.assertEqual(c["headers"]["authorization"], "Bearer sk_test_platform")
        self.assertNotIn("stripe-account", k["headers"], "the fallback path sends no Stripe-Account")
        self.assertEqual(c["body"], k["body"], "the session body is the same either way")
        for f in ("application_fee", "transfer_data", "on_behalf_of"):
            self.assertNotIn(f, c["body"])
        self.assertEqual(out["via"], ["off", "key", "connected", "off"])
        self.assertEqual(out["mode"], ["test", "live"])
        self.assertEqual((out["catalog"]["checkout"], out["catalog"]["via"]), ("test", "connected"))

    def test_the_unchanged_webhook_verifies_patchlamps_forwarded_signature(self):
        body = json.dumps({"id": "evt_1", "type": "checkout.session.completed", "account": ACCT,
                           "data": {"object": {"id": "cs_test_1", "payment_status": "paid", "amount_total": 2400}}})
        t = int(time.time())
        # § Contract C: Stripe-Signature: t=<unix>,v1=<hex hmac_sha256(forward_secret, "<t>.<body>")>
        good = f"t={t},v1=" + hmac.new(FWD.encode(), f"{t}.{body}".encode(), hashlib.sha256).hexdigest()
        wrong = f"t={t},v1=" + hmac.new(b"not-the-secret", f"{t}.{body}".encode(), hashlib.sha256).hexdigest()
        (self.work / "in.json").write_text(json.dumps({"body": body, "good": good, "wrong": wrong, "secret": FWD}))
        out = self.run_node(r"""
import { verify, onRequestPost as hook } from "./functions/api/stripe-webhook.js";
import { readFileSync } from "node:fs";
const { body, good, wrong, secret } = JSON.parse(readFileSync(new URL("./in.json", import.meta.url), "utf8"));
const runs = [];
const db = { prepare(sql) { const st = { args: [], bind(...a) { st.args = a; return st; }, async run() { runs.push([sql.slice(0, 30), st.args.at(-1)]); return {}; } }; return st; } };
const env = { DB: db, STRIPE_WEBHOOK_SECRET: secret };
const post = (sig) => hook({ request: new Request("https://shop.example/api/stripe-webhook", { method: "POST", headers: { "stripe-signature": sig }, body }), env });
const out = { verify: [await verify(body, good, secret), await verify(body, wrong, secret)] };
out.good = (await post(good)).status; out.runs = runs.slice(); out.wrong = (await post(wrong)).status;
console.log(JSON.stringify(out));
""")
        self.assertEqual(out["verify"], [True, False])
        self.assertEqual(out["good"], 200)
        self.assertEqual(out["runs"], [["UPDATE orders SET status = 'pa", "cs_test_1"]])
        self.assertEqual(out["wrong"], 400)


if __name__ == "__main__":
    unittest.main()
