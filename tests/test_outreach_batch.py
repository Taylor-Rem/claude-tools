"""The batch lane (ROADMAP B90, plan ~/projects/plans/37-email-at-volume.md) against
in-process fake SMTP and IMAP servers on 127.0.0.1: nothing here connects to Google, to
Instantly or to a verifier, nothing is mailed, and `leads` / `notify` are recorders.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

The clock is OUTREACH_NOW, so a day of five-minute ticks runs in a few seconds.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads (tests/_offline.py)

import base64
import datetime as dt
import email
import email.policy
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import socketserver
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
BATCH = HERE / "fixtures" / "outreach" / "batch.json"
KIT = HERE / "fixtures" / "outreach" / "remote.json"

ADDRESS = "PO Box 1234, American Fork, UT 84003"
DOMAIN = "trypatchlamp.example"
BOXES = [f"taylor@{DOMAIN}", f"t.remund@{DOMAIN}", f"hello@{DOMAIN}"]
PASSWORDS = {b: f"app-pass-{i}-NEVERreal" for i, b in enumerate(BOXES)}
DISCLOSURE = "Patch, my AI operator, found this and drafted it; I approve each batch."
MONDAY = "2026-10-19"


def pw_name(addr):
    return "OUTREACH_APP_PASSWORD_" + re.sub(r"[^A-Z0-9]", "_", addr.upper())


STUB_LEADS = """#!/usr/bin/env python3
import json, os, sys
open(os.environ["STUB_LOG"], "a").write(json.dumps({"tool": "leads", "argv": sys.argv[1:]}) + "\\n")
if sys.argv[1:2] == ["preview"]:
    url = os.environ.get("STUB_PREVIEW_URL")
    if not url:
        print("leads: no such option --place", file=sys.stderr); sys.exit(2)
    print(json.dumps({"ok": True, "place_id": sys.argv[3], "url": url, "slug": "x", "name": "x",
                      "category": "Plumber", "city": "Lehi", "expires": "2026-11-18", "published": True}))
else:
    print("ok")
"""
STUB_PREP = """#!/usr/bin/env python3
import json, os, sys
open(os.environ["STUB_LOG"], "a").write(json.dumps({"tool": "prep", "argv": sys.argv[1:]}) + "\\n")
if "--dry-run" in sys.argv:
    print("prep one --dry-run: " + sys.argv[2] + " — nothing started")
else:
    print("Prep 2026-10-19-a: building " + sys.argv[2] + " — the outline comes by message")
