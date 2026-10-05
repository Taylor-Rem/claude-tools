"""gbp's review loop (B118): `ask`, `asks`, `watch`, and `reply` refusing cleanly at quota 0.

    python3 -m unittest tests.test_gbp_reviews -q   (from claude-tools/)

No network and no real customer book: GBP_DB is a stand-in for B122's `db` (it answers
`customers find|show --json` from a JSON file and records `jobs done`), GBP_PLACES_URL is a
local server playing Place Details, and the workspace is a temp dir with a NOTES.md. What's
pinned: the queue line the relay will read (its shape is the contract with
sms-relay/relay/reviews.py), every refusal exiting 3 with its reason and nothing queued, one
toolbelt ledger line per Places call, the 20-hour reuse, and the owner's reply coming back as a
draft when Google refuses.
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
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
GBP = HERE.parent / "bin" / "gbp"
PID = "ChIJtestPlaceId0000000001"
CREDS = {"GBP_ACCESS_TOKEN": "ya29.fake", "GBP_LOCATION": "locations/129",
         "GBP_ACCOUNT": "accounts/104", "GBP_LOCATION_TITLE": "Juniper Flats"}

FAKE_DB = r'''#!/usr/bin/env python3
import json, os, sys
book = json.load(open(os.environ["FAKE_BOOK"]))
a = sys.argv[1:]
if a[:2] == ["customers", "find"]:
    q = a[2].lower()
    print(json.dumps([c for c in book["customers"] if q in json.dumps(c).lower()]))
elif a[:2] == ["customers", "show"]:
    c = next(c for c in book["customers"] if str(c["id"]) == a[2])
    print(json.dumps(dict(c, jobs=[j for j in book["jobs"] if str(j["customer_id"]) == a[2]])))
elif a[:2] == ["jobs", "done"]:
    open(os.environ["FAKE_BOOK"] + ".done", "a").write(a[2] + "\n")
    print("job " + a[2] + " done")
else:
    sys.exit("fake db: " + " ".join(a))
'''

BOOK = {"customers": [
    {"id": 7, "name": "Jo Smith", "phone": "801-555-0134", "email": "Jo@Example.com"},
    {"id": 8, "name": "Sam Smithers", "phone": "801-555-0199", "email": "sam@example.com"},
    {"id": 9, "name": "Pat Nomail", "phone": "801-555-0111", "email": ""}],
    "jobs": [{"id": 31, "customer_id": 7, "date": "2026-10-01", "what": "spring opening", "status": "done"},
             {"id": 32, "customer_id": 7, "date": "2026-10-05", "what": "heater repair", "status": "booked"}]}

DETAILS = {"id": PID, "displayName": {"text": "Juniper Flats Pool & Spa"}, "rating": 4.8, "userRatingCount": 23,
           "reviews": [{"name": f"places/{PID}/reviews/r1", "rating": 5,
                        "text": {"text": "Fixed our heater same day."}, "authorAttribution": {"displayName": "Maria S."},
                        "publishTime": "2026-10-04T18:00:00Z"},
                       {"name": f"places/{PID}/reviews/r2", "rating": 2,
                        "originalText": {"text": "Late twice."}, "authorAttribution": {"displayName": "Dev P."},
                        "publishTime": "2026-09-20T18:00:00Z"}]}


class Places(BaseHTTPRequestHandler):
    hits = []

    def do_GET(self):
        Places.hits.append((self.path, self.headers.get("X-Goog-Api-Key")))
        body = json.dumps(DETAILS).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class ReviewLoopTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Places)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Places.hits = []
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.ws = t / "ws"
        self.ws.mkdir()
        (self.ws / "NOTES.md").write_text(f"# Notes\n\n- Google place id: {PID}\n")
        self.book = t / "book.json"
        self.book.write_text(json.dumps(BOOK))
        self.db = t / "db"
        self.db.write_text(FAKE_DB)
        self.db.chmod(0o755)
        self.ledger = t / "ledger.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_gbp(self, *args, extra=None, creds=False):
        env = dict(os.environ, GBP_DB=str(self.db), FAKE_BOOK=str(self.book), IMG_LEDGER=str(self.ledger),
                   LEADS_STATE=str(Path(self.tmp.name) / "leads"), CLAUDE_TOOLS_ENV=str(Path(self.tmp.name) / "no-env"),
                   GBP_PLACES_URL=f"http://127.0.0.1:{self.server.server_port}/v1/places/",
                   GOOGLE_MAPS_API_KEY="fake-maps")
        for k in (*CREDS, "RELAY_PROJECT", "RELAY_SANDBOX"):
            env.pop(k, None)
        if creds:
            env.update(CREDS)
        env.update(extra or {})
        return subprocess.run([sys.executable, str(GBP), *args], capture_output=True, text=True, env=env, cwd=self.ws)

    def queue(self):
        p = self.ws / "reviews" / "queue.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []

    # -- ask -------------------------------------------------------------------------------

    def test_done_with_the_smith_job_marks_the_open_job_and_files_the_ask(self):
        r = self.run_gbp("ask", "801-555-0134")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        [q] = self.queue()
        self.assertEqual(q["op"], "ask")
        self.assertEqual(q["customer"], {"id": 7, "name": "Jo Smith", "email": "jo@example.com"})
        self.assertEqual(q["job"], 32, "the newest job that isn't done")
        self.assertEqual(q["place_id"], PID)
        self.assertIn("due", q)
        self.assertEqual(Path(str(self.book) + ".done").read_text(), "32\n")
        self.assertIn("Queued: Jo Smith", r.stdout)
        self.assertIn("j…@example.com", r.stdout, "the address is masked in what the owner reads")
        self.assertIn("90 days", r.stdout)

    def test_two_matches_no_match_and_no_email_each_refuse_with_the_reason(self):
        r = self.run_gbp("ask", "Smith")
        self.assertEqual(r.returncode, 3)
        self.assertIn("More than one customer", r.stdout)
        r = self.run_gbp("ask", "Nobody")
        self.assertEqual(r.returncode, 3)
        self.assertIn("Nobody in the customer book", r.stdout)
        r = self.run_gbp("ask", "Nomail")
        self.assertEqual(r.returncode, 3)
        self.assertIn("never gave the business one", r.stdout)
        self.assertEqual(self.queue(), [], "a refusal queues nothing")
        self.assertFalse(Path(str(self.book) + ".done").exists(), "and marks nothing done")

    def test_no_place_id_refuses_before_anything_is_touched(self):
        (self.ws / "NOTES.md").write_text("# Notes\n")
        r = self.run_gbp("ask", "Jo Smith")
        self.assertEqual(r.returncode, 3)
        self.assertIn("no Google place id in NOTES.md", r.stdout)
        self.assertEqual(self.queue(), [])

    def test_the_relays_mirror_stops_a_second_ask_inside_90_days_and_a_stopped_customer(self):
        import datetime as dt
        asked = dt.date.today() - dt.timedelta(days=5)
        (self.ws / "reviews").mkdir()
        (self.ws / "reviews" / "status.json").write_text(json.dumps(
            {"asked": {"jo@example.com": f"{asked}T10:00:00+00:00"}, "stopped": ["sam@example.com"]}))
        r = self.run_gbp("ask", "Jo Smith")
        self.assertEqual(r.returncode, 3)
        self.assertIn(f"not again before {asked + dt.timedelta(days=90)}", r.stdout)
        r = self.run_gbp("ask", "Sam")
        self.assertEqual(r.returncode, 3)
        self.assertIn("asked not to be contacted", r.stdout)
        self.assertEqual(self.queue(), [])

    def test_stop_and_cancel_file_their_own_lines(self):
        self.assertEqual(self.run_gbp("ask", "Jo Smith", "--cancel").returncode, 0)
        r = self.run_gbp("ask", "someone@else.com", "--stop", "--why", "replied STOP")
        self.assertEqual(r.returncode, 0, r.stderr)
        ops = [(q["op"], q["customer"]["email"]) for q in self.queue()]
        self.assertEqual(ops, [("cancel", "jo@example.com"), ("stop", "someone@else.com")])
        self.assertEqual(self.queue()[1]["why"], "replied STOP")

    def test_dry_run_files_nothing_and_marks_nothing(self):
        r = self.run_gbp("--dry-run", "ask", "Jo Smith")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would queue", r.stdout)
        self.assertIn(f"writereview?placeid={PID}", r.stdout)
        self.assertEqual(self.queue(), [])
        self.assertFalse(Path(str(self.book) + ".done").exists())

    def test_asks_shows_filed_and_the_relays_word(self):
        self.run_gbp("ask", "Jo Smith")
        (self.ws / "reviews" / "status.json").write_text(json.dumps({"updated": "2026-10-05T16:00:00+00:00", "asks": [
            {"name": "Lee", "state": "refused", "reason": "patchlamp.com can't send it yet", "due": "2026-10-05T15:00"}]}))
        r = self.run_gbp("asks")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("filed     Jo Smith", r.stdout)
        self.assertIn("refused   Lee", r.stdout)
        self.assertIn("can't send it yet", r.stdout)

    # -- watch -----------------------------------------------------------------------------

    def test_watch_reads_places_once_writes_one_ledger_line_and_keeps_the_copy(self):
        r = self.run_gbp("watch", "--json", "--fresh")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual((got["source"], got["rating"], got["count"]), ("places", 4.8, 23))
        self.assertEqual([x["id"] for x in got["reviews"]], ["r1", "r2"])
        self.assertEqual(got["reviews"][1]["text"], "Late twice.", "the original text over the translation")
        self.assertIsNone(got["reviews"][0]["replied"], "Places doesn't know about owner replies")
        self.assertEqual(len(Places.hits), 1)
        self.assertTrue(Places.hits[0][0].endswith(PID))
        [row] = [json.loads(x) for x in self.ledger.read_text().splitlines()]
        self.assertEqual((row["kind"], row["tool"], row["calls"], row["cost_usd"]), ("places_details", "gbp watch", 1, 0.025))
        self.assertTrue((self.ws / "reviews" / "latest.json").exists())
        # a second read inside 20 hours is the copy: no call, no ledger line
        r = self.run_gbp("watch")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("4.8★ from 23 reviews", r.stdout)
        self.assertIn("the daily watch's copy", r.stdout)
        self.assertEqual(len(Places.hits), 1)
        self.assertEqual(len(self.ledger.read_text().splitlines()), 1)

    def test_watch_in_a_walled_run_without_the_key_gives_the_relays_copy_or_says_why(self):
        r = self.run_gbp("watch", "--fresh", extra={"GOOGLE_MAPS_API_KEY": ""})
        self.assertEqual(r.returncode, 3)
        self.assertIn("no Places key here", r.stdout)
        (self.ws / "reviews").mkdir()
        (self.ws / "reviews" / "latest.json").write_text(json.dumps(
            {"source": "places", "rating": 4.7, "count": 22, "reviews": [], "at": "2026-10-01T09:00:00+00:00"}))
        r = self.run_gbp("watch", "--fresh", extra={"GOOGLE_MAPS_API_KEY": ""})
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("4.7★ from 22", r.stdout)
        self.assertEqual(Places.hits, [])

    def test_watch_falls_back_to_places_when_google_says_quota_zero(self):
        fx = Path(self.tmp.name) / "fx"
        fx.mkdir()
        (fx / "q.json").write_text(json.dumps({"error": {"code": 403, "message": "Quota exceeded: quota is 0"}}))
        (fx / "routes.json").write_text(json.dumps({"GET /v4/accounts/104/locations/129/reviews": {"status": 403, "file": "q.json"}}))
        r = self.run_gbp("watch", "--json", "--fresh", creds=True, extra={"GBP_FIXTURES": str(fx)})
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["source"], "places")
        self.assertIn("quota is 0", " ".join(got["why"]))

    def test_watch_by_the_api_knows_which_are_unanswered(self):
        r = self.run_gbp("watch", "--json", "--fresh", creds=True,
                         extra={"GBP_FIXTURES": str(HERE / "fixtures" / "gbp")})
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got["source"], "gbp")
        self.assertIn(False, [x["replied"] for x in got["reviews"]])
        self.assertIn(True, [x["replied"] for x in got["reviews"]])
        self.assertEqual(Places.hits, [], "no Places call when the API answered")

    # -- reply at quota 0 ----------------------------------------------------------------------

    def test_reply_is_refused_cleanly_at_quota_zero_and_the_draft_comes_back(self):
        fx = Path(self.tmp.name) / "fx"
        fx.mkdir()
        (fx / "q.json").write_text(json.dumps({"error": {"code": 403, "message": "Quota exceeded: quota is 0"}}))
        (fx / "routes.json").write_text(json.dumps({
            "GET /v4/accounts/104/locations/129/reviews": {"status": 403, "file": "q.json"},
            "PUT /v4/accounts/104/locations/129/reviews/r1/reply": {"status": 403, "file": "q.json"}}))
        for which in ("1", "r1"):
            r = self.run_gbp("reply", which, "Thanks Maria, glad it's warm again.", creds=True,
                             extra={"GBP_FIXTURES": str(fx)})
            self.assertEqual(r.returncode, 3, r.stderr)
            self.assertIn("Not posted", r.stdout)
            self.assertIn("nothing was changed", r.stdout)
            self.assertIn("Thanks Maria, glad it's warm again.", r.stdout)
            self.assertIn("business.google.com", r.stdout)
            self.assertEqual(r.stderr, "")

    def test_doctor_names_the_place_id_and_the_book(self):
        r = self.run_gbp("doctor")
        self.assertIn(f"place id (NOTES.md): {PID}", r.stdout)
        self.assertIn("writereview?placeid=", r.stdout)
        self.assertIn("customer book: found", r.stdout)
        self.assertEqual(r.returncode, 1, "still no connection: doctor says so after the review lines")


if __name__ == "__main__":
    unittest.main()
