"""The Postmaster signal (ROADMAP B136): Google Postmaster Tools read by API into postmaster.jsonl,
shown by `outreach status`, read by the stop rule, and a HEALTH line when a domain goes three days
without a reading. Against a stub of Google's token and Postmaster endpoints serving fixture responses
(tests/fixtures/postmaster/), under the example venture (tests/fixtures/ventures/example: its sending
domain is trybrightwell.example), so no real host, key or product name is touched.

    python3 -m unittest tests.test_outreach_postmaster   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent.parent / "lib"))

import datetime as dt  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
import threading  # noqa: E402
import unittest  # noqa: E402
import urllib.parse  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402
from pathlib import Path  # noqa: E402

import postmaster  # noqa: E402

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
OUTREACH = TOOLS / "bin" / "outreach"
FIX = HERE / "fixtures" / "postmaster"
VENTURES = HERE / "fixtures" / "ventures"
DOMAIN = "trybrightwell.example"          # the example venture's sending domain
NOW = "2026-10-08T09:00:00"               # so "yesterday" is 2026-10-07, the fixture's last day

STUB_NOTIFY = """#!/usr/bin/env python3
import json, os, sys
open(os.environ["STUB_LOG"], "a").write(json.dumps({"tool": "notify", "argv": sys.argv[1:]}) + "\\n")
"""


def v2_with(ratio, day=(2026, 10, 7)):
    return {"domainStats": [{"metric": "spam_rate", "date": dict(zip(("year", "month", "day"), day)),
                             "value": {"doubleValue": ratio}}]}


class Google(BaseHTTPRequestHandler):
    """The token endpoint and both Postmaster versions. `state` picks what each answers."""

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

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode() if n else ""

    def do_POST(self):
        u = urllib.parse.urlsplit(self.path)
        body = self._body()
        self.state["seen"].append(("POST", u.path, body))
        if u.path == "/token":
            form = urllib.parse.parse_qs(body)
            if form.get("grant_type") == ["authorization_code"]:
                return self._send(200, {"access_token": "ya29.FAKE", "refresh_token": "1//FAKE-refresh-token"})
            return self._send(200, {"access_token": "ya29.FAKE", "expires_in": 3599})
        if u.path.endswith("/domainStats:query") and u.path.startswith("/v2/"):
            if self.headers.get("Authorization") != "Bearer ya29.FAKE":
                return self._send(401, {"error": {"message": "bad token"}})
            v2 = self.state.get("v2")
            if isinstance(v2, int):
                return self._send(v2, {"error": {"message": "refused"}})
            return self._send(200, v2 if v2 is not None else {})
        return self._send(404, {"error": {"message": "no route"}})

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        self.state["seen"].append(("GET", u.path, u.query))
        if u.path.endswith("/trafficStats") and u.path.startswith("/v1/"):
            v1 = self.state.get("v1")
            if isinstance(v1, int):
                return self._send(v1, {"error": {"message": "retired"}})
            return self._send(200, v1 if v1 is not None else {})
        return self._send(404, {"error": {"message": "no route"}})


class LibTest(unittest.TestCase):
    """lib/postmaster.py on its own: the parsers, the file, the registry's view."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="postmaster-lib-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.path = self.tmp / "postmaster.jsonl"

    def test_v2_is_a_ratio_and_has_no_reputation(self):
        rows = postmaster.parse_v2(json.loads((FIX / "v2-query.json").read_text()), DOMAIN)
        self.assertEqual([r["date"] for r in rows], ["2026-10-06", "2026-10-07"])
        self.assertAlmostEqual(rows[1]["rate"], 0.02)
        self.assertIsNone(rows[1]["reputation"])
        self.assertEqual(rows[1]["api"], "v2")
        self.assertAlmostEqual(postmaster.parse_v2(v2_with(0.001), DOMAIN)[0]["rate"], 0.1)

    def test_v1_carries_reputation(self):
        rows = postmaster.parse_v1(json.loads((FIX / "v1-trafficstats.json").read_text()), DOMAIN)
        self.assertEqual([(r["date"], r["reputation"]) for r in rows], [("2026-10-06", "MEDIUM"), ("2026-10-07", "HIGH")])
        self.assertEqual(postmaster.describe(rows[1]), "reputation HIGH, spam rate 0.02%")

    def test_empty_is_no_rows(self):
        self.assertEqual(postmaster.parse_v2({}, DOMAIN), [])
        self.assertEqual(postmaster.parse_v1({"trafficStats": []}, DOMAIN), [])

    def test_record_dedupes_and_registry_view(self):
        rows = postmaster.parse_v1(json.loads((FIX / "v1-trafficstats.json").read_text()), DOMAIN)
        self.assertEqual(len(postmaster.record(self.path, rows, "2026-10-08T09:00:00-06:00")), 2)
        self.assertEqual(postmaster.record(self.path, rows, "2026-10-09T09:00:00-06:00"), [])
        self.assertEqual(len(postmaster.read_rows(self.path)), 2)
        rep = postmaster.reputation(DOMAIN, self.path, dt.date(2026, 10, 8))
        self.assertEqual((rep["source"], rep["date"], rep["reputation"], rep["age_days"], rep["stale"]),
                         ("postmaster", "2026-10-07", "HIGH", 1, False))
        self.assertAlmostEqual(rep["spam_rate_pct"], 0.02)
        old = postmaster.reputation(DOMAIN, self.path, dt.date(2026, 10, 10))
        self.assertTrue(old["stale"])
        none = postmaster.reputation("other.example", self.path, dt.date(2026, 10, 8))
        self.assertEqual((none["date"], none["stale"]), (None, True))

    def test_stale_lines_name_the_last_fetch(self):
        postmaster.log_fetch(self.path, DOMAIN, "no data", "0 day(s), 0 new", "2026-10-10T10:20:00-06:00")
        lines = postmaster.stale_lines([DOMAIN], self.path, dt.date(2026, 10, 11))
        self.assertEqual(len(lines), 1)
        self.assertIn(f"no reading for {DOMAIN} ever", lines[0])
        self.assertIn("no data", lines[0])

    def test_missing_credentials_and_the_code(self):
        env = {}
        self.assertEqual(postmaster.missing_credentials(env.get), list(postmaster.CRED_NAMES))
        self.assertEqual(postmaster.missing_credentials({"POSTMASTER_ACCESS_TOKEN": "x"}.get), [])
        self.assertEqual(postmaster.code_from("http://127.0.0.1:8765/?state=&code=4/abc&scope=x"), "4/abc")
        url = postmaster.grant_url({"POSTMASTER_CLIENT_ID": "cid"}.get)
        self.assertIn("access_type=offline", url)
        self.assertIn("postmaster.traffic.readonly", urllib.parse.unquote(url))


class OutreachPostmasterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Google.state = {"seen": []}
        cls.server = HTTPServer(("127.0.0.1", 0), Google)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="postmaster-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        stub = self.tmp / "notify"
        stub.write_text(STUB_NOTIFY)
        stub.chmod(0o755)
        self.log = self.tmp / "stub.log"
        self.todo = self.tmp / "TAYLOR-TODO.md"
        self.todo.write_text("# TAYLOR-TODO\n\n## 1. Now\n\n## 7. Triage\n")
        self.envfile = self.tmp / "env"
        self.envfile.write_text("SOME_KEY=kept\n")
        Google.state = {"seen": [], "v2": json.loads((FIX / "v2-query.json").read_text())}
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.tmp), "LC_ALL": "C.UTF-8",
            "PYTHONIOENCODING": "utf-8", "CLAUDE_TOOLS_ENV": str(self.envfile),
            "VENTURES_DIR": str(VENTURES), "VENTURE": "example",
            "OUTREACH_STATE": str(self.tmp / "state"), "OUTREACH_LEDGER": str(self.tmp / "ledger.jsonl"),
            "OUTREACH_NOTIFY_BIN": str(stub), "STUB_LOG": str(self.log), "TAYLOR_TODO": str(self.todo),
            "OUTREACH_PROVIDER": "fake", "OUTREACH_NOW": NOW,
            "POSTMASTER_CLIENT_ID": "cid.apps.example", "POSTMASTER_CLIENT_SECRET": "fake-secret",
            "POSTMASTER_REFRESH_TOKEN": "1//fake", "POSTMASTER_API_BASE": self.base,
            "POSTMASTER_TOKEN_URL": self.base + "/token",
        }

    def run_it(self, *args, expect=0, **over):
        env = dict(self.env)
        for k, v in over.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = str(v)
        r = subprocess.run([sys.executable, str(OUTREACH), *args], capture_output=True, text=True, env=env,
                           timeout=120)
        if expect is not None:
            self.assertEqual(r.returncode, expect, f"{args} exited {r.returncode}\n{r.stdout}\n{r.stderr}")
        return r

    def rows(self, name="postmaster.jsonl"):
        p = self.tmp / "state" / name
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    def notifies(self):
        return [json.loads(x) for x in self.log.read_text().splitlines()] if self.log.exists() else []

    # -- the acceptance -------------------------------------------------------------
    def test_status_prints_yesterdays_reading(self):
        self.run_it("postmaster", "fetch")
        rows = self.rows()
        self.assertEqual([(r["domain"], r["date"], r["source"]) for r in rows],
                         [(DOMAIN, "2026-10-06", "api"), (DOMAIN, "2026-10-07", "api")])
        sent = [s for s in Google.state["seen"] if s[1].endswith("domainStats:query")][0]
        body = json.loads(sent[2])
        self.assertEqual(body["metricDefinitions"][0]["baseMetric"]["standardMetric"], "SPAM_RATE")
        self.assertEqual(body["timeQuery"]["dateRanges"]["dateRanges"][0]["end"], {"year": 2026, "month": 10, "day": 7})
        out = self.run_it("status").stdout
        self.assertIn(f"Postmaster {DOMAIN}, yesterday (2026-10-07): reputation not published by Google, "
                      "spam rate 0.02%", out)
        self.assertIn("stop rules: none crossed", out)

    def test_v1_answers_when_v2_refuses_and_brings_reputation(self):
        Google.state.update(v2=404, v1=json.loads((FIX / "v1-trafficstats.json").read_text()))
        self.run_it("postmaster", "fetch")
        out = self.run_it("status").stdout
        self.assertIn(f"Postmaster {DOMAIN}, yesterday (2026-10-07): reputation HIGH, spam rate 0.02%", out)
        q = [s for s in Google.state["seen"] if s[1].endswith("/trafficStats")][0][2]
        self.assertIn("endDate.day=8", q)          # v1's end is exclusive

    def test_a_tenth_of_a_percent_trips_the_lane_and_files_the_entry(self):
        Google.state["v2"] = v2_with(0.001)
        r = self.run_it("postmaster", "fetch", expect=1)
        self.assertIn("the lane is stopped", r.stdout)
        self.assertTrue((self.tmp / "state" / "stopped.json").exists())
        todo = self.todo.read_text()
        self.assertIn("**The email lane stopped itself", todo.split("## 7.")[1])
        self.assertIn(f"Postmaster spam rate on {DOMAIN}: 0.10% on 2026-10-07", todo)
        self.assertEqual(len([n for n in self.notifies() if n["tool"] == "notify"]), 1)
        out = self.run_it("status").stdout
        self.assertIn("THE LANE IS STOPPED", out)
        # a second fetch of the same day neither stacks the entry nor notifies again
        self.run_it("postmaster", "fetch")
        self.assertEqual(self.todo.read_text().count("The email lane stopped itself"), 1)
        self.assertEqual(len(self.rows()), 1)

    def test_under_the_line_does_not_trip(self):
        Google.state["v2"] = v2_with(0.0009)
        self.run_it("postmaster", "fetch")
        self.assertFalse((self.tmp / "state" / "stopped.json").exists())
        self.assertNotIn("stopped itself", self.todo.read_text())

    # -- the edges --------------------------------------------------------------------
    def test_not_set_up_writes_nothing(self):
        r = self.run_it("postmaster", "fetch", POSTMASTER_REFRESH_TOKEN=None)
        self.assertIn("isn't set up: POSTMASTER_REFRESH_TOKEN unset", r.stdout)
        self.assertEqual(self.rows(), [])
        self.assertEqual(Google.state["seen"], [])
        out = self.run_it("status", POSTMASTER_REFRESH_TOKEN=None).stdout
        self.assertIn(f"Postmaster {DOMAIN}: no reading for yesterday (2026-10-07); not set up", out)

    def test_no_data_is_not_zero(self):
        Google.state["v2"] = {}
        r = self.run_it("postmaster", "fetch")
        self.assertIn("Google has no data", r.stdout)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.rows("postmaster-fetch.jsonl")[-1]["outcome"], "no data")

    def test_a_failed_call_says_why_and_exits_2(self):
        Google.state.update(v2=500, v1=410)
        r = self.run_it("postmaster", "fetch", expect=2)
        self.assertIn("v2 domainStats: HTTP 500", r.stdout)
        self.assertIn("v1 trafficStats: HTTP 410", r.stdout)
        self.assertEqual(self.rows(), [])

    def test_check_is_the_health_line(self):
        r = self.run_it("postmaster", "check", expect=1)
        self.assertIn(f"no reading for {DOMAIN} ever", r.stdout)
        self.run_it("postmaster", "fetch")
        r = self.run_it("postmaster", "check")
        self.assertIn("every domain read within 3 days", r.stdout)
        r = self.run_it("postmaster", "check", expect=1, OUTREACH_NOW="2026-10-10T21:00:00")
        self.assertIn(f"no reading for {DOMAIN} since 2026-10-07 (3 days)", r.stdout)
        r = self.run_it("postmaster", "check", expect=1, POSTMASTER_CLIENT_ID=None)
        self.assertIn("not set up", r.stdout)

    def test_grant_writes_the_refresh_token_unprinted(self):
        r = self.run_it("postmaster", "grant", POSTMASTER_REFRESH_TOKEN=None)
        self.assertIn("accounts.google.com", r.stdout)
        r = self.run_it("postmaster", "grant", "--code", "http://127.0.0.1:8765/?code=4/onetime&scope=x",
                        POSTMASTER_REFRESH_TOKEN=None)
        self.assertNotIn("FAKE-refresh-token", r.stdout + r.stderr)
        text = self.envfile.read_text()
        self.assertIn("SOME_KEY=kept\n", text)
        self.assertIn("POSTMASTER_REFRESH_TOKEN=1//FAKE-refresh-token\n", text)
        self.assertEqual(self.envfile.stat().st_mode & 0o777, 0o600)

    def test_hand_reading_still_works(self):
        r = self.run_it("postmaster", "0.05", "--domain", DOMAIN)
        self.assertIn("Recorded 0.05%", r.stdout)
        self.assertEqual(self.rows()[0]["rate"], 0.05)


if __name__ == "__main__":
    unittest.main()