"""
STUB_NOTIFY = """#!/usr/bin/env python3
import json, os, sys
open(os.environ["STUB_LOG"], "a").write(json.dumps({"tool": "notify", "argv": sys.argv[1:]}) + "\\n")
"""


# ---- the fake mail servers -------------------------------------------------------

class Mail:
    """What the fake servers share: messages sent, inboxes, and who may log in."""
    sent = []
    inbox = {}
    uidvalidity = 7
    lock = threading.Lock()

    @classmethod
    def reset(cls):
        with cls.lock:
            cls.sent = []
            cls.inbox = {b: [] for b in BOXES}

    @classmethod
    def deliver(cls, box, raw):
        with cls.lock:
            msgs = cls.inbox.setdefault(box, [])
            msgs.append((len(msgs) + 1, raw if isinstance(raw, bytes) else raw.encode()))


class FakeSMTP(socketserver.StreamRequestHandler):
    def w(self, line):
        self.wfile.write((line + "\r\n").encode())

    def handle(self):
        self.w("220 fake.smtp ESMTP")
        user, mfrom, rcpts = None, None, []
        while True:
            line = self.rfile.readline()
            if not line:
                return
            cmd = line.decode(errors="replace").strip()
            up = cmd.upper()
            if up.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250-fake.smtp\r\n250-AUTH PLAIN LOGIN\r\n250 8BITMIME\r\n")
            elif up.startswith("AUTH PLAIN"):
                parts = base64.b64decode(cmd.split()[2]).split(b"\0")
                u, p = parts[1].decode(), parts[2].decode()
                if PASSWORDS.get(u) == p:
                    user = u
                    self.w("235 ok")
                else:
                    self.w("535 5.7.8 bad credentials")
            elif up.startswith("MAIL FROM"):
                mfrom, rcpts = cmd.split(":", 1)[1].strip().strip("<>").split(">")[0], []
                self.w("250 ok")
            elif up.startswith("RCPT TO"):
                rcpts.append(cmd.split(":", 1)[1].strip().strip("<>"))
                self.w("250 ok")
            elif up == "DATA":
                self.w("354 go")
                data = []
                while True:
                    l = self.rfile.readline()
                    if l in (b".\r\n", b".\n", b""):
                        break
                    data.append(l[1:] if l.startswith(b"..") else l)
                with Mail.lock:
                    Mail.sent.append({"user": user, "from": mfrom, "to": rcpts, "raw": b"".join(data)})
                self.w("250 queued")
            elif up in ("RSET", "NOOP"):
                self.w("250 ok")
            elif up == "QUIT":
                self.w("221 bye")
                return
            else:
                self.w("502 no")


TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|(\S+)')


class FakeIMAP(socketserver.StreamRequestHandler):
    def w(self, line):
        self.wfile.write(line if isinstance(line, bytes) else (line + "\r\n").encode())

    def handle(self):
        self.w("* OK fake IMAP4rev1 ready")
        user = None
        while True:
            line = self.rfile.readline()
            if not line:
                return
            toks = [a or b for a, b in TOKEN.findall(line.decode(errors="replace").strip())]
            if len(toks) < 2:
                continue
            tag, cmd, args = toks[0], toks[1].upper(), toks[2:]
            if cmd == "CAPABILITY":
                self.w("* CAPABILITY IMAP4rev1 AUTH=PLAIN")
                self.w(f"{tag} OK done")
            elif cmd == "LOGIN":
                if PASSWORDS.get(args[0]) == args[1]:
                    user = args[0]
                    self.w(f"{tag} OK logged in")
                else:
                    self.w(f"{tag} NO [AUTHENTICATIONFAILED] bad")
            elif cmd in ("SELECT", "EXAMINE"):
                n = len(Mail.inbox.get(user, []))
                self.w(f"* {n} EXISTS")
                self.w(f"* OK [UIDVALIDITY {Mail.uidvalidity}] ok")
                self.w(f"{tag} OK [READ-ONLY] done")
            elif cmd == "UID" and args and args[0].upper() == "SEARCH":
                msgs = Mail.inbox.get(user, [])
                uids = [u for u, _ in msgs]
                crit = " ".join(args[1:]).upper()
                m = re.match(r"UID (\d+):\*", crit)
                if m:
                    lo = int(m.group(1))
                    uids = [u for u in uids if u >= lo] or ([uids[-1]] if uids else [])
                self.w("* SEARCH " + " ".join(str(u) for u in uids))
                self.w(f"{tag} OK search done")
            elif cmd == "UID" and args and args[0].upper() == "FETCH":
                uid = int(args[1])
                for i, (u, raw) in enumerate(Mail.inbox.get(user, []), 1):
                    if u == uid:
                        self.w(f"* {i} FETCH (UID {u} BODY[] {{{len(raw)}}}".encode() + b"\r\n" + raw + b")\r\n")
                self.w(f"{tag} OK fetch done")
            elif cmd == "LOGOUT":
                self.w("* BYE")
                self.w(f"{tag} OK bye")
                return
            else:
                self.w(f"{tag} OK")


class Verifier(BaseHTTPRequestHandler):
    """MillionVerifier's v3 shape: GET /api/v3/?api=KEY&email=E -> {"result": ...}."""
    answers = {}
    seen = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
        Verifier.seen.append(q.get("email"))
        raw = json.dumps({"email": q.get("email"), "result": Verifier.answers.get(q.get("email"), "ok")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class Threaded(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


def parsed(raw):
    return email.message_from_bytes(raw, policy=email.policy.default)


def body_of(raw):
    return parsed(raw).get_content()


def reply_raw(frm, to, subject, text, in_reply_to=None, references=None, msgid=None, extra=""):
    lines = [f"From: {frm}", f"To: {to}", f"Subject: {subject}", "Date: Mon, 19 Oct 2026 14:00:00 -0600",
             f"Message-ID: {msgid or '<r' + str(abs(hash(text)) % 99999) + '@mail.example>'}"]
    if in_reply_to:
        lines.append(f"In-Reply-To: {in_reply_to}")
    if references:
        lines.append(f"References: {references}")
    if extra:
        lines.append(extra)
    lines += ["Content-Type: text/plain; charset=utf-8", "", text, ""]
    return "\r\n".join(lines)


def dsn_raw(to_box, rcpt, original_id):
    return "\r\n".join([
        "From: Mail Delivery Subsystem <mailer-daemon@googlemail.com>", f"To: {to_box}",
        "Subject: Delivery Status Notification (Failure)", "Date: Mon, 19 Oct 2026 14:00:00 -0600",
        "Message-ID: <dsn1@mx.google.example>", "MIME-Version: 1.0",
        'Content-Type: multipart/report; report-type=delivery-status; boundary="BB"', "",
        "--BB", "Content-Type: text/plain", "", f"Address not found: {rcpt}", "",
        "--BB", "Content-Type: message/delivery-status", "", "Reporting-MTA: dns; googlemail.com", "",
        f"Final-Recipient: rfc822; {rcpt}", "Action: failed", "Status: 5.1.1", "",
        "--BB", "Content-Type: text/rfc822-headers", "", f"Message-ID: {original_id}", "Subject: x", "",
        "--BB--", ""])


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.smtp = Threaded(("127.0.0.1", 0), FakeSMTP)
        cls.imap = Threaded(("127.0.0.1", 0), FakeIMAP)
        cls.verifier = HTTPServer(("127.0.0.1", 0), Verifier)
        for srv in (cls.smtp, cls.imap, cls.verifier):
            threading.Thread(target=srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        for srv in (cls.smtp, cls.imap, cls.verifier):
            srv.shutdown()
            srv.server_close()

    def setUp(self):
        Mail.reset()
        Verifier.answers, Verifier.seen = {}, []
        self.tmp = Path(tempfile.mkdtemp(prefix="outreach-batch-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.tpl = self.tmp / "tpl"
        shutil.copytree(TEMPLATES, self.tpl)
        (self.tpl / "APPROVED").unlink(missing_ok=True)
        stub = self.tmp / "stub"
        stub.mkdir()
        for name, src in (("leads", STUB_LEADS), ("notify", STUB_NOTIFY), ("prep", STUB_PREP)):
            (stub / name).write_text(src)
            (stub / name).chmod(0o755)
        self.log = self.tmp / "stub.log"
        self.todo = self.tmp / "TAYLOR-TODO.md"
        self.todo.write_text("# TAYLOR-TODO\n\n## 1. Now\n\n## 7. Triage\n")
        self.env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.tmp),
            "CLAUDE_TOOLS_ENV": os.devnull, "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8",
            "OUTREACH_TEMPLATES": str(self.tpl), "OUTREACH_STATE": str(self.tmp / "state"),
            "OUTREACH_LEDGER": str(self.tmp / "ledger.jsonl"),
            "OUTREACH_LEADS_BIN": str(stub / "leads"), "OUTREACH_NOTIFY_BIN": str(stub / "notify"),
            "OUTREACH_PREP_BIN": str(stub / "prep"),
            "STUB_LOG": str(self.log), "TAYLOR_TODO": str(self.todo),
            "LEADS_MAIL_ADDRESS": ADDRESS, "PATCHLAMP_VOICE_NUMBER": "801-555-0100",
            "OUTREACH_PROVIDER": "google", "OUTREACH_MAILBOXES": ",".join(BOXES),
            "OUTREACH_SMTP_HOST": f"127.0.0.1:{self.smtp.server_address[1]}",
            "OUTREACH_IMAP_HOST": f"127.0.0.1:{self.imap.server_address[1]}",
            "OUTREACH_MAILBOX_PER_DAY": "25", "OUTREACH_WARMUP_START": "2026-08-01",
            "OUTREACH_NOW": f"{MONDAY}T07:00:00",
            **{pw_name(b): p for b, p in PASSWORDS.items()},
            # the offline guard's proxy (tests/_offline.py) goes with the built env: a stray real
            # request is caught and reported, while the loopback fakes stay direct by NO_PROXY
            **{k: os.environ[k] for k in os.environ
               if k.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy", "claude_tools_offline_proxy")},
        }

    # -- helpers ------------------------------------------------------------------
    def run_it(self, *args, expect=0, **over):
        env = dict(self.env)
        env.update({k: str(v) for k, v in over.items()})
        env = {k: v for k, v in env.items() if v != "__unset__"}
        r = subprocess.run([sys.executable, str(OUTREACH), *args], capture_output=True, text=True,
                           env=env, timeout=120)
        if expect is not None:
            self.assertEqual(r.returncode, expect,
                             f"{args} exited {r.returncode}\nSTDOUT\n{r.stdout}\nSTDERR\n{r.stderr}")
        for p in PASSWORDS.values():
            self.assertNotIn(p, r.stdout + r.stderr)
        return r

    def approve(self):
        self.run_it("approve")

    def write_batch(self, picks, batch_id="b-test-1"):
        p = self.tmp / f"{batch_id}.json"
        p.write_text(json.dumps({"batch_id": batch_id, "city": "Lehi", "category": "Plumber", "picks": picks}))
        return p

    def picks(self, n=None):
        data = json.loads(BATCH.read_text())["picks"]
        return data if n is None else data[:n]

    def tick_day(self, day, start="07:55", end="17:05", step=5, **over):
        # one process for the day's ticks (`tick --until`), not one a tick: same code path, a second not twenty
        self.run_it("tick", "--until", f"{day}T{end}", "--every", str(step), OUTREACH_NOW=f"{day}T{start}", **over)

    def calls(self, tool=None):
        rows = [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []
        return [r for r in rows if tool is None or r["tool"] == tool]

    def state_rows(self, name):
        p = self.tmp / "state" / name
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def seqs(self):
        p = self.tmp / "state" / "sequences.json"
        return json.loads(p.read_text()) if p.exists() else []

    def sent_to(self, addr):
        return [m for m in Mail.sent if addr in m["to"]]


# ---- the letters --------------------------------------------------------------------

class Letters(Base):
    def test_dry_run_renders_fifty_letters_each_with_its_own_two_faults_and_no_link(self):
        r = self.run_it("send", "--batch", str(BATCH), "--dry-run")
        self.assertIn("50 first letters rendered", r.stdout)
        blocks = re.split(r"\n(?=\d+\. )", r.stdout)
        letters = [b for b in blocks if re.match(r"\d+\. ", b) and "| Hi " in b]
        self.assertEqual(50, len(letters))
        for pick, block in zip(self.picks(), letters):
            with self.subTest(pick=pick["name"]):
                text = "\n".join(l[5:] for l in block.splitlines() if l.startswith("   | "))
                for f in pick["faults"]:
                    self.assertIn(f"- {f['sentence']}\n", text + "\n")
                self.assertIn(DISCLOSURE, text)
                self.assertIn(ADDRESS, text)
                self.assertIn('Reply "no thanks"', text)
                self.assertIn("advertisement", text)
                self.assertIn(f"I can build you a preview of a site for {pick['name']} from your Google listing, "
                              "free, nothing to sign. Want to see it? Just reply.", text)
                self.assertIn("$99 a month, no contract, stated on the site", text)
                self.assertNotRegex(text, r"https?://|www\.|\.com\b")
        self.assertEqual([], Mail.sent)
        self.assertEqual([], self.seqs())

    def letter_for(self, pick):
        r = self.run_it("send", "--batch", str(self.write_batch([pick])), "--dry-run")
        return "\n".join(l[5:] for l in r.stdout.splitlines() if l.startswith("   | ")), r.stdout

    def test_two_faults_read_as_two_things_that_stood_out(self):
        pick = self.picks(1)[0]
        pick["faults"][0]["kind"] = pick["faults"][1]["kind"] = "fault"
        text, _ = self.letter_for(pick)
        self.assertIn("I looked Summit Plumbing up, and two things stood out:\n\n"
                      f"- {pick['faults'][0]['sentence']}\n- {pick['faults'][1]['sentence']}\n", text)

    def test_a_fault_and_a_fact_read_as_one_to_fix_and_one_in_their_favour_fault_first(self):
        pick = self.picks(1)[0]
        fact = "more than 60 Google reviews, averaging 4.8"
        pick["faults"] = [{"key": "reviews", "kind": "fact", "sentence": fact, "evidence": "x"},
                          {"key": "hours", "kind": "fault", "sentence": "your Google listing has no hours for Saturday",
                           "evidence": "y"}]
        text, _ = self.letter_for(pick)
        self.assertIn("I looked Summit Plumbing up: one thing could be better, and one is already working for you."
                      f"\n\n- your Google listing has no hours for Saturday\n- {fact}\n", text)
        self.assertNotIn("stood out", text)
        self.assertIn(DISCLOSURE, text)

    def test_a_pick_with_only_facts_is_not_written_to(self):
        pick = self.picks(1)[0]
        for f in pick["faults"]:
            f["kind"] = "fact"
        _, out = self.letter_for(pick)
        self.assertIn("no fault worth naming", out)
        self.assertIn("0 first letters rendered", out)

    def test_a_batch_across_the_corridor_never_names_a_city(self):
        p = self.tmp / "any.json"
        p.write_text(json.dumps({"batch_id": "b-any", "city": "any", "category": "Plumber", "picks": self.picks(1)}))
        r = self.run_it("send", "--batch", str(p), "--dry-run")
        self.assertIn("Plumber across the corridor", r.stdout)
        self.assertNotIn(" any", r.stdout.lower().replace("company", ""))

    def test_dry_run_reads_the_batch_from_stdin_too(self):
        env = dict(self.env)
        r = subprocess.run([sys.executable, str(OUTREACH), "send", "--batch", "-", "--dry-run"],
                           input=BATCH.read_text(), capture_output=True, text=True, env=env, timeout=60)
        self.assertEqual(0, r.returncode, r.stderr)
        self.assertIn("50 first letters rendered", r.stdout)

    def test_without_go_taylor_sees_each_name_with_its_two_facts_and_nothing_queues(self):
        self.approve()
        r = self.run_it("send", "--batch", str(BATCH))
        self.assertIn("Waiting on `go` for this batch — 50 businesses", r.stdout)
        first = self.picks(1)[0]
        self.assertIn(f"- {first['faults'][0]['sentence']}", r.stdout)
        self.assertEqual([], self.seqs())
        self.assertEqual([], Mail.sent)

    def test_a_batch_waits_on_go_even_with_outreach_auto(self):
        self.approve()
        r = self.run_it("send", "--batch", str(BATCH), OUTREACH_AUTO="1")
        self.assertIn("Waiting on `go`", r.stdout)
        self.assertEqual([], self.seqs())

    def test_go_refuses_unapproved_letters(self):
        r = self.run_it("send", "--batch", str(BATCH), "--go", expect=1)
        self.assertIn("batch-first: not in APPROVED", r.stderr)
        self.assertEqual([], self.seqs())

    def test_picks_without_two_faults_or_an_address_or_suppressed_are_never_queued(self):
        self.approve()
        p = self.picks(5)
        p[0]["faults"] = p[0]["faults"][:1]
        p[1]["email"] = ""
        p[3]["email"] = "x@blocked.example"
        self.run_it("suppress", "add", "blocked.example")
        p[4]["email"] = p[2]["email"]
        p.append(dict(self.picks()[7], faults=[dict(f, kind="opinion") for f in self.picks()[7]["faults"]]))
        r = self.run_it("send", "--batch", str(self.write_batch(p)), "--dry-run")
        self.assertIn("1 sentence(s), not two", r.stdout)
        self.assertIn("no address", r.stdout)
        self.assertIn("suppressed", r.stdout)
        self.assertIn("twice in this batch", r.stdout)
        self.assertIn("neither fault nor fact", r.stdout)
        self.assertIn("1 first letters rendered", r.stdout)

    def test_the_follow_ups_carry_one_link_on_the_sending_domain_or_ask_for_a_reply(self):
        r = self.run_it("approve", "--dry-run")
        self.assertNotIn("PROBLEMS", r.stdout)
        for name in ("batch-first", "batch-second", "batch-third", "answer-yes"):
            self.assertIn(f"{name}.md", r.stdout)

    def test_a_link_base_off_the_sending_domain_is_ignored(self):
        self.approve()
        p = self.picks(1)
        self.run_it("send", "--batch", str(self.write_batch(p)), "--go",
                    OUTREACH_LINK_BASE="https://previews.patchlamp.com")
        self.tick_day(MONDAY, OUTREACH_LINK_BASE="https://previews.patchlamp.com")
        self.tick_day("2026-10-22", OUTREACH_LINK_BASE="https://previews.patchlamp.com")
        second = body_of(self.sent_to(p[0]["email"])[1]["raw"])
        self.assertNotIn("http", second)
        self.assertIn("just reply and I'll send it", second)

    def test_with_a_link_base_the_second_touch_carries_exactly_that_link(self):
        self.approve()
        p = self.picks(1)
        base = f"https://see.{DOMAIN}"
        self.run_it("send", "--batch", str(self.write_batch(p)), "--go", OUTREACH_LINK_BASE=base)
        self.tick_day(MONDAY, OUTREACH_LINK_BASE=base)
        self.tick_day("2026-10-22", OUTREACH_LINK_BASE=base)
        first, second = (body_of(m["raw"]) for m in self.sent_to(p[0]["email"])[:2])
        self.assertNotIn("http", first)
        token = self.seqs()[0]["token"]
        self.assertEqual([f"{base}/{token}"], re.findall(r"https?://\S+", second))


class NeverClaimsASite(Base):
    def test_no_batch_letter_says_a_site_was_built(self):
        spec = importlib.util.spec_from_loader("outreach_mod", importlib.machinery.SourceFileLoader(
            "outreach_mod", str(OUTREACH)))
        mod = importlib.util.module_from_spec(spec)
        os.environ["OUTREACH_TEMPLATES"] = str(self.tpl)
        try:
            spec.loader.exec_module(mod)
            mod.TEMPLATES = self.tpl
            vals = mod.sample_values()
            for name in mod.BATCH_LETTERS:
                for see in ("", "https://see.trypatchlamp.example/x"):
                    vals["see_url"] = see
                    _, letter = mod.load_template(name).render(vals)
                    self.assertFalse(mod.claims_a_site(letter, ""), f"{name} claims a site:\n{letter}")
            # the kit lane's first letter does say it ("I've made you a page"), so the guard sees it
            _, kit_letter = mod.load_template("first").render(vals, fault=vals["fault"])
            self.assertTrue(mod.claims_a_site(kit_letter, ""))
            self.assertFalse(mod.claims_a_site(kit_letter, "https://preview.example/"))
        finally:
            os.environ.pop("OUTREACH_TEMPLATES", None)

    def test_an_edited_letter_that_claims_a_site_is_refused_even_with_a_matching_hash(self):
        p = self.tpl / "batch-first.md"
        p.write_text(p.read_text().replace("I can build you a preview of a site",
                                           "I've built you a page already. I can build you a preview of a site"))
        self.approve_by_hash()
        r = self.run_it("send", "--batch", str(self.write_batch(self.picks(2))), "--go", expect=1)
        self.assertIn("says a site was built", r.stderr)
        self.assertEqual([], Mail.sent)

    def approve_by_hash(self):
        lines = [f"{n} {hashlib.sha256((self.tpl / (n + '.md')).read_bytes()).hexdigest()}"
                 for n in ("batch-first", "batch-second", "batch-third")]
        (self.tpl / "APPROVED").write_text("\n".join(lines) + "\n")


# ---- sending: rotation, pacing, caps, threading ----------------------------------------

class Sending(Base):
    def setUp(self):
        super().setUp()
        self.approve()

    def test_fifty_go_out_across_three_mailboxes_spread_over_the_day_under_the_cap(self):
        r = self.run_it("send", "--batch", str(BATCH), "--go")
        self.assertIn("Queued 50 businesses", r.stdout)
        self.assertIn("Outside the sending window", r.stdout)     # 07:00: the go queues, the tick waits
        self.assertEqual([], Mail.sent)
        self.tick_day(MONDAY)
        self.assertEqual(50, len(Mail.sent))
        times = {}
        for m in Mail.sent:
            msg = parsed(m["raw"])
            self.assertEqual(m["user"], m["from"])
            self.assertIn(m["user"], msg["From"])
            when = email.utils.parsedate_to_datetime(msg["Date"])
            times.setdefault(m["user"], []).append(when)
        self.assertEqual(set(BOXES), set(times))
        for box, ts in times.items():
            with self.subTest(box=box):
                self.assertLessEqual(len(ts), 25)
                self.assertGreaterEqual(len(ts), 15)
                self.assertTrue(all(8 <= t.hour < 17 for t in ts))
                gaps = [(b - a).total_seconds() / 60 for a, b in zip(ts, ts[1:])]
                self.assertTrue(all(g >= 6 for g in gaps), gaps)
                self.assertGreater(len(set(gaps)), 4, f"gaps too regular: {gaps}")
                self.assertGreater(ts[-1].hour, 13, "the day's letters bunched in the morning")
        # each send went into `leads` as today, and nothing was sent twice
        logs = [c for c in self.calls("leads") if c["argv"][:1] == ["log"]]
        self.assertEqual(50, len(logs))
        self.assertTrue(all(c["argv"][2] == "messaged" for c in logs))
        self.assertEqual(50, len({m["to"][0] for m in Mail.sent}))

    def test_every_letter_is_plain_text_with_a_real_message_id_and_a_mailto_unsubscribe(self):
        self.run_it("send", "--batch", str(self.write_batch(self.picks(3))), "--go")
        self.tick_day(MONDAY)
        self.assertEqual(3, len(Mail.sent))
        for m in Mail.sent:
            msg = parsed(m["raw"])
            self.assertEqual("text/plain", msg.get_content_type())
            self.assertFalse(msg.is_multipart())
            self.assertRegex(msg["Message-ID"], rf"^<[0-9a-f]+\.\d+@{re.escape(DOMAIN)}>$")
            self.assertEqual(f"<mailto:{m['user']}?subject=unsubscribe>", msg["List-Unsubscribe"])
            self.assertNotIn("<img", m["raw"].decode(errors="replace").lower())

    def test_the_cap_holds_and_the_rest_wait_for_tomorrow(self):
        self.run_it("send", "--batch", str(self.write_batch(self.picks(9))), "--go")
        self.tick_day(MONDAY, OUTREACH_MAILBOX_PER_DAY="2")
        self.assertEqual(6, len(Mail.sent))
        self.assertEqual({2}, {sum(1 for m in Mail.sent if m["user"] == b) for b in BOXES})
        self.tick_day("2026-10-20", OUTREACH_MAILBOX_PER_DAY="2")
        self.assertEqual(9, len(Mail.sent))

    def test_cap_zero_sends_nothing(self):
        self.run_it("send", "--batch", str(self.write_batch(self.picks(3))), "--go")
        r = self.run_it("tick", OUTREACH_NOW=f"{MONDAY}T10:00:00", OUTREACH_MAILBOX_PER_DAY="0")
        self.assertIn("cap today is 0", r.stdout)
        self.assertEqual([], Mail.sent)

    def test_a_ramp_counts_from_the_warm_up_start(self):
        self.run_it("send", "--batch", str(self.write_batch(self.picks(12))), "--go")
        ramp = "14:1,21:20"
        # day 13 of warm-up: nothing; day 14: one a mailbox
        self.tick_day(MONDAY, OUTREACH_MAILBOX_PER_DAY=ramp, OUTREACH_WARMUP_START="2026-10-06")
        self.assertEqual([], Mail.sent)
        self.tick_day("2026-10-20", OUTREACH_MAILBOX_PER_DAY=ramp, OUTREACH_WARMUP_START="2026-10-06")
        self.assertEqual(3, len(Mail.sent))
        r = self.run_it("warmup", OUTREACH_MAILBOX_PER_DAY=ramp, OUTREACH_WARMUP_START="2026-10-06",
                        OUTREACH_NOW="2026-10-20T10:00:00")
        self.assertIn("day 14", r.stdout)
        self.assertIn("cap today 1 a mailbox", r.stdout)

    def test_a_ramp_with_no_recorded_start_sends_nothing_until_flint_records_it(self):
        self.run_it("send", "--batch", str(self.write_batch(self.picks(3))), "--go")
        self.tick_day(MONDAY, end="09:00", OUTREACH_MAILBOX_PER_DAY="0:5", OUTREACH_WARMUP_START="__unset__")
        self.assertEqual([], Mail.sent)
        self.run_it("warmup", "start", "2026-10-01", OUTREACH_WARMUP_START="__unset__")
        self.tick_day(MONDAY, start="09:05", OUTREACH_MAILBOX_PER_DAY="0:5", OUTREACH_WARMUP_START="__unset__")
        self.assertEqual(3, len(Mail.sent))

    def test_three_touches_in_one_thread_from_one_mailbox_and_never_a_fourth(self):
        p = self.picks(6)
        self.run_it("send", "--batch", str(self.write_batch(p)), "--go")
        for day in (MONDAY, "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-29", "2026-11-05", "2026-11-12"):
            self.tick_day(day, start="08:00", end="17:05", step=10, OUTREACH_MAILBOX_PER_DAY="2")
        for pick in p:
            with self.subTest(pick=pick["name"]):
                got = self.sent_to(pick["email"])
                self.assertEqual(3, len(got))
                self.assertEqual(1, len({m["user"] for m in got}), "the thread changed mailbox")
                msgs = [parsed(m["raw"]) for m in got]
                days = [email.utils.parsedate_to_datetime(m["Date"]).date() for m in msgs]
                self.assertEqual([3, 10], [(d - days[0]).days for d in days[1:]])
                ids = [m["Message-ID"] for m in msgs]
                self.assertEqual(ids[0], msgs[1]["In-Reply-To"])
                self.assertEqual(ids[1], msgs[2]["In-Reply-To"])
                self.assertEqual(f"{ids[0]} {ids[1]}", msgs[2]["References"])
                self.assertEqual(f"Re: {msgs[0]['Subject']}", msgs[1]["Subject"])
                self.assertEqual(f"Re: {msgs[0]['Subject']}", msgs[2]["Subject"])
        self.assertEqual({"done"}, {s["status"] for s in self.seqs()})

    def test_follow_ups_count_toward_the_cap_and_go_first(self):
        self.run_it("send", "--batch", str(self.write_batch(self.picks(6), "b-one")), "--go")
        self.tick_day(MONDAY, start="08:00", end="17:05", step=10, OUTREACH_MAILBOX_PER_DAY="2")
        self.run_it("send", "--batch", str(self.write_batch(self.picks()[10:16], "b-two")), "--go",
                    OUTREACH_NOW="2026-10-22T07:00:00")
        self.tick_day("2026-10-22", start="08:00", end="17:05", step=10, OUTREACH_MAILBOX_PER_DAY="2")
        thursday = [m for m in Mail.sent if "22 Oct 2026" in parsed(m["raw"])["Date"]]
        self.assertEqual(6, len(thursday))
        self.assertTrue(all(parsed(m["raw"])["Subject"].startswith("Re: ") for m in thursday),
                        "a new first letter took a follow-up's place")

    def test_no_sends_on_a_weekend(self):
        self.run_it("send", "--batch", str(self.write_batch(self.picks(3))), "--go")
        self.tick_day("2026-10-24", end="12:00", step=15)
        self.assertEqual([], Mail.sent)

    def test_a_wrong_app_password_fails_without_printing_it_and_sends_nothing(self):
        self.run_it("send", "--batch", str(self.write_batch(self.picks(1))), "--go")
        r = self.run_it("tick", OUTREACH_NOW=f"{MONDAY}T09:00:00", **{pw_name(b): "wrong-pass-zzz" for b in BOXES})
        self.assertIn("refused the login", r.stdout)
        self.assertNotIn("wrong-pass-zzz", r.stdout + r.stderr)
        self.assertEqual([], Mail.sent)


# ---- verification before a first send -------------------------------------------------

class Verification(Base):
    def setUp(self):
        super().setUp()
        self.approve()

    def test_with_no_verifier_the_first_month_sends_only_own_domain_mx_ok(self):
        p = self.picks(8)            # pick 4 (index 3) is free-mail
        p[1]["email_mx"] = "unknown"
        self.run_it("send", "--batch", str(self.write_batch(p)), "--go", OUTREACH_WARMUP_START="2026-10-05")
        self.tick_day(MONDAY, OUTREACH_WARMUP_START="2026-10-05")
        sent = {m["to"][0] for m in Mail.sent}
        self.assertNotIn(p[3]["email"], sent)
        self.assertNotIn(p[1]["email"], sent)
        self.assertEqual(6, len(sent))
        held = [s for s in self.seqs() if s["status"] == "held"]
        self.assertEqual(2, len(held))
        self.assertEqual({"2026-11-04"}, {s["hold_until"] for s in held})
        r = self.run_it("doctor", "--kit", str(KIT), expect=None, OUTREACH_WARMUP_START="2026-10-05")
        self.assertIn("verification: none. Until 2026-11-04, only addresses the batch marks MX-ok on the "
                      "business's own domain are sent", r.stdout)
        # after the month, the held ones go
        self.tick_day("2026-11-04", OUTREACH_WARMUP_START="2026-10-05")
        self.assertIn(p[3]["email"], {m["to"][0] for m in Mail.sent})

    def test_the_verifier_lets_ok_through_holds_accept_all_and_drops_invalid(self):
        p = self.picks(3)
        Verifier.answers = {p[0]["email"]: "ok", p[1]["email"]: "catch_all", p[2]["email"]: "invalid"}
        over = {"OUTREACH_VERIFY": "millionverifier", "MILLIONVERIFIER_API_KEY": "mv-FAKEkeyNEVERreal",
                "OUTREACH_VERIFY_BASE": f"http://127.0.0.1:{self.verifier.server_address[1]}",
                "OUTREACH_WARMUP_START": "2026-10-05"}
        self.run_it("send", "--batch", str(self.write_batch(p)), "--go", **over)
        self.tick_day(MONDAY, **over)
        self.assertEqual([p[0]["email"]], [m["to"][0] for m in Mail.sent])
        by = {s["email"]: s for s in self.seqs()}
        self.assertEqual("held", by[p[1]["email"]]["status"])
        self.assertEqual("stopped", by[p[2]["email"]]["status"])
        supp = json.loads(self.run_it("suppress", "ls", "--json").stdout)
        self.assertIn({"value": p[2]["email"], "kind": "address"}, supp)
        rows = [l for l in (json.loads(x) for x in (self.tmp / "ledger.jsonl").read_text().splitlines())
                if l["kind"] == "email_verify"]
        self.assertEqual(3, len(rows))
        self.assertTrue(all(r["cost_usd"] > 0 for r in rows))
        self.assertEqual(3, len(Verifier.seen), "an address was checked twice")
        r = self.run_it("tick", OUTREACH_NOW=f"{MONDAY}T16:30:00", **over)
        self.assertNotIn("mv-FAKEkeyNEVERreal", r.stdout + r.stderr)


# ---- replies, warm-up strays and bounces ---------------------------------------------

class ReplyWorld(Base):
    """Six letters sent on Monday, so there is something to reply to."""

    def setUp(self):
        super().setUp()
        self.approve()
        self.p = self.picks(6)
        self.run_it("send", "--batch", str(self.write_batch(self.p)), "--go")
        self.tick_day(MONDAY, start="08:00", end="17:05", step=10)
        self.assertEqual(6, len(Mail.sent))
        self.first = {m["to"][0]: m for m in Mail.sent}

    def letter_to(self, i):
        m = self.first[self.p[i]["email"]]
        return m["user"], parsed(m["raw"])

    def inbox(self, **over):
        return self.run_it("inbox", OUTREACH_NOW=f"{MONDAY}T15:00:00", **over)


class Replies(ReplyWorld):

    def test_a_threaded_reply_from_another_address_stops_the_sequence(self):
        box, msg = self.letter_to(0)
        Mail.deliver(box, reply_raw("Mike Owner <mike.personal@home.example>", box, f"Re: {msg['Subject']}",
                                    "Thanks, we're set for now.", in_reply_to=msg["Message-ID"],
                                    references=msg["Message-ID"]))
        r = self.inbox()
        self.assertIn("1 new reply", r.stdout)
        self.assertIn("the sequence stopped: 2 touch(es) won't go", r.stdout)
        by = {s["email"]: s for s in self.seqs()}
        self.assertEqual("stopped", by[self.p[0]["email"]]["status"])
        self.tick_day("2026-10-22", start="08:00", end="17:05", step=10)
        self.assertEqual(1, len(self.sent_to(self.p[0]["email"])))
        self.assertEqual(2, len(self.sent_to(self.p[1]["email"])))

    def test_a_reply_from_the_address_we_wrote_to_counts_even_with_no_thread_headers(self):
        box, msg = self.letter_to(1)
        Mail.deliver(box, reply_raw(self.p[1]["email"], box, "your email", "Who is this?"))
        r = self.inbox()
        self.assertIn("1 new reply", r.stdout)
        self.assertEqual("stopped", {s["email"]: s for s in self.seqs()}[self.p[1]["email"]]["status"])

    def test_warm_up_mail_is_never_a_reply_never_classified_never_answered(self):
        box, _ = self.letter_to(2)
        Mail.deliver(box, reply_raw("Jen <jen@warmup-network.example>", box, "Re: quick favor for the team",
                                    "Sounds good, thanks! no thanks needed. 3HNX8K2", in_reply_to="<w1@warmup.example>",
                                    references="<w0@warmup.example> <w1@warmup.example>"))
        Mail.deliver(box, reply_raw("Sam <sam@warmup-network.example>", box, "Lunch plans",
                                    "Are you free Friday? Call me. 3HNX8K2"))
        Mail.deliver(box, dsn_raw(box, "nobody@warmup-network.example", "<w9@warmup.example>"))
        r = self.inbox(ANTHROPIC_KEY_OUTREACH="sk-ant-FAKEkeyNEVERreal", ANTHROPIC_API_BASE="http://127.0.0.1:1")
        self.assertIn("0 new replies", r.stdout)
        self.assertEqual([], self.state_rows("replies.jsonl"))
        self.assertEqual([], self.state_rows("bounces.jsonl"))
        self.assertEqual([], self.calls("notify"))
        self.assertEqual(6, len(Mail.sent), "something was answered")
        self.assertEqual({"active"}, {s["status"] for s in self.seqs()})
        self.assertEqual([], self.state_rows("suppress.jsonl"))
        cursor = json.loads((self.tmp / "state" / "cursor.json").read_text())
        self.assertEqual(3, cursor["ignored"])

    def test_each_message_is_read_once(self):
        box, msg = self.letter_to(0)
        Mail.deliver(box, reply_raw(self.p[0]["email"], box, f"Re: {msg['Subject']}", "hmm",
                                    in_reply_to=msg["Message-ID"]))
        self.inbox()
        r = self.inbox()
        self.assertIn("0 new replies", r.stdout)
        self.assertEqual(1, len(self.state_rows("replies.jsonl")))

    def test_a_bounce_is_counted_per_mailbox_and_batch_and_the_address_suppressed(self):
        box, msg = self.letter_to(3)
        Mail.deliver(box, dsn_raw(box, self.p[3]["email"], msg["Message-ID"]))
        r = self.inbox()
        self.assertIn("bounce", r.stdout)
        rows = self.state_rows("bounces.jsonl")
        self.assertEqual(1, len(rows))
        self.assertEqual(box, rows[0]["mailbox"])
        self.assertEqual("b-test-1", rows[0]["batch_id"])
        self.assertEqual(self.p[3]["email"], rows[0]["email"])
        self.assertEqual("stopped", {s["email"]: s for s in self.seqs()}[self.p[3]["email"]]["status"])
        supp = json.loads(self.run_it("suppress", "ls", "--json").stdout)
        self.assertIn({"value": self.p[3]["email"], "kind": "address"}, supp)
        r = self.run_it("status", OUTREACH_NOW=f"{MONDAY}T15:00:00")
        self.assertIn("6 sent, 1 bounced", r.stdout)

    def test_an_angry_reply_pauses_that_mailbox_and_tells_taylor(self):
        box, msg = self.letter_to(0)
        Mail.deliver(box, reply_raw(self.p[0]["email"], box, f"Re: {msg['Subject']}",
                                    "This is spam. How did you get my email?", in_reply_to=msg["Message-ID"]))
        r = self.inbox()
        self.assertIn("angry", r.stdout)
        paused = json.loads((self.tmp / "state" / "paused.json").read_text())
        self.assertEqual([box], list(paused))
        notes = self.calls("notify")
        self.assertEqual(1, len(notes))
        self.assertIn(f"`outreach resume {box}`", notes[0]["argv"][0])
        self.assertEqual(6, len(Mail.sent), "an angry reply was answered")
        # the paused mailbox's follow-ups wait; the others go
        self.tick_day("2026-10-22", start="08:00", end="17:05", step=10)
        thursday = [m for m in Mail.sent[6:]]
        self.assertTrue(thursday)
        self.assertNotIn(box, {m["user"] for m in thursday})
        self.run_it("resume", box)
        self.tick_day("2026-10-23", start="08:00", end="17:05", step=10)
        self.assertIn(box, {m["user"] for m in Mail.sent[6 + len(thursday):]})
        r = self.run_it("tick", OUTREACH_NOW="2026-10-23T12:30:00")
        self.assertNotIn("the lane is stopped", r.stdout, "one angry reply stopped the whole lane")

    def test_a_yes_builds_the_preview_and_answers_in_the_thread_with_its_address(self):
        box, msg = self.letter_to(0)
        Mail.deliver(box, reply_raw(self.p[0]["email"], box, f"Re: {msg['Subject']}", "Yes please!",
                                    in_reply_to=msg["Message-ID"], msgid="<yes1@mail.example>"))
        url = "https://previews.patchlamp.com/summit-plumbing/"
        base = f"https://see.{DOMAIN}"
        r = self.inbox(STUB_PREVIEW_URL=url, OUTREACH_LINK_BASE=base)
        self.assertIn("answering with the preview", r.stdout)
        pv = [c for c in self.calls("leads") if c["argv"][:1] == ["preview"]]
        self.assertEqual([["preview", "--place", self.p[0]["place_id"], "--json"]], [c["argv"] for c in pv])
        answer = Mail.sent[-1]
        self.assertEqual(box, answer["user"])
        am = parsed(answer["raw"])
        self.assertEqual("<yes1@mail.example>", am["In-Reply-To"])
        body = am.get_content()
        token = {s["email"]: s for s in self.seqs()}[self.p[0]["email"]]["token"]
        # the link in the answer is on the sending domain, never previews.patchlamp.com (plan 37 § 3)
        self.assertEqual([f"{base}/{token}"], re.findall(r"https?://\S+", body))
        self.assertIn("Here it is", body)
        self.assertTrue(any(url in n["argv"][0] for n in self.calls("notify")))

    def test_a_yes_with_no_link_base_hands_the_built_preview_to_taylor(self):
        box, msg = self.letter_to(0)
        Mail.deliver(box, reply_raw(self.p[0]["email"], box, f"Re: {msg['Subject']}", "Yes please",
                                    in_reply_to=msg["Message-ID"]))
        url = "https://previews.patchlamp.com/summit-plumbing/"
        r = self.inbox(STUB_PREVIEW_URL=url)
        self.assertIn("handed to Taylor", r.stdout)
        self.assertEqual(6, len(Mail.sent), "a previews.patchlamp.com link went out from the cold lane")
        notes = self.calls("notify")
        self.assertEqual(1, len(notes))
        self.assertIn(url, notes[0]["argv"][0])
        self.assertIn("OUTREACH_LINK_BASE", notes[0]["argv"][0])

    def test_a_yes_with_no_preview_available_goes_to_taylor_unanswered(self):
        box, msg = self.letter_to(0)
        Mail.deliver(box, reply_raw(self.p[0]["email"], box, f"Re: {msg['Subject']}", "Yes please",
                                    in_reply_to=msg["Message-ID"]))
        r = self.inbox()
        self.assertIn("handed to Taylor", r.stdout)
        self.assertEqual(6, len(Mail.sent))
        notes = self.calls("notify")
        self.assertEqual(1, len(notes))
        self.assertIn("said yes to the preview", notes[0]["argv"][0])
        logs = [c for c in self.calls("leads") if c["argv"][:1] == ["log"]]
        self.assertEqual("interested", logs[-1]["argv"][2])

    def test_interested_and_call_me_are_never_machine_answered(self):
        box, msg = self.letter_to(0)
        Mail.deliver(box, reply_raw(self.p[0]["email"], box, f"Re: {msg['Subject']}",
                                    "Yes, call me Tuesday at 3pm and we can talk", in_reply_to=msg["Message-ID"]))
        r = self.inbox(STUB_PREVIEW_URL="https://previews.patchlamp.com/x/")
        self.assertIn("interested", r.stdout)
        self.assertEqual(6, len(Mail.sent))
        self.assertEqual([], [c for c in self.calls("leads") if c["argv"][:1] == ["preview"]])


# ---- the build word (B92, plan 37 § 4) ------------------------------------------------

BUILD_LINE = "reply `build` and the full site is ready before you call"


class BuildWord(ReplyWorld):
    """Taylor's `build` after an interested reply starts `prep one` for that business, and nothing else
    does: not the inbox pass, not the tick, not a lead whose reply says "build"."""

    def reply(self, i, text):
        box, msg = self.letter_to(i)
        Mail.deliver(box, reply_raw(self.p[i]["email"], box, f"Re: {msg['Subject']}", text,
                                    in_reply_to=msg["Message-ID"]))

    def preps(self):
        return [c["argv"] for c in self.calls("prep")]

    def test_build_after_an_interested_reply_starts_prep_one_for_that_business(self):
        self.reply(0, "Can you build me the full site? Call me Tuesday at 3pm and we can talk.")
        self.inbox()
        notes = self.calls("notify")
        self.assertEqual(1, len(notes))
        self.assertTrue(notes[0]["argv"][0].endswith(BUILD_LINE + "."), notes[0]["argv"][0])
        # the inbox pass, a lead saying "build" and the day's ticks start nothing
        self.assertEqual([], self.preps())
        self.tick_day("2026-10-22", start="08:00", end="17:05", step=10)
        self.assertEqual([], self.preps())
        # Taylor's word does
        r = self.run_it("build")
        self.assertEqual([["one", self.p[0]["place_id"], "--why",
                           f"outreach build: {self.p[0]['name']} replied {MONDAY}"]], self.preps())
        self.assertIn("Prep 2026-10-19-a: building", r.stdout)
        # said twice, it doesn't start a second build: nothing is waiting any more
        r = self.run_it("build", expect=1)
        self.assertIn("Nothing is waiting on `build`", r.stdout)
        self.assertEqual(1, len(self.preps()))

    def test_a_yes_offers_build_too(self):
        self.reply(0, "Yes please")
        self.inbox()
        note = self.calls("notify")[0]["argv"][0]
        self.assertIn("said yes to the preview", note)
        self.assertTrue(note.endswith(BUILD_LINE + "."), note)
        self.assertEqual([], self.preps())

    def test_a_no_or_an_angry_reply_that_says_build_offers_nothing_and_starts_nothing(self):
        self.reply(0, "No thanks, don't build anything for us. Unsubscribe.")
        self.reply(1, "This is spam. Don't build me anything, I'll report you.")
        self.inbox()
        self.assertFalse([n for n in self.calls("notify") if "`build`" in n["argv"][0]])
        self.assertEqual([], self.preps())
        r = self.run_it("build", expect=1)
        self.assertIn("Nothing is waiting on `build`", r.stdout)
        self.assertEqual([], self.preps())

    def test_two_waiting_asks_which_and_a_name_picks_one(self):
        self.reply(0, "Interested. Call me tomorrow?")
        self.reply(1, "Sounds interesting. Call me Friday.")
        self.inbox()
        r = self.run_it("build", expect=1)
        self.assertIn("2 replies are waiting on `build`; which one?", r.stdout)
        self.assertEqual([], self.preps())
        name = self.p[1]["name"]
        self.run_it("build", name.split()[0] if len(name.split()[0]) > 3 else name)
        self.assertEqual(self.p[1]["place_id"], self.preps()[0][1])

    def test_dry_run_asks_prep_for_its_own_dry_run_and_records_nothing(self):
        self.reply(0, "Interested. Call me tomorrow?")
        self.inbox()
        r = self.run_it("build", "--dry-run")
        self.assertEqual("--dry-run", self.preps()[0][-1])
        self.assertIn("nothing started", r.stdout)
        self.assertEqual([], self.state_rows("builds.jsonl"))

    def test_a_reply_we_cannot_name_by_its_place_offers_nothing(self):
        # a stranger writing to the mailbox: no send row, so no place id and no `build` line
        box, _ = self.letter_to(0)
        Mail.deliver(box, reply_raw("Pat <pat@elsewhere.example>", box, "hi", "Call me, I'm interested"))
        self.inbox()
        self.assertFalse([n for n in self.calls("notify") if "`build`" in n["argv"][0]])


# ---- the stop rules ------------------------------------------------------------------

class StopRules(Base):
    def setUp(self):
        super().setUp()
        self.approve()
        self.run_it("send", "--batch", str(self.write_batch(self.picks(3))), "--go")

    def seed(self, sends, bounces=(), replies=()):
        st = self.tmp / "state"
        st.mkdir(parents=True, exist_ok=True)
        with open(st / "sends.jsonl", "a") as f:
            for r in sends:
                f.write(json.dumps(r) + "\n")
        with open(st / "bounces.jsonl", "a") as f:
            for r in bounces:
                f.write(json.dumps(r) + "\n")
        with open(st / "replies.jsonl", "a") as f:
            for r in replies:
                f.write(json.dumps(r) + "\n")

    def sends(self, n, box=BOXES[0], batch="b-old", prefix="s"):
        return [{"ts": "2026-10-10T09:00:00-06:00", "date": "2026-10-10", "email": f"{prefix}{i}@x.example",
                 "mailbox": box, "batch_id": batch, "provider": "google"} for i in range(n)]

    def tick(self):
        return self.run_it("tick", expect=None, OUTREACH_NOW=f"{MONDAY}T10:00:00")

    def assert_stopped(self, r, words):
        self.assertEqual(1, r.returncode, r.stdout + r.stderr)
        self.assertIn("the lane is stopped", r.stdout)
        self.assertIn(words, r.stdout)
        self.assertEqual([], Mail.sent)
        self.assertIn("**The email lane stopped itself", self.todo.read_text())
        self.assertEqual(1, len(self.calls("notify")))

    def test_bounces_over_two_percent_on_one_mailbox_stop_the_lane(self):
        self.seed(self.sends(100), bounces=[{"ts": "2026-10-10T10:00:00-06:00", "mailbox": BOXES[0],
                                             "batch_id": "b-old"}] * 3)
        self.assert_stopped(self.tick(), f"bounces on mailbox {BOXES[0]}: 3 of 100")

    def test_two_percent_exactly_does_not_stop_it(self):
        self.seed(self.sends(100), bounces=[{"ts": "2026-10-10T10:00:00-06:00", "mailbox": BOXES[0],
                                             "batch_id": "b-old"}] * 2)
        r = self.tick()
        self.assertEqual(0, r.returncode, r.stdout)
        self.assertEqual(3, len(Mail.sent))

    def test_bounces_over_two_percent_of_one_batch_stop_it_even_spread_over_mailboxes(self):
        sends = sum((self.sends(30, box=b, batch="b-old", prefix=b[:3]) for b in BOXES), [])
        bounces = [{"ts": "2026-10-10T10:00:00-06:00", "mailbox": b, "batch_id": "b-old"} for b in BOXES]
        self.seed(sends, bounces=bounces)      # each mailbox 1 of 30 (counted over 50: 2%), the batch 3 of 90
        self.assert_stopped(self.tick(), "bounces on batch b-old: 3 of 90")

    def test_angry_plus_unsubscribes_over_one_percent_of_the_last_thousand_stop_it(self):
        sends = self.sends(1000)
        reps = [{"ts": "2026-10-11T10:00:00-06:00", "class": "no" if i % 2 else "angry",
                 "email": f"s{i}@x.example"} for i in range(11)]
        self.seed(sends, replies=reps)
        self.assert_stopped(self.tick(), "angry replies plus unsubscribes: 11")

    def test_ten_in_a_thousand_is_not_over_the_line(self):
        reps = [{"ts": "2026-10-11T10:00:00-06:00", "class": "no", "email": f"s{i}@x.example"} for i in range(10)]
        self.seed(self.sends(1000), replies=reps)
        r = self.tick()
        self.assertEqual(0, r.returncode, r.stdout)

    def test_one_no_thanks_early_on_does_not_stop_a_lane(self):
        self.seed(self.sends(20), replies=[{"ts": "2026-10-11T10:00:00-06:00", "class": "no",
                                            "email": "s1@x.example"}])
        self.assertEqual(0, self.tick().returncode)

    def test_a_postmaster_reading_at_the_line_stops_it_and_under_it_does_not(self):
        r = self.run_it("postmaster", "0.08", OUTREACH_NOW=f"{MONDAY}T09:00:00")
        self.assertIn(f"Recorded 0.08% for {DOMAIN}", r.stdout)
        r = self.run_it("postmaster", "0.1", expect=1, OUTREACH_NOW=f"{MONDAY}T09:30:00")
        self.assertIn("Postmaster spam rate", r.stdout)
        self.assert_stopped(self.tick(), "stopped since")

    def test_a_stop_holds_until_taylor_resumes_and_then_counts_afresh(self):
        self.seed(self.sends(100), bounces=[{"ts": "2026-10-10T10:00:00-06:00", "mailbox": BOXES[0],
                                             "batch_id": "b-old"}] * 5)
        self.assert_stopped(self.tick(), "bounces on mailbox")
        r = self.tick()
        self.assertEqual(1, r.returncode)
        self.assertEqual(1, len(self.calls("notify")), "told twice")
        self.assertEqual(1, self.todo.read_text().count("**The email lane stopped itself"))
        self.run_it("resume", "--lane", OUTREACH_NOW=f"{MONDAY}T10:30:00")
        self.tick_day(MONDAY, start="10:35", end="13:00")
        self.assertEqual(3, len(Mail.sent))

    def test_status_and_doctor_show_the_numbers(self):
        self.seed(self.sends(40), bounces=[{"ts": "2026-10-10T10:00:00-06:00", "mailbox": BOXES[0],
                                            "batch_id": "b-old"}])
        r = self.run_it("status", OUTREACH_NOW=f"{MONDAY}T07:00:00")
        self.assertIn("40 sent, 1 bounced", r.stdout)
        self.assertIn("stop rules: none crossed", r.stdout)
        self.assertIn("sequences: active 3", r.stdout)
        for b in BOXES:
            self.assertIn(f"{b}: 0 of 25 today", r.stdout)


# ---- the same lane on the `fake` provider (the acceptance line: caps and kill switch against fake) ----

class OnFake(Base):
    """The batch lane with OUTREACH_PROVIDER=fake: letters land in state/fake/outbox.jsonl and
    nothing opens a socket at all. Proves the caps, the kill switch and the stop rules there."""

    def setUp(self):
        super().setUp()
        self.env["OUTREACH_PROVIDER"] = "fake"
        self.approve()

    def outbox(self):
        return self.state_rows("fake/outbox.jsonl")

    def test_the_per_mailbox_cap_and_the_day(self):
        self.run_it("send", "--batch", str(self.write_batch(self.picks(9))), "--go")
        self.tick_day(MONDAY, OUTREACH_MAILBOX_PER_DAY="2")
        out = self.outbox()
        self.assertEqual(6, len(out))
        self.assertEqual({2}, {sum(1 for m in out if m["from"] == b) for b in BOXES})
        self.assertEqual([], Mail.sent, "the fake provider opened a mail connection")
        self.tick_day("2026-10-20", OUTREACH_MAILBOX_PER_DAY="2")
        self.assertEqual(9, len(self.outbox()))

    def test_the_default_cap_is_zero_and_sends_nothing(self):
        self.run_it("send", "--batch", str(self.write_batch(self.picks(3))), "--go", OUTREACH_MAILBOX_PER_DAY="__unset__")
        self.tick_day(MONDAY, OUTREACH_MAILBOX_PER_DAY="__unset__")
        self.assertEqual([], self.outbox())

    def test_the_kill_switch_on_bounces_stops_the_lane_and_resume_restarts_it(self):
        self.run_it("send", "--batch", str(self.write_batch(self.picks(3))), "--go")
        st = self.tmp / "state"
        with open(st / "sends.jsonl", "a") as f:
            for i in range(100):
                f.write(json.dumps({"ts": "2026-10-10T09:00:00-06:00", "date": "2026-10-10", "email": f"s{i}@x.example",
                                    "mailbox": BOXES[0], "batch_id": "b-old", "provider": "fake"}) + "\n")
        with open(st / "bounces.jsonl", "a") as f:
            for _ in range(3):
                f.write(json.dumps({"ts": "2026-10-10T10:00:00-06:00", "mailbox": BOXES[0], "batch_id": "b-old"}) + "\n")
        r = self.run_it("tick", expect=1, OUTREACH_NOW=f"{MONDAY}T10:00:00")
        self.assertIn("the lane is stopped", r.stdout)
        self.assertEqual([], self.outbox())
        r = self.run_it("send", "--batch", str(self.write_batch(self.picks()[5:7], "b-later")), "--go", expect=1,
                        OUTREACH_NOW=f"{MONDAY}T10:05:00")
        self.assertIn("the lane is stopped", r.stdout)
        self.assertEqual(1, len(self.calls("notify")))
        self.run_it("resume", "--lane", OUTREACH_NOW=f"{MONDAY}T10:30:00")
        self.tick_day(MONDAY, start="10:35", end="15:00")
        self.assertEqual(3, len(self.outbox()))

    def test_an_angry_reply_pauses_only_its_mailbox(self):
        self.run_it("send", "--batch", str(self.write_batch(self.picks(6))), "--go")
        self.tick_day(MONDAY, step=10)
        first = {m["to"]: m for m in self.outbox()}
        pick = self.picks(1)[0]
        mb = first[pick["email"]]["from"]
        (self.tmp / "state" / "fake" / "inbox.jsonl").write_text(json.dumps(
            {"id": "r1", "from": pick["email"], "subject": "Re: x", "text": "This is spam, stop.",
             "ts": f"{MONDAY}T15:00:00-06:00"}) + "\n")
        r = self.run_it("inbox", OUTREACH_NOW=f"{MONDAY}T15:05:00")
        self.assertIn("angry", r.stdout)
        self.assertEqual([mb], list(json.loads((self.tmp / "state" / "paused.json").read_text())))
        self.assertIn({"value": pick["email"].lower(), "kind": "address"},
                      json.loads(self.run_it("suppress", "ls", "--json").stdout))
        self.tick_day("2026-10-22", step=10)
        later = self.outbox()[6:]
        self.assertTrue(later)
        self.assertNotIn(mb, {m["from"] for m in later})

    def test_verify_before_first_send_holds_free_mail_in_the_first_month(self):
        p = self.picks(4)                     # index 3 is free-mail
        self.run_it("send", "--batch", str(self.write_batch(p)), "--go", OUTREACH_WARMUP_START="2026-10-05")
        self.tick_day(MONDAY, OUTREACH_WARMUP_START="2026-10-05")
        self.assertNotIn(p[3]["email"], {m["to"] for m in self.outbox()})
        self.assertEqual(3, len(self.outbox()))


# ---- the small commands and the doctor ----------------------------------------------------

class Commands(Base):
    def test_suppress_ls_json_is_a_list_of_values_and_kinds(self):
        self.run_it("suppress", "add", "A@b.example", "spammy.example", "ChIJplace0001")
        got = json.loads(self.run_it("suppress", "ls", "--json").stdout)
        self.assertEqual([{"value": "a@b.example", "kind": "address"},
                          {"value": "spammy.example", "kind": "domain"},
                          {"value": "ChIJplace0001", "kind": "place_id"}], got)

    def test_suppress_ls_json_is_an_empty_list_when_nobody_is(self):
        self.assertEqual([], json.loads(self.run_it("suppress", "ls", "--json").stdout))

    def test_a_suppressed_domain_is_never_written_to(self):
        self.approve()
        p = self.picks(2)
        self.run_it("suppress", "add", p[0]["email"].split("@")[1])
        self.run_it("send", "--batch", str(self.write_batch(p)), "--go")
        self.tick_day(MONDAY, end="17:05", step=10)
        self.assertEqual([p[1]["email"]], [m["to"][0] for m in Mail.sent])

    def test_a_business_is_never_queued_twice_across_batches(self):
        self.approve()
        p = self.picks(2)
        self.run_it("send", "--batch", str(self.write_batch(p, "b-a")), "--go")
        r = self.run_it("send", "--batch", str(self.write_batch(p, "b-b")), "--go")
        self.assertIn("already in a sequence", r.stdout)
        self.assertEqual(2, len(self.seqs()))

    def test_doctor_is_green_on_a_fully_faked_setup(self):
        self.approve()
        r = self.run_it("doctor", "--kit", str(KIT), expect=0, ANTHROPIC_KEY_OUTREACH="sk-ant-FAKEkeyNEVERreal",
                        LEADS_BOOKING_URL="https://cal.com/x", OUTREACH_LINK_BASE=f"https://see.{DOMAIN}")
        for b in BOXES:
            self.assertIn(f"{b} logs in to SMTP and IMAP", r.stdout)
            self.assertIn(f"{pw_name(b)}: set", r.stdout)
        self.assertIn("batch-first: approved", r.stdout)
        self.assertIn("cap today", r.stdout.replace("a mailbox today", "cap today"))
        self.assertIn(f"link base: https://see.{DOMAIN}", r.stdout)

    def test_doctor_is_plain_about_what_is_missing_on_a_bare_setup(self):
        bare = {k: "__unset__" for k in ("OUTREACH_MAILBOXES", "OUTREACH_WARMUP_START", "OUTREACH_MAILBOX_PER_DAY",
                                         *[pw_name(b) for b in BOXES])}
        r = self.run_it("doctor", "--kit", str(KIT), expect=1, **bare)
        self.assertIn("OUTREACH_MAILBOXES: MISSING", r.stdout)
        self.assertIn("warm-up start: not recorded", r.stdout)
        self.assertIn("(0: nothing sends)", r.stdout)
        self.assertIn("verification: none.", r.stdout)
        self.assertIn("NOT APPROVED", r.stdout)

    def test_doctor_names_a_missing_app_password_by_name_only(self):
        r = self.run_it("doctor", "--kit", str(KIT), expect=1, **{pw_name(BOXES[1]): "__unset__"})
        self.assertIn(f"{pw_name(BOXES[1])}: MISSING", r.stdout)

    def test_the_batch_lane_refuses_instantly(self):
        self.approve()
        r = self.run_it("send", "--batch", str(self.write_batch(self.picks(1))), "--go", expect=1,
                        OUTREACH_PROVIDER="instantly", INSTANTLY_API_KEY="inst_FAKE")
        self.assertIn("OUTREACH_PROVIDER=google", r.stderr)


if __name__ == "__main__":
    unittest.main()
