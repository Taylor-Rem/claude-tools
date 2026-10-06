"""pay against a fake Stripe and a fake patchlamp.com: no network, no money.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

One local HTTP server answers both /v1/... (Stripe, form-encoded, the way
api.stripe.com does) and /internal/relay/projects/{slug}/connections (the
stripe row of plan 16 § Contract A) and records every request with its
headers. The request shapes are the contract with Stripe: every call carries
Stripe-Account, no fee field ever, amounts in cents, the invoice sequence.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PAY = HERE.parent / "bin" / "pay"
LIVE = "sk_live_FAKEplatformKEY000"
TEST = "sk_test_FAKEplatformKEY000"
ACCT = "acct_1TestOwner00001"


def stripe_row(status="connected", livemode=False, acct=ACCT):
    row = {"id": 9, "kind": "stripe", "status": status, "label": "Fernhill Candle Co.", "external_id": acct,
           "stripe_account": acct, "charges_enabled": status == "connected", "payouts_enabled": status == "connected",
           "requirements": [] if status == "connected" else ["external_account", "tos_acceptance.date"],
           "livemode": livemode}
    if status == "connected":
        row["env"] = {"STRIPE_CONNECTED_ACCOUNT": acct}
        row["webhook_secret"] = "0123456789abcdef0123456789abcdef"
    return row


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

    def _record(self, method, body=None):
        u = urllib.parse.urlsplit(self.path)
        self.state["sent"].append({
            "method": method, "path": u.path, "query": dict(urllib.parse.parse_qsl(u.query)),
            "account": self.headers.get("Stripe-Account"), "auth": self.headers.get("Authorization"),
            "idem": self.headers.get("Idempotency-Key"), "body": body or {}})
        return u.path

    def _test_mode_only(self):
        """A test-mode account asked for with a live key, the way Stripe says it."""
        if self.state.get("test_only") and self.headers.get("Authorization") == f"Bearer {LIVE}":
            self._send(404, {"error": {"message": f"No such account: '{ACCT}'; a similar object exists in test mode, "
                                                  f"but a live mode key was used to make this request."}})
            return True
        return False

    def do_GET(self):
        path = self._record("GET")
        s = self.state
        if path.startswith("/internal/relay/projects/"):
            slug = path.split("/")[4]
            return self._send(200, {"connections": s["rows"].get(slug, [])})
        if self._test_mode_only():
            return
        if path == "/v1/account":
            return self._send(200, {"id": ACCT, "charges_enabled": True, "payouts_enabled": False,
                                    "business_profile": {"name": "Fernhill Candle Co."},
                                    "requirements": {"currently_due": ["external_account"]}})
        if path == "/v1/customers":
            return self._send(200, {"data": s.get("by_email", [])})
        if path == "/v1/customers/search":
            return self._send(200, {"data": s.get("by_name", [])})
        if path == "/v1/invoices":
            return self._send(200, {"data": s.get("invoices") or [{"id": "in_1", "number": "FERN-0001", "amount_due": 45000,
                                                                   "status": "paid", "customer_name": "Smith"}]})
        if path == "/v1/charges":
            return self._send(200, {"data": [{"amount": 4500, "paid": True, "status": "succeeded",
                                              "description": "June service", "billing_details": {"name": "Smith"}}]})
        self._send(404, {"error": {"message": "unknown"}})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
        body = dict(urllib.parse.parse_qsl(raw))
        path = self._record("POST", body)
        if self._test_mode_only():
            return
        if path == "/v1/prices":
            return self._send(200, {"id": "price_1", "unit_amount": int(body["unit_amount"])})
        if path == "/v1/payment_links":
            return self._send(200, {"id": "plink_1", "url": "https://buy.stripe.com/test_abc"})
        if path == "/v1/customers":
            return self._send(200, {"id": "cus_new", "name": body.get("name"), "email": body.get("email")})
        if path == "/v1/invoices":
            return self._send(200, {"id": "in_1", "status": "draft"})
        if path == "/v1/invoiceitems":
            return self._send(200, {"id": "ii_1"})
        if path == "/v1/invoices/in_1/finalize":
            return self._send(200, {"id": "in_1", "number": "FERN-0001", "status": "open",
                                    "hosted_invoice_url": "https://invoice.stripe.com/i/acct_x/test_inv"})
        if path == "/v1/invoices/in_1/send":
            return self._send(200, {"id": "in_1", "number": "FERN-0001", "status": "open",
                                    "hosted_invoice_url": "https://invoice.stripe.com/i/acct_x/test_inv"})
        self._send(404, {"error": {"message": "unknown"}})


class PayTest(unittest.TestCase):
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
        self.home = Path(self.tmp.name)
        self.envfile = self.home / "env"
        self.envfile.write_text(f"STRIPE_KEY_PATCHLAMP={LIVE}\nSTRIPE_TEST_KEY={TEST}\n"
                                f"PATCHLAMP_RELAY_SHARED_SECRET=relay-secret\nPATCHLAMP_URL={self.base}\n")
        Fake.state = {"sent": [], "rows": {"demo-store": [stripe_row()]}}

    def tearDown(self):
        self.tmp.cleanup()

    def pay(self, *args, env=None, cwd=None):
        e = {k: v for k, v in os.environ.items()
             if not k.startswith(("STRIPE_", "PATCHLAMP_"))}
        e.update(CLAUDE_TOOLS_ENV=str(self.envfile), STRIPE_API_BASE=self.base)
        e.update(env or {})
        r = subprocess.run([sys.executable, str(PAY), *args], capture_output=True, text=True, env=e,
                           cwd=cwd or self.tmp.name)
        for key in (LIVE, TEST, "relay-secret"):
            self.assertNotIn(key, r.stdout + r.stderr, "a key value was printed")
        return r

    def stripe_calls(self):
        return [x for x in Fake.state["sent"] if x["path"].startswith("/v1/")]

    def workspace(self, slug="demo-store"):
        ws = self.home / slug
        ws.mkdir()
        (ws / ".client.json").write_text(json.dumps({"slug": slug, "name": "Fernhill"}))
        return str(ws)

    def assert_clean(self, calls):
        for c in calls:
            self.assertEqual(c["account"], ACCT, f"{c['method']} {c['path']} without Stripe-Account")
            for k in c["body"]:
                for f in ("application_fee", "transfer_data", "on_behalf_of"):
                    self.assertNotIn(f, k)
            if c["method"] == "POST":
                self.assertTrue(c["idem"], "POSTs carry an idempotency key")

    # -- link / deposit -----------------------------------------------------------

    def test_link_is_a_price_then_a_payment_link_on_their_account(self):
        r = self.pay("link", "$45", "June service", env={"STRIPE_CONNECTED_ACCOUNT": ACCT})
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.stripe_calls()
        self.assertEqual([c["path"] for c in calls], ["/v1/prices", "/v1/payment_links"])
        self.assert_clean(calls)
        self.assertEqual(calls[0]["body"]["unit_amount"], "4500")
        self.assertEqual(calls[0]["body"]["currency"], "usd")
        self.assertEqual(calls[0]["body"]["product_data[name]"], "June service")
        self.assertEqual(calls[1]["body"]["line_items[0][price]"], "price_1")
        self.assertEqual(calls[1]["body"]["line_items[0][quantity]"], "1")
        self.assertEqual(calls[0]["auth"], f"Bearer {LIVE}", "no workspace, no --test: the live platform key")
        self.assertIn("https://buy.stripe.com/test_abc", r.stdout)
        self.assertIn("$45.00", r.stdout)

    def test_deposit_is_labelled_a_deposit(self):
        r = self.pay("deposit", "1,200.50", "catering 10/12", "--account", ACCT)
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.stripe_calls()
        self.assert_clean(calls)
        self.assertEqual(calls[0]["body"]["unit_amount"], "120050")
        self.assertEqual(calls[0]["body"]["product_data[name]"], "Deposit — catering 10/12")
        self.assertEqual(calls[1]["body"]["metadata[patchlamp]"], "deposit")
        self.assertIn("$1,200.50 deposit", r.stdout)

    def test_amounts_that_are_not_money_are_refused_before_anything_is_sent(self):
        for bad in ("0.10", "12.345", "abc", "-5", "1000000"):
            r = self.pay("link", bad, "x", "--account", ACCT)
            self.assertNotEqual(r.returncode, 0, bad)
        self.assertEqual(self.stripe_calls(), [])

    def test_dry_run_sends_nothing(self):
        r = self.pay("invoice", "Smith", "450", "June service", "--dry-run", "--account", ACCT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([c for c in self.stripe_calls() if c["method"] == "POST"], [])
        self.assertIn("would POST /v1/invoiceitems", r.stdout)
        self.assertIn("amount = 45000", r.stdout)

    # -- invoice (the acceptance line: "invoice Smith $450 for the June service") ------

    def test_invoice_smith_450_is_a_payable_invoice_from_their_account(self):
        r = self.pay("invoice", "Smith", "$450", "June service", env={"STRIPE_CONNECTED_ACCOUNT": ACCT})
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.stripe_calls()
        self.assertEqual([(c["method"], c["path"]) for c in calls], [
            ("GET", "/v1/customers/search"), ("POST", "/v1/customers"), ("POST", "/v1/invoices"),
            ("POST", "/v1/invoiceitems"), ("POST", "/v1/invoices/in_1/finalize")])
        self.assert_clean(calls)
        self.assertEqual(calls[0]["query"]["query"], "name:'Smith'")
        self.assertEqual(calls[1]["body"]["name"], "Smith")
        inv = calls[2]["body"]
        self.assertEqual(inv["customer"], "cus_new")
        self.assertEqual(inv["collection_method"], "send_invoice")
        self.assertEqual(inv["days_until_due"], "14")
        self.assertEqual(inv["pending_invoice_items_behavior"], "exclude")
        item = calls[3]["body"]
        self.assertEqual((item["invoice"], item["amount"], item["currency"]), ("in_1", "45000", "usd"))
        self.assertEqual(item["description"], "June service")
        self.assertIn("https://invoice.stripe.com/i/acct_x/test_inv", r.stdout)
        self.assertIn("$450.00", r.stdout)

    def test_invoice_in_lines_is_one_item_a_line_and_they_must_add_up(self):
        """The hand-over from `estimate` (B123): --line each, --ref in the metadata, --json for a machine."""
        env = {"STRIPE_CONNECTED_ACCOUNT": ACCT}
        r = self.pay("invoice", "Smith", "450", "Estimate E-0001", "--line", "3 windows", "300",
                     "--line", "2 doors", "150", "--ref", "E-0001", "--json", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.stripe_calls()
        self.assert_clean(calls)
        items = [c["body"] for c in calls if c["path"] == "/v1/invoiceitems"]
        self.assertEqual([(i["description"], i["amount"]) for i in items], [("3 windows", "30000"), ("2 doors", "15000")])
        self.assertEqual(next(c for c in calls if c["path"] == "/v1/invoices")["body"]["metadata[ref]"], "E-0001")
        out = json.loads(r.stdout)
        self.assertEqual((out["kind"], out["number"], out["amount_cents"], out["lines"]), ("invoice", "FERN-0001", 45000, 2))
        Fake.state["sent"] = []
        r = self.pay("invoice", "Smith", "450", "x", "--line", "a", "300", "--line", "b", "100", env=env)
        self.assertIn("add up to $400.00, not $450.00", r.stderr)
        self.assertEqual(self.stripe_calls(), [], "a mismatch makes nothing")
        r = self.pay("invoice", "Smith", "400", "x", "--line", "work", "450", "--line", "credit", "-50", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-5000", [c["body"].get("amount") for c in self.stripe_calls()])

    def test_an_idempotency_key_and_a_ref_never_bill_twice(self):
        """estimate sync may run again after pay succeeded (B123 review): the same key gives the same
        Idempotency-Keys, and an invoice already made for the ref is handed back, not made again."""
        env = {"STRIPE_CONNECTED_ACCOUNT": ACCT}
        Fake.state["by_email"] = [{"id": "cus_smith", "name": "Smith", "email": "s@x.test"}]
        args = ("invoice", "Smith", "450", "Estimate E-0001", "--email", "s@x.test", "--ref", "E-0001",
                "--idempotency-key", "estimate:E-0001:tok123", "--json")
        r = self.pay(*args, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        keys = [c["idem"] for c in self.stripe_calls() if c["method"] == "POST"]
        self.assertEqual(keys[0], "estimate:E-0001:tok123:/v1/invoices:0")
        self.assertEqual(len(set(keys)), len(keys), "one key a request")
        Fake.state["sent"] = []
        self.pay(*args, env=env)
        self.assertEqual([c["idem"] for c in self.stripe_calls() if c["method"] == "POST"], keys, "a retry sends the same keys")
        Fake.state["sent"] = []
        Fake.state["invoices"] = [{"id": "in_9", "number": "FERN-0009", "status": "open", "amount_due": 45000,
                                   "metadata": {"ref": "E-0001"}, "hosted_invoice_url": "https://invoice.stripe.com/i/x/9"}]
        r = self.pay(*args, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual((out["id"], out["existing"]), ("in_9", True))
        self.assertEqual([c for c in self.stripe_calls() if c["method"] == "POST"], [], "nothing made again")
        Fake.state["invoices"][0]["status"] = "draft"
        self.assertIn("draft invoice for E-0001", self.pay(*args, env=env).stderr)

    def test_invoice_to_a_known_email_reuses_the_customer_and_send_emails_it(self):
        Fake.state["by_email"] = [{"id": "cus_smith", "name": "Pat Smith", "email": "smith@x.test"}]
        r = self.pay("invoice", "Smith", "450", "June service", "--email", "smith@x.test", "--due", "30d", "--send",
                     "--account", ACCT)
        self.assertEqual(r.returncode, 0, r.stderr)
        paths = [c["path"] for c in self.stripe_calls()]
        self.assertNotIn("/v1/customers/search", paths)
        self.assertEqual(paths.count("/v1/customers"), 1, "a GET by email, no create")
        self.assertIn("/v1/invoices/in_1/send", paths)
        self.assertEqual(self.stripe_calls()[1]["body"]["days_until_due"], "30")
        self.assertIn("Stripe emailed it", r.stdout)

    def test_two_customers_with_that_name_asks_which(self):
        Fake.state["by_name"] = [{"id": "cus_a", "name": "Smith", "email": "a@x.test"},
                                 {"id": "cus_b", "name": "Smith", "email": "b@x.test"}]
        r = self.pay("invoice", "Smith", "450", "June service", "--account", ACCT)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--email", r.stderr)
        self.assertFalse([c for c in self.stripe_calls() if c["method"] == "POST"])

    # -- which account, which key ----------------------------------------------------

    def test_in_a_workspace_the_account_and_mode_come_from_patchlamp(self):
        ws = self.workspace()
        r = self.pay("link", "25", "Candle", cwd=ws)
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.stripe_calls()
        self.assert_clean(calls)
        self.assertEqual(calls[0]["auth"], f"Bearer {TEST}", "a test-mode account (the demo) runs on the test key")
        self.assertIn("TEST MODE", r.stdout)

    def test_a_workspace_cannot_reach_another_clients_stripe(self):
        ws = self.workspace()
        Fake.state["rows"]["other"] = [stripe_row(acct="acct_1Other0000000", livemode=True)]
        self.assertNotEqual(self.pay("link", "25", "x", "--project", "other", cwd=ws).returncode, 0)
        self.assertNotEqual(self.pay("link", "25", "x", "--account", "acct_1Other0000000", cwd=ws).returncode, 0)
        r = self.pay("link", "25", "x", cwd=ws, env={"STRIPE_CONNECTED_ACCOUNT": "acct_1Other0000000"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refusing", r.stderr)
        self.assertEqual(self.stripe_calls(), [])

    def test_onboarding_not_finished_says_what_stripe_still_needs(self):
        Fake.state["rows"]["demo-store"] = [stripe_row(status="invited")]
        r = self.pay("link", "25", "x", "--project", "demo-store")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("external_account", r.stderr)
        self.assertEqual(self.stripe_calls(), [])

    def test_not_connected_at_all_says_to_connect(self):
        Fake.state["rows"]["demo-store"] = []
        r = self.pay("link", "25", "x", "--project", "demo-store")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("CONNECT: stripe", r.stderr)

    def test_a_test_mode_account_on_the_live_key_retries_on_the_test_key(self):
        Fake.state["test_only"] = True
        r = self.pay("link", "25", "Candle", env={"STRIPE_CONNECTED_ACCOUNT": ACCT})
        self.assertEqual(r.returncode, 0, r.stderr)
        auths = [c["auth"] for c in self.stripe_calls()]
        self.assertEqual(auths[0], f"Bearer {LIVE}")
        self.assertEqual(auths[1:], [f"Bearer {TEST}"] * 2)
        self.assertIn("TEST MODE", r.stdout)

    def test_no_account_anywhere_is_a_clear_no(self):
        r = self.pay("link", "25", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("STRIPE_CONNECTED_ACCOUNT", r.stderr)

    # -- status / doctor ---------------------------------------------------------------

    def test_status(self):
        r = self.pay("status", "--project", "demo-store")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assert_clean(self.stripe_calls())
        self.assertIn("taking payments: yes", r.stdout)
        self.assertIn("payouts to their bank: NOT YET", r.stdout)
        self.assertIn("external_account", r.stdout)
        self.assertIn("FERN-0001", r.stdout)
        self.assertIn("June service", r.stdout)

    def test_doctor(self):
        r = self.pay("doctor", "--project", "demo-store")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("STRIPE_TEST_KEY: set", r.stdout)
        self.assertIn("test mode", r.stdout)
        self.assertIn("reachable: yes", r.stdout)
        self.assertEqual(self.pay("doctor").returncode, 0, "no account outside a workspace is fine")
        self.envfile.write_text(f"PATCHLAMP_URL={self.base}\n")
        self.assertNotEqual(self.pay("doctor").returncode, 0, "no platform key is not")


if __name__ == "__main__":
    unittest.main()
