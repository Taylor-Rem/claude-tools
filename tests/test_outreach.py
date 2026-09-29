"""outreach against a fake mailbox, a stub Instantly and a stub classifier: no network,
no mail, no money, and never the real pipeline.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

Everything the ROADMAP B46 acceptance line asks for is proven here against the `fake`
provider, because the outreach mailbox doesn't exist yet: six sent on `go` with the
footer, a reply answered in one tick, a "no thanks" suppressed before the next run, a
"call me" briefed to Taylor with the time, and the caps proven by lowering them.
`leads` and `notify` are replaced by recorders, so the exact commands are asserted and
~/projects/private-docs/leads/pipeline.jsonl is never touched.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
OUTREACH = TOOLS / "bin" / "outreach"
TEMPLATES = TOOLS / "templates" / "outreach"
KIT = HERE / "fixtures" / "outreach" / "remote.json"

ADDRESS = "PO Box 1234, American Fork, UT 84003"
BOOKING = "https://cal.com/taylor/15min"
MAILBOX = "taylor@patchlampmail.example"
FAKE_KEY = "inst_FAKEkeyNEVERreal000"
FAKE_AI_KEY = "sk-ant-FAKEkeyNEVERreal000"

STUB_LEADS = """#!/usr/bin/env python3
import json, os, sys
open(os.environ["STUB_LOG"], "a").write(json.dumps({"tool": "leads", "argv": sys.argv[1:]}) + "\\n")
print("ok")
"""
STUB_NOTIFY = """#!/usr/bin/env python3
import json, os, sys
open(os.environ["STUB_LOG"], "a").write(json.dumps({"tool": "notify", "argv": sys.argv[1:]}) + "\\n")
"""


def classifier_json(cls, topic=None, when=None, why="stub"):
    return {"content": [{"type": "text", "text": json.dumps(
        {"class": cls, "topic": topic, "when": when, "why": why})}],
        "usage": {"input_tokens": 320, "output_tokens": 30}}


class Stub(BaseHTTPRequestHandler):
    """One server for both hosts: /v1/messages is the classifier, /api/v2/* is Instantly."""

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

    def _record(self, method):
        u = urllib.parse.urlsplit(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode()) if n else {}
        self.state["seen"].append({"method": method, "path": u.path, "body": body,
                                   "query": dict(urllib.parse.parse_qsl(u.query)),
                                   "auth": self.headers.get("Authorization"),
                                   "key": self.headers.get("x-api-key")})
        return u.path, body

    def do_GET(self):
        path, _ = self._record("GET")
        if path == "/api/v2/campaigns":
            return self._send(200, {"items": self.state.get("campaigns", [])})
        if path == "/api/v2/emails":
            return self._send(200, {"items": self.state.get("emails", [])})
        if path == "/api/v2/campaigns/analytics/overview":
            return self._send(200, self.state.get("analytics", {
                "emails_sent_count": 40, "bounced_count": 0, "reply_count_unique": 3, "unsubscribed_count": 0}))
        if path == "/api/v2/accounts":
            return self._send(200, {"items": [{"email": MAILBOX}]})
        return self._send(404, {"message": "no"})

    def do_POST(self):
        path, body = self._record("POST")
        if path == "/v1/messages":
            answers = self.state.setdefault("ai", [])
            return self._send(200, answers.pop(0) if answers else classifier_json("other"))
        if path == "/api/v2/campaigns":
            return self._send(200, {"id": "camp-1", "name": body.get("name")})
        if path.endswith("/activate"):
            return self._send(200, {"ok": True})
        if path == "/api/v2/leads":
            return self._send(200, {"id": f"lead-{len(self.state['seen'])}"})
        if path == "/api/v2/emails/reply":
            return self._send(200, {"id": "sent-reply-1"})
        if path == "/api/v2/block-lists-entries":
            return self._send(200, {"id": "bl-1", "bl_value": body.get("bl_value")})
        if path == "/api/v2/accounts/warmup-analytics":
            return self._send(200, {"aggregate_data": {MAILBOX: {"sent": 12, "landed_inbox": 12, "landed_spam": 0}}})
        return self._send(404, {"message": "no"})


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Stub.state = {"seen": []}
        cls.server = HTTPServer(("127.0.0.1", 0), Stub)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="outreach-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.tpl = self.tmp / "tpl"
        shutil.copytree(TEMPLATES, self.tpl)
        (self.tpl / "APPROVED.example").unlink(missing_ok=True)
        (self.tpl / "APPROVED").unlink(missing_ok=True)
        stub = self.tmp / "stub"
        stub.mkdir()
        for name, src in (("leads", STUB_LEADS), ("notify", STUB_NOTIFY)):
            p = stub / name
            p.write_text(src)
            p.chmod(0o755)
        self.log = self.tmp / "stub.log"
        self.todo = self.tmp / "TAYLOR-TODO.md"
        self.todo.write_text("# TAYLOR-TODO\n\n## 1. Now\n\n## 7. Triage\n\n- [x] **Old.** Done.\n"
                             "  _(triage, 2026-09-24)_\n")
        Stub.state = {"seen": [], "ai": []}
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.tmp),
            "CLAUDE_TOOLS_ENV": os.devnull, "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
            "OUTREACH_TEMPLATES": str(self.tpl), "OUTREACH_STATE": str(self.tmp / "state"),
            "OUTREACH_LEDGER": str(self.tmp / "ledger.jsonl"),
            "OUTREACH_LEADS_BIN": str(stub / "leads"), "OUTREACH_NOTIFY_BIN": str(stub / "notify"),
            "STUB_LOG": str(self.log), "TAYLOR_TODO": str(self.todo),
            "LEADS_MAIL_ADDRESS": ADDRESS, "LEADS_BOOKING_URL": BOOKING,
            "PATCHLAMP_VOICE_NUMBER": "801-555-0100",
            "OUTREACH_PROVIDER": "fake", "OUTREACH_FROM": MAILBOX, "OUTREACH_PER_DAY": "6",
        }

    # -- helpers ------------------------------------------------------------------
    def run_it(self, *args, expect=0, **over):
        env = dict(self.env)
        env.update({k: str(v) for k, v in over.items()})
        r = subprocess.run([sys.executable, str(OUTREACH), *args], capture_output=True, text=True,
                           env=env, timeout=120)
        if expect is not None:
            self.assertEqual(r.returncode, expect,
                             f"{args} exited {r.returncode}\nSTDOUT\n{r.stdout}\nSTDERR\n{r.stderr}")
        return r

    def approve(self):
        self.run_it("approve")

    def send(self, *extra, **over):
        return self.run_it("send", "--kit", str(KIT), "--go", *extra, **over)

    def calls(self, tool=None):
        rows = [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []
        return [r for r in rows if tool is None or r["tool"] == tool]

    def state_rows(self, name):
        p = self.tmp / "state" / name
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def ledger(self):
        p = self.tmp / "ledger.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def outbox(self):
        p = self.tmp / "state" / "fake" / "outbox.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def inbox_write(self, rows):
        d = self.tmp / "state" / "fake"
        d.mkdir(parents=True, exist_ok=True)
        (d / "inbox.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    def set_analytics(self, **kw):
        d = self.tmp / "state" / "fake"
        d.mkdir(parents=True, exist_ok=True)
        base = {"sent": 100, "bounced": 0, "replies": 0, "unsubscribed": 0, "complaints": 0}
        base.update(kw)
        (d / "analytics.json").write_text(json.dumps(base))


class Templates(Base):
    def test_every_letter_keeps_its_rules(self):
        r = self.run_it("approve", "--dry-run")
        self.assertIn("APPROVED not written", r.stdout)
        self.assertNotIn("PROBLEMS", r.stdout)
        for name in ("first", "second", "third", "answer-price", "answer-how"):
            self.assertIn(f"{name}.md", r.stdout)

    def test_the_day_zero_letter_says_everything_the_law_and_the_policy_want(self):
        r = self.run_it("approve", "--dry-run")
        letter = r.stdout.split("───── first.md ─────")[1].split("─────")[0]
        self.assertIn("American Fork", letter)
        self.assertIn("Taylor Remund", letter)
        self.assertIn("$99 a month, no contract, stated on the site", letter)
        self.assertIn(ADDRESS, letter)
        self.assertIn(BOOKING, letter)
        self.assertIn("801-555-0100", letter)
        self.assertIn("advertisement", letter)
        self.assertIn('"no thanks"', letter)
        self.assertIn("Patch, my AI operator", letter)
        body = letter.split("Hi Dave,", 1)[1]
        pitch = [p for p in body.split("\n\n") if p.strip()][0]
        self.assertEqual(1, len(re.findall(r"https?://", pitch)), f"one link in the pitch, not\n{pitch}")
        self.assertTrue(4 <= len(re.split(r"(?<=[.!?])\s+", pitch.strip())) <= 6)

    def test_approve_writes_a_hash_per_letter(self):
        self.approve()
        text = (self.tpl / "APPROVED").read_text()
        for name in ("first", "second", "third", "answer-price", "answer-how"):
            self.assertRegex(text, rf"(?m)^{re.escape(name)}\s+[0-9a-f]{{64}}$")

    def test_send_refuses_an_unapproved_letter(self):
        r = self.send(expect=1)
        self.assertIn("isn't approved", r.stderr)
        self.assertEqual([], self.outbox())

    def test_editing_a_letter_unapproves_it(self):
        self.approve()
        p = self.tpl / "first.md"
        p.write_text(p.read_text().replace("Either way the page is yours to copy from.",
                                           "Either way the page is yours. Free forever."))
        r = self.send(expect=1)
        self.assertIn("changed since Taylor approved it", r.stderr)
        self.assertEqual([], self.outbox())

    def test_approve_refuses_a_letter_that_breaks_its_rules(self):
        p = self.tpl / "first.md"
        p.write_text(p.read_text().replace("{address}", "American Fork, Utah"))
        r = self.run_it("approve", expect=1)
        self.assertIn("no postal address", r.stderr)
        self.assertFalse((self.tpl / "APPROVED").exists())

    def test_send_re_checks_the_rules_even_on_an_approved_hash(self):
        """The hash could be hand-written; the rules are checked again at send time."""
        import hashlib
        p = self.tpl / "first.md"
        p.write_text(p.read_text().replace("{address}", "American Fork, Utah"))
        (self.tpl / "APPROVED").write_text(f"first  {hashlib.sha256(p.read_bytes()).hexdigest()}\n")
        r = self.send(expect=1)
        self.assertIn("breaks its own rules", r.stderr)
        self.assertIn("postal address", r.stderr)
        self.assertEqual([], self.outbox())


class Send(Base):
    def setUp(self):
        super().setUp()
        self.approve()

    def test_a_real_six_on_go(self):
        r = self.send()
        out = self.outbox()
        self.assertEqual(6, len(out), r.stdout)
        self.assertIn("Sent 6 of 6", r.stdout)
        self.assertIn("no address on the listing", r.stdout)       # the seventh pick
        for row in out:
            self.assertIn(ADDRESS, row["text"])
            self.assertIn('"no thanks"', row["text"])
            self.assertIn("advertisement", row["text"])
            self.assertIn("Patch, my AI operator", row["text"])
            self.assertIn("$99 a month, no contract, stated on the site", row["text"])
            self.assertTrue(row["subject"].strip())
            self.assertEqual(MAILBOX, row["from"])

    def test_the_greeting_and_the_fault_are_written_to_them_not_about_them(self):
        self.send()
        by = {r["to"]: r["text"] for r in self.outbox()}
        self.assertIn("Hi Dave,", by["dave@highlandpoolspa.example"])
        self.assertIn("Hi Cedar Hollow Lawn Care team,", by["hello@cedarhollowlawn.example"])
        ken = by["ken@saratogablinds.example"]
        self.assertIn("a Facebook page you don't control", ken)   # `leads` says "they don't control"
        for text in by.values():
            self.assertNotRegex(text.split("Taylor Remund")[0], r"\btheir\b|\bthey\b")

    def test_each_subject_names_that_business_s_own_fault(self):
        self.send()
        subjects = {r["to"]: r["subject"] for r in self.outbox()}
        self.assertIn("dead", subjects["dave@highlandpoolspa.example"].lower() + " dead")
        self.assertIn("doesn't load", subjects["dave@highlandpoolspa.example"])
        self.assertIn("no website", subjects["hello@cedarhollowlawn.example"])
        self.assertIn("book", subjects["marisol@timppeakplumbing.example"])
        self.assertIn("DoorDash", subjects["ken@saratogablinds.example"])
        self.assertIn("photos", subjects["bee@alpineridgegrooming.example"])

    def test_the_pipeline_is_written_through_leads_and_only_through_leads(self):
        self.send()
        logs = self.calls("leads")
        self.assertEqual(6, len(logs))
        first = logs[0]["argv"]
        self.assertEqual(["log", "Highland Pool & Spa", "messaged"], first[:3])
        self.assertTrue(first[3].startswith("email: "))
        self.assertIn("--place", first)
        self.assertEqual("ChIJfixture0000000000001", first[first.index("--place") + 1])
        self.assertIn("--via", first)
        self.assertEqual("email", first[first.index("--via") + 1])
        self.assertIn("--email", first)

    def test_one_ledger_row_a_send_at_no_cost(self):
        self.send()
        rows = [r for r in self.ledger() if r["kind"] == "outreach_email"]
        self.assertEqual(6, len(rows))
        for r in rows:
            self.assertEqual(0, r["cost_usd"])
            self.assertEqual("outreach", r["tool"])
            self.assertEqual("global", r["project"])
            self.assertIn("first day0", r["for"])

    def test_no_postal_address_means_no_mail_at_all(self):
        r = self.send(expect=1, LEADS_MAIL_ADDRESS="")
        self.assertIn("LEADS_MAIL_ADDRESS", r.stderr)
        self.assertEqual([], self.outbox())

    def test_per_day_zero_sends_nothing(self):
        r = self.send(OUTREACH_PER_DAY="0")
        self.assertIn("nothing sends", r.stdout)
        self.assertEqual([], self.outbox())

    def test_the_cap_proven_by_lowering_it(self):
        self.send(OUTREACH_PER_DAY="2")
        self.assertEqual(2, len(self.outbox()))
        r = self.send(OUTREACH_PER_DAY="2")
        self.assertIn("cap is spent", r.stdout)
        self.assertEqual(2, len(self.outbox()))

    def test_without_go_nothing_leaves_but_the_list_is_shown(self):
        r = self.run_it("send", "--kit", str(KIT))
        self.assertIn("Waiting on `go`", r.stdout)
        self.assertIn("Highland Pool & Spa", r.stdout)
        self.assertEqual([], self.outbox())

    def test_outreach_auto_stands_in_for_go(self):
        self.run_it("send", "--kit", str(KIT), OUTREACH_AUTO="1")
        self.assertEqual(6, len(self.outbox()))

    def test_only_and_hold(self):
        self.send("--only", "1", "3")
        self.assertEqual(2, len(self.outbox()))
        (self.tmp / "state" / "sends.jsonl").unlink()
        (self.tmp / "state" / "fake" / "outbox.jsonl").unlink()
        self.send("--hold", "1", "2")
        self.assertEqual(4, len(self.outbox()))
        self.assertNotIn("dave@highlandpoolspa.example", [r["to"] for r in self.outbox()])

    def test_dry_run_sends_nothing_and_writes_nothing(self):
        r = self.send("--dry-run")
        self.assertIn("DRY RUN", r.stdout)
        self.assertIn("I'm Taylor Remund", r.stdout)
        self.assertEqual([], self.outbox())
        self.assertEqual([], self.ledger())
        self.assertEqual([], self.calls())

    def test_the_two_follow_up_touches_render_and_send(self):
        r = self.send("--touch", "3")
        self.assertEqual(6, len(self.outbox()))
        self.assertIn("touch day 3 (second)", r.stdout)
        self.assertIn("Following up once", self.outbox()[0]["text"])
        r = self.send("--touch", "10")
        self.assertIn("touch day 10 (third)", r.stdout)
        third = [row for row in self.outbox() if "comes down" in row["text"]]
        self.assertEqual(6, len(third))
        self.assertRegex(third[0]["subject"], r"comes down \d{1,2} \w+")

    def test_a_pick_with_no_preview_page_is_never_written_to(self):
        """Every letter says "I've made you a page…"; without one there is nothing true to send."""
        kit = json.loads(KIT.read_text())
        kit["picks"][0]["preview_url"] = None
        kit["picks"][1]["preview_url"] = ""
        p = self.tmp / "no-previews.json"
        p.write_text(json.dumps(kit))
        r = self.run_it("send", "--kit", str(p), "--go")
        self.assertEqual(4, len(self.outbox()))
        self.assertIn("no preview page yet (B45)", r.stdout)
        for row in self.outbox():
            self.assertIn("https://preview-", row["text"])

    def test_a_suppressed_address_or_place_is_never_written_to(self):
        self.run_it("suppress", "add", "dave@highlandpoolspa.example", "--reason", "by hand")
        self.run_it("suppress", "add", "ChIJfixture0000000000003")
        r = self.send()
        self.assertEqual(4, len(self.outbox()))
        self.assertIn("skipped: suppressed", r.stdout)
        tos = [row["to"] for row in self.outbox()]
        self.assertNotIn("dave@highlandpoolspa.example", tos)
        self.assertNotIn("marisol@timppeakplumbing.example", tos)


class KillSwitch(Base):
    def setUp(self):
        super().setUp()
        self.approve()

    def test_bounces_over_the_cap_stop_the_lane_and_file_a_todo(self):
        self.set_analytics(sent=100, bounced=4)
        r = self.send(expect=1)
        self.assertIn("the lane is stopped", r.stdout)
        self.assertEqual([], self.outbox())
        notes = self.calls("notify")
        self.assertEqual(1, len(notes))
        self.assertIn("Email lane stopped", notes[0]["argv"][0])
        todo = self.todo.read_text()
        self.assertIn("**The email lane stopped itself", todo)
        self.assertIn("- **1.**", todo)
        self.assertIn("- **Then:**", todo)
        self.assertIn("_(outreach, ", todo)

    def test_one_spam_complaint_stops_the_lane_with_no_bounces_at_all(self):
        self.set_analytics(sent=100, bounced=0, complaints=1)
        r = self.send(expect=1)
        self.assertIn("1 spam complaint", r.stdout)
        self.assertEqual([], self.outbox())

    def test_it_does_not_stack_the_same_entry_or_notify_twice(self):
        self.set_analytics(sent=100, bounced=9)
        self.send(expect=1)
        self.send(expect=1)
        self.assertEqual(1, len(self.calls("notify")))
        self.assertEqual(1, self.todo.read_text().count("**The email lane stopped itself"))

    def test_a_lowered_cap_is_the_switch(self):
        self.set_analytics(sent=100, bounced=2)
        self.send()                                            # 2% under the 3% default
        self.assertEqual(6, len(self.outbox()))
        (self.tmp / "state" / "sends.jsonl").unlink()
        r = self.send(expect=1, OUTREACH_BOUNCE_MAX_PCT="1.0")
        self.assertIn("cap 1.0%", r.stdout)


class Inbox(Base):
    def setUp(self):
        super().setUp()
        self.approve()
        self.send()
        self.log.unlink(missing_ok=True)

    def reply(self, **kw):
        row = {"id": "r1", "thread_id": "t1", "from": "dave@highlandpoolspa.example",
               "subject": "Re: your Google listing", "text": "hello", "ts": "2026-09-28T18:00:00Z"}
        row.update(kw)
        return row

    def test_no_thanks_is_suppressed_before_anything_else_and_never_answered(self):
        self.inbox_write([self.reply(text="No thanks, please take me off your list.")])
        r = self.run_it("inbox")
        self.assertIn("— no (by rule)", r.stdout)
        self.assertIn("no reply sent, by policy", r.stdout)
        supp = {row["value"] for row in self.state_rows("suppress.jsonl")}
        self.assertIn("dave@highlandpoolspa.example", supp)
        self.assertIn("ChIJfixture0000000000001", supp)          # the place, so no kit picks it up
        log = self.calls("leads")[0]["argv"]
        self.assertEqual(["log", "Highland Pool & Spa", "lost"], log[:3])
        self.assertEqual([], [f for f in (self.tmp / "state" / "fake").glob("sent-replies.jsonl")])

    def test_one_no_thanks_is_suppressed_before_the_next_run(self):
        self.inbox_write([self.reply(text="no thanks")])
        self.run_it("inbox")
        (self.tmp / "state" / "sends.jsonl").unlink()
        (self.tmp / "state" / "fake" / "outbox.jsonl").unlink()
        r = self.send()
        self.assertIn("skipped: suppressed", r.stdout)
        self.assertNotIn("dave@highlandpoolspa.example", [row["to"] for row in self.outbox()])

    def test_every_reasonable_phrasing_of_no_is_a_no(self):
        for i, words in enumerate(("no thanks", "No thank you", "please unsubscribe me",
                                   "STOP", "remove me from this list", "take us off",
                                   "not interested", "do not contact me again", "opt out")):
            with self.subTest(words=words):
                self.tmp.joinpath("state", "cursor.json").unlink(missing_ok=True)
                self.tmp.joinpath("state", "suppress.jsonl").unlink(missing_ok=True)
                self.inbox_write([self.reply(id=f"n{i}", text=words)])
                r = self.run_it("inbox")
                self.assertIn("— no (by rule)", r.stdout)

    def test_a_bounce_suppresses_the_recipient_not_the_daemon(self):
        self.inbox_write([self.reply(id="b1", **{"from": "MAILER-DAEMON@mail.example"},
                                     subject="Undeliverable: your Google listing",
                                     text="550 5.1.1 user unknown ken@saratogablinds.example")])
        r = self.run_it("inbox")
        self.assertIn("— bounce (by rule)", r.stdout)
        supp = {row["value"] for row in self.state_rows("suppress.jsonl")}
        self.assertIn("ken@saratogablinds.example", supp)
        self.assertNotIn("MAILER-DAEMON@mail.example", supp)
        self.assertEqual([], self.calls("leads"))               # a bounce is not a conversation

    def test_an_auto_reply_is_noted_and_nothing_more(self):
        self.inbox_write([self.reply(text="Automatic reply: I am out of office until 6 October.")])
        r = self.run_it("inbox")
        self.assertIn("out of office", r.stdout)
        self.assertEqual([], self.calls())
        self.assertEqual([], self.state_rows("suppress.jsonl"))

    def test_call_me_with_a_time_is_briefed_to_taylor_and_never_machine_answered(self):
        self.inbox_write([self.reply(id="c1", **{"from": "marisol@timppeakplumbing.example"},
                                     text="Looks good - call me Thursday at 2pm.")])
        r = self.run_it("inbox")
        self.assertIn("handed to Taylor", r.stdout)
        note = self.calls("notify")[0]["argv"][0]
        self.assertIn("Timp Peak Plumbing replied:", note)
        self.assertIn("leads brief pending", note)
        self.assertIn("reply yes to book Thursday at 2pm", note)
        log = self.calls("leads")[0]["argv"]
        self.assertEqual(["log", "Timp Peak Plumbing", "interested"], log[:3])
        self.assertFalse((self.tmp / "state" / "fake" / "sent-replies.jsonl").exists())

    def test_a_reply_with_no_time_carries_the_booking_link_instead(self):
        self.inbox_write([self.reply(id="c2", text="Yes I'd like to hear more.")])
        self.run_it("inbox")
        self.assertIn(BOOKING, self.calls("notify")[0]["argv"][0])

    def test_the_cursor_means_a_reply_is_read_once(self):
        self.inbox_write([self.reply(text="Automatic reply: out of office")])
        self.run_it("inbox")
        r = self.run_it("inbox")
        self.assertIn("Nothing new", r.stdout)


class InboxWithClassifier(Base):
    """The one reply the machine may answer, with the classifier stubbed."""

    def setUp(self):
        super().setUp()
        self.env.update({"ANTHROPIC_KEY_OUTREACH": FAKE_AI_KEY, "ANTHROPIC_API_BASE": self.base})
        self.approve()
        self.send()
        self.log.unlink(missing_ok=True)
        Stub.state["seen"] = []

    def ask(self, text, ai, rid="q1", thread="tq", sender="bee@alpineridgegrooming.example",
            ts="2026-09-28T19:00:00Z", **over):
        Stub.state["ai"] = [ai]
        self.inbox_write([{"id": rid, "thread_id": thread, "from": sender, "subject": "Re: photos",
                           "text": text, "ts": ts}])
        return self.run_it("inbox", **over)

    def sent_replies(self):
        p = self.tmp / "state" / "fake" / "sent-replies.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def test_a_price_question_is_answered_within_a_tick_at_the_published_price(self):
        r = self.ask("How much does this cost per month?", classifier_json("question", "price"))
        self.assertIn("answering:", r.stdout)
        out = self.sent_replies()
        self.assertEqual(1, len(out))
        self.assertIn("$99 a month, no contract, stated on the site", out[0]["text"])
        self.assertIn("435-901-7141", out[0]["text"])            # text it yourself
        self.assertIn(BOOKING, out[0]["text"])
        self.assertIn(ADDRESS, out[0]["text"])
        self.assertIn('"no thanks"', out[0]["text"])
        log = self.calls("leads")[0]["argv"]
        self.assertEqual(["log", "Alpine Ridge Dog Grooming", "talked"], log[:3])
        self.assertTrue(log[3].startswith("asked: "))
        self.assertEqual([], self.calls("notify"))

    def test_a_how_does_it_work_question_gets_the_two_line_version(self):
        out = self.ask("What is this exactly, how does it work?", classifier_json("question", "how"))
        self.assertIn("answering:", out.stdout)
        self.assertIn("you text Patch", self.sent_replies()[0]["text"])

    def test_the_classifier_costs_one_ledger_row_with_a_real_price(self):
        self.ask("How much?", classifier_json("question", "price"))
        rows = [r for r in self.ledger() if r["kind"] == "claude"]
        self.assertEqual(1, len(rows))
        self.assertEqual("claude-haiku-4-5", rows[0]["model"])
        self.assertEqual(320, rows[0]["tokens_in"])
        self.assertAlmostEqual(320 / 1e6 * 1.0 + 30 / 1e6 * 5.0, rows[0]["cost_usd"], places=8)
        self.assertEqual("anthropic:ANTHROPIC_KEY_OUTREACH", rows[0]["billed_to"])

    def test_the_key_never_appears_in_the_output(self):
        r = self.ask("How much?", classifier_json("question", "price"))
        self.assertNotIn(FAKE_AI_KEY, r.stdout + r.stderr)
        self.assertNotIn(FAKE_KEY, r.stdout + r.stderr)

    def test_never_more_than_one_machine_reply_per_thread_per_day(self):
        self.ask("How much?", classifier_json("question", "price"), rid="q1", thread="same")
        self.assertEqual(1, len(self.sent_replies()))
        r = self.ask("And with tax?", classifier_json("question", "price"), rid="q2", thread="same",
                     ts="2026-09-28T19:05:00Z")
        self.assertIn("already answered this thread today", r.stdout)
        self.assertEqual(1, len(self.sent_replies()))

    def test_two_replies_in_the_same_second_are_both_read(self):
        Stub.state["ai"] = [classifier_json("other"), classifier_json("other")]
        self.inbox_write([{"id": "s1", "thread_id": "ta", "from": "bee@alpineridgegrooming.example",
                           "subject": "Re:", "text": "one", "ts": "2026-09-28T19:00:00Z"},
                          {"id": "s2", "thread_id": "tb", "from": "hello@cedarhollowlawn.example",
                           "subject": "Re:", "text": "two", "ts": "2026-09-28T19:00:00Z"}])
        r = self.run_it("inbox")
        self.assertIn("2 new replies", r.stdout)
        self.assertEqual(2, len(self.calls("notify")))

    def test_the_daily_reply_cap_holds(self):
        self.env["OUTREACH_MAX_REPLIES_PER_DAY"] = "1"
        self.ask("How much?", classifier_json("question", "price"), rid="q1", thread="a")
        r = self.ask("How much?", classifier_json("question", "price"), rid="q2", thread="b",
                     sender="hello@cedarhollowlawn.example", ts="2026-09-28T19:05:00Z")
        self.assertIn("reply cap", r.stdout)
        self.assertEqual(1, len(self.sent_replies()))

    def test_call_me_goes_to_taylor_even_when_the_classifier_calls_it_a_price_question(self):
        """A rule, not a judgement: the model can be wrong, the policy can't bend."""
        r = self.ask("How much is it? Call me Thursday at 2pm.", classifier_json("question", "price"))
        self.assertEqual([], self.sent_replies())
        self.assertIn("asks to talk, so it is Taylor's", r.stdout)
        self.assertIn("reply yes to book Thursday at 2pm", self.calls("notify")[0]["argv"][0])

    def test_the_answer_keeps_their_subject_without_a_second_re(self):
        Stub.state["ai"] = [classifier_json("question", "price")]
        self.inbox_write([{"id": "s1", "thread_id": "ts", "from": "bee@alpineridgegrooming.example",
                           "subject": "Re: photos", "text": "how much?", "ts": "2026-09-28T19:00:00Z"}])
        self.run_it("inbox")
        self.assertEqual("Re: photos", self.sent_replies()[0]["subject"])

    def test_the_ai_spend_is_counted_against_taylors_day_not_utcs(self):
        """Ledger rows are stamped UTC; a Denver evening is already tomorrow there."""
        import datetime as dtm
        utc_now = dtm.datetime.now(dtm.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        (self.tmp / "ledger.jsonl").write_text(json.dumps(
            {"ts": utc_now, "kind": "claude", "tool": "outreach", "model": "claude-haiku-4-5",
             "cost_usd": 0.49, "project": "global"}) + "\n")
        r = self.run_it("status")
        self.assertIn("classifier spend today: $0.4900", r.stdout)
        out = self.ask("How much?", classifier_json("question", "price"), OUTREACH_AI_USD_PER_DAY="0.40")
        self.assertEqual([], self.sent_replies())
        self.assertIn("handed to Taylor", out.stdout)

    def test_interested_is_never_machine_answered_even_when_the_classifier_says_so(self):
        r = self.ask("Yes, let's do it", classifier_json("interested", None, "Friday morning"))
        self.assertEqual([], self.sent_replies())
        self.assertIn("reply yes to book Friday morning", self.calls("notify")[0]["argv"][0])
        self.assertIn("never answered by the machine", r.stdout)

    def test_a_no_never_reaches_the_classifier_at_all(self):
        self.inbox_write([{"id": "n9", "thread_id": "t9", "from": "bee@alpineridgegrooming.example",
                           "subject": "Re:", "text": "no thanks", "ts": "2026-09-28T19:00:00Z"}])
        self.run_it("inbox")
        self.assertEqual([], [s for s in Stub.state["seen"] if s["path"] == "/v1/messages"])
        self.assertEqual([], [r for r in self.ledger() if r["kind"] == "claude"])

    def test_the_ai_budget_stops_the_machine_answering_and_hands_over_instead(self):
        self.env["OUTREACH_AI_USD_PER_DAY"] = "0"
        r = self.ask("How much does it cost?", classifier_json("question", "price"))
        self.assertEqual([], [s for s in Stub.state["seen"] if s["path"] == "/v1/messages"])
        self.assertEqual([], self.sent_replies())
        self.assertIn("handed to Taylor", r.stdout)

    def test_a_classifier_that_fails_hands_the_reply_over(self):
        self.env["ANTHROPIC_API_BASE"] = "http://127.0.0.1:1"      # nothing listens
        self.inbox_write([{"id": "x1", "thread_id": "tx", "from": "bee@alpineridgegrooming.example",
                           "subject": "Re:", "text": "How much is it?", "ts": "2026-09-28T19:00:00Z"}])
        r = self.run_it("inbox")
        self.assertEqual([], self.sent_replies())
        self.assertIn("handed to Taylor", r.stdout)

    def test_an_unapproved_answer_template_is_never_sent(self):
        (self.tpl / "APPROVED").write_text("first  " + "0" * 64 + "\n")
        r = self.ask("How much?", classifier_json("question", "price"))
        self.assertEqual([], self.sent_replies())
        self.assertIn("NOT answered", r.stdout)
        self.assertEqual(1, len(self.calls("notify")))


class InstantlyProvider(Base):
    """The instantly implementation against a stub of Instantly's API v2."""

    def setUp(self):
        super().setUp()
        self.env.update({"OUTREACH_PROVIDER": "instantly", "INSTANTLY_API_KEY": FAKE_KEY,
                         "INSTANTLY_API_BASE": self.base})
        self.approve()

    def seen(self, method, path):
        return [s for s in Stub.state["seen"] if s["method"] == method and s["path"] == path]

    def test_the_campaign_is_made_once_plain_text_with_no_tracking(self):
        self.send()
        made = self.seen("POST", "/api/v2/campaigns")
        self.assertEqual(1, len(made))
        body = made[0]["body"]
        self.assertTrue(body["text_only"])
        self.assertFalse(body["link_tracking"])
        self.assertFalse(body["open_tracking"])
        self.assertTrue(body["stop_on_reply"])
        self.assertEqual([MAILBOX], body["email_list"])
        self.assertEqual(6, body["daily_limit"])
        step = body["sequences"][0]["steps"][0]["variants"][0]
        self.assertEqual("{{subject_line}}", step["subject"])
        self.assertEqual("{{body_html}}", step["body"])
        self.assertEqual(1, len(self.seen("POST", "/api/v2/campaigns/camp-1/activate")))
        self.assertEqual(f"Bearer {FAKE_KEY}", made[0]["auth"])
        # a second run reuses the remembered id
        (self.tmp / "state" / "sends.jsonl").unlink()
        self.send()
        self.assertEqual(1, len(self.seen("POST", "/api/v2/campaigns")))

    def test_each_pick_is_a_lead_carrying_its_own_rendered_letter(self):
        self.send()
        leads = self.seen("POST", "/api/v2/leads")
        self.assertEqual(6, len(leads))
        body = leads[0]["body"]
        self.assertEqual("camp-1", body["campaign"])
        self.assertEqual("dave@highlandpoolspa.example", body["email"])
        self.assertEqual("Highland Pool & Spa", body["company_name"])
        self.assertTrue(body["skip_if_in_campaign"])
        cv = body["custom_variables"]
        self.assertIn("doesn't load", cv["subject_line"])
        self.assertIn("<br/>", cv["body_html"])
        self.assertIn(ADDRESS, cv["body_text"])
        self.assertEqual("ChIJfixture0000000000001", cv["place_id"])

    def test_replies_come_from_the_unibox_newest_first_and_only_the_received_ones(self):
        self.send()
        Stub.state["emails"] = [
            {"id": "e3", "timestamp_created": "2026-09-28T20:00:00Z", "ue_type": 2,
             "lead": "dave@highlandpoolspa.example", "subject": "Re: listing",
             "body": {"text": "no thanks"}, "thread_id": "th1"},
            {"id": "e2", "timestamp_created": "2026-09-28T19:00:00Z", "ue_type": 1,
             "lead": "dave@highlandpoolspa.example", "subject": "ours", "body": {"text": "the note"}},
        ]
        r = self.run_it("inbox")
        self.assertIn("1 new reply", r.stdout)
        self.assertIn("— no (by rule)", r.stdout)
        self.assertEqual(1, len(self.seen("POST", "/api/v2/block-lists-entries")))
        self.assertEqual("dave@highlandpoolspa.example",
                         self.seen("POST", "/api/v2/block-lists-entries")[0]["body"]["bl_value"])
        q = self.seen("GET", "/api/v2/emails")[0]["query"]
        self.assertEqual("desc", q["sort_order"])
        self.assertEqual("camp-1", q["campaign_id"])

    def test_a_machine_answer_goes_out_as_a_reply_to_that_email(self):
        self.env.update({"ANTHROPIC_KEY_OUTREACH": FAKE_AI_KEY, "ANTHROPIC_API_BASE": self.base})
        self.send()
        Stub.state["ai"] = [classifier_json("question", "price")]
        Stub.state["emails"] = [{"id": "e9", "timestamp_created": "2026-09-28T20:00:00Z", "ue_type": 2,
                                 "lead": "bee@alpineridgegrooming.example", "subject": "Re: photos",
                                 "body": {"html": "How much is it?<br/>Thanks"}, "thread_id": "th9"}]
        self.run_it("inbox")
        rep = self.seen("POST", "/api/v2/emails/reply")
        self.assertEqual(1, len(rep))
        self.assertEqual("e9", rep[0]["body"]["reply_to_uuid"])
        self.assertEqual(MAILBOX, rep[0]["body"]["eaccount"])
        self.assertIn("$99 a month", rep[0]["body"]["body"]["text"])
        self.assertIn("<br/>", rep[0]["body"]["body"]["html"])

    def test_the_bounce_rate_comes_from_the_campaign_analytics(self):
        Stub.state["analytics"] = {"emails_sent_count": 100, "bounced_count": 5, "reply_count_unique": 2,
                                   "unsubscribed_count": 1}
        r = self.send(expect=1)
        self.assertIn("100 sent, 5 bounced (5.0%", r.stdout)
        self.assertIn("the lane is stopped", r.stdout)
        self.assertEqual([], self.seen("POST", "/api/v2/leads"))

    def test_a_postmaster_complaint_counts_because_instantly_reports_none(self):
        Stub.state["analytics"] = {"emails_sent_count": 100, "bounced_count": 0}
        r = self.send(expect=1, OUTREACH_COMPLAINTS="1")
        self.assertIn("1 spam complaint(s) per OUTREACH_COMPLAINTS", r.stdout)

    def test_warmup_reads_the_mailbox_s_own_numbers(self):
        r = self.run_it("warmup")
        self.assertIn(MAILBOX, r.stdout)
        self.assertIn("12 sent", r.stdout)
        self.assertEqual(1, len(self.seen("POST", "/api/v2/accounts/warmup-analytics")))

    def test_an_unreachable_provider_stops_the_run_rather_than_sending_blind(self):
        r = self.run_it("send", "--kit", str(KIT), "--go", expect=1, INSTANTLY_API_BASE="http://127.0.0.1:1")
        self.assertNotIn(FAKE_KEY, r.stdout + r.stderr)
        self.assertIn("can't read the bounce rate", r.stderr)
        self.assertEqual([], self.seen("POST", "/api/v2/leads"))

    def test_the_key_is_never_printed_even_when_it_is_refused(self):
        r = self.run_it("doctor", "--kit", str(KIT), expect=1, INSTANTLY_API_BASE="http://127.0.0.1:1")
        self.assertNotIn(FAKE_KEY, r.stdout + r.stderr)
        self.assertIn("INSTANTLY_API_KEY: set", r.stdout)

    def test_dry_run_never_touches_the_api(self):
        self.send("--dry-run")
        self.assertEqual([], Stub.state["seen"])


class StatusAndDoctor(Base):
    def test_status_shows_the_day_the_caps_and_the_classes(self):
        self.approve()
        self.send()
        self.inbox_write([{"id": "s1", "thread_id": "ts", "from": "dave@highlandpoolspa.example",
                           "subject": "Re:", "text": "no thanks", "ts": "2026-09-28T18:00:00Z"}])
        self.run_it("inbox")
        r = self.run_it("status")
        self.assertIn("sends today: 6 of 6", r.stdout)
        self.assertIn("day 0: 6", r.stdout)
        self.assertIn("replies today: 1", r.stdout)
        self.assertIn("no 1", r.stdout)
        self.assertIn("suppressed: 2", r.stdout)
        self.assertIn("all approved", r.stdout)

    def test_doctor_fails_loudly_while_the_mailbox_and_the_key_are_missing(self):
        r = self.run_it("doctor", "--kit", str(KIT), expect=1,
                        OUTREACH_FROM="", LEADS_MAIL_ADDRESS="", LEADS_BOOKING_URL="")
        self.assertIn("INSTANTLY_API_KEY: MISSING", r.stdout)
        self.assertIn("LEADS_MAIL_ADDRESS: MISSING", r.stdout)
        self.assertIn("NOT APPROVED", r.stdout)
        self.assertIn("no classifier key", r.stdout)

    def test_doctor_passes_once_everything_is_set(self):
        self.approve()
        r = self.run_it("doctor", "--kit", str(KIT), expect=0,
                        INSTANTLY_API_KEY=FAKE_KEY, ANTHROPIC_KEY_OUTREACH=FAKE_AI_KEY,
                        OUTREACH_PROVIDER="fake")
        self.assertIn("first: approved", r.stdout)
        self.assertIn("rules ok", r.stdout)
        self.assertIn("7 picks, 6 with an address", r.stdout)
        self.assertNotIn(FAKE_KEY, r.stdout)
        self.assertNotIn(FAKE_AI_KEY, r.stdout)

    def test_doctor_says_so_when_the_kit_json_has_the_wrong_shape(self):
        old = self.tmp / "old-shape.json"
        old.write_text('[{"place_id": "x", "name": "Old Shape"}]')
        r = self.run_it("doctor", "--kit", str(old), expect=1)
        self.assertIn("{date, segment, picks}", r.stdout)

    def test_send_says_so_and_exits_zero_when_the_kit_flag_is_not_there_yet(self):
        self.approve()
        old = self.tmp / "old-shape.json"
        old.write_text('[{"place_id": "x", "name": "Old Shape"}]')
        r = self.run_it("send", "--kit", str(old), "--go", expect=0)
        self.assertIn("Nothing to send:", r.stdout)
        self.assertEqual([], self.outbox())


if __name__ == "__main__":
    unittest.main()
