"""The close arm (ROADMAP B137, plan ~/projects/plans/55-autonomous-acquisition.md § 5.4 and § 5.6, experiment
E3): with OUTREACH_LINK_BASE set and answer-interested.md approved, an *interested* reply to a batch letter is
dealt arm A (Taylor's brief, as before) or arm B (Patch answers once, as Patch, with the site link, the claim
link and the call windows, then stops) by a stable hash of the place id; the lead's next message goes to Taylor
either way; `outreach status --by arm` counts interested, claimed and paid per arm.

Against the in-process fake SMTP and IMAP servers of tests/test_outreach_batch.py: nothing is mailed.

    python3 -m unittest tests.test_outreach_close_arm   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads (tests/_offline.py)

import hashlib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import unittest  # noqa: E402

from test_outreach_batch import DOMAIN, MONDAY, Base, Mail, ReplyWorld, parsed, reply_raw  # noqa: E402

LINK_BASE = f"https://see.{DOMAIN}"
BOOKING = "https://cal.example/taylor/15"
PREVIEW = "https://previews.example/summit-plumbing/"
CLAIM = "https://start.example/start?business=Summit+Plumbing&preview=summit-plumbing"
SIGNATURE = "Patch, Taylor's AI operator"

# `leads` as a recorder whose preview answer carries the claim link, as `leads preview --place --json` does
STUB_LEADS = """#!/usr/bin/env python3
import json, os, sys
open(os.environ["STUB_LOG"], "a").write(json.dumps({"tool": "leads", "argv": sys.argv[1:]}) + "\\n")
if sys.argv[1:2] == ["preview"]:
    url = os.environ.get("STUB_PREVIEW_URL")
    if not url:
        print("leads: no preview", file=sys.stderr); sys.exit(2)
    out = {"ok": True, "place_id": sys.argv[3], "url": url, "slug": "x", "name": "x", "category": "Plumber",
           "city": "Lehi", "expires": "2026-11-18", "published": True}
    if os.environ.get("STUB_CLAIM_URL"):
        out["claim_url"] = os.environ["STUB_CLAIM_URL"]
    print(json.dumps(out))
else:
    print("ok")
"""


def arm_of(place_id):
    """The deal, written out independently of the tool: sha256("E3:" + place id), first 8 hex digits, even = A."""
    return "AB"[int(hashlib.sha256(f"E3:{place_id}".encode()).hexdigest()[:8], 16) % 2]


class CloseArm(ReplyWorld):
    def setUp(self):
        super().setUp()
        (self.tmp / "stub" / "leads").write_text(STUB_LEADS)
        self.pipeline = self.tmp / "pipeline.jsonl"
        self.env.update(LEADS_PIPELINE=str(self.pipeline), LEADS_PREVIEWS=str(self.tmp / "previews"))
        arms = [arm_of(p["place_id"]) for p in self.p]
        self.a, self.b = arms.index("A"), arms.index("B")       # the fixture holds one of each among the six

    def on(self, **over):
        """The test's switches: the link base, the booking link, the preview and its claim link."""
        return dict(dict(OUTREACH_LINK_BASE=LINK_BASE, LEADS_BOOKING_URL=BOOKING, STUB_PREVIEW_URL=PREVIEW,
                         STUB_CLAIM_URL=CLAIM, LEADS_CLAIM_START="https://start.example/start",
                         OUTREACH_CLAIM_LINKS="1"), **over)

    def relay_says(self, *kinds):
        """The relay's press state as `relay/press.py` keeps it after a links sync (B147): the kinds the app
        serves. Returns the switches with the manual override unset, so the relay's word decides."""
        p = self.tmp / "relay-press.json"
        p.write_text(json.dumps({"inflight": {}, "kinds": list(kinds), "kinds_at": "2026-10-08T09:00:00-06:00"}))
        return self.on(OUTREACH_CLAIM_LINKS="__unset__", OUTREACH_PRESS_STATE=str(p))

    def interested(self, i, text="Interested. Can you call me this week?", msgid=None):
        box, msg = self.letter_to(i)
        Mail.deliver(box, reply_raw(self.p[i]["email"], box, f"Re: {msg['Subject']}", text,
                                    in_reply_to=msg["Message-ID"], msgid=msgid or f"<int{i}-{len(text)}@mail.example>"))
        return box

    def rows(self):
        return {r["email"]: r for r in self.state_rows("replies.jsonl")}

    def logs(self):
        return [c["argv"] for c in self.calls("leads") if c["argv"][:1] == ["log"]]

    def answers(self):
        return Mail.sent[6:]

    # -- the default is unchanged ------------------------------------------------------------
    def test_without_a_link_base_every_interested_reply_is_taylors_as_before(self):
        self.interested(self.a)
        self.interested(self.b)
        r = self.inbox(**self.on(OUTREACH_LINK_BASE="__unset__"))
        self.assertIn("close test E3 is off", r.stdout)
        self.assertEqual([], self.answers(), "the machine answered an interested reply with the test off")
        self.assertEqual(2, len(self.calls("notify")))
        self.assertEqual([], [c for c in self.calls("leads") if c["argv"][:1] == ["preview"]])
        for row in self.rows().values():
            self.assertNotIn("arm", row)
            self.assertNotIn("experiment_id", row)
        for argv in self.logs():
            self.assertNotIn("--arm", argv)
        self.assertEqual({None}, {s.get("arm") for s in self.seqs()})

    def test_an_unapproved_template_keeps_the_test_off(self):
        tpl = self.tpl / "answer-interested.md"
        tpl.write_text(tpl.read_text() + "\n# an edit after approval\n")
        self.interested(self.b)
        r = self.inbox(**self.on())
        self.assertIn("answer-interested: the text changed since Taylor approved it", r.stdout)
        self.assertEqual([], self.answers())
        self.assertNotIn("arm", self.rows()[self.p[self.b]["email"]])

    # -- the acceptance: two interested replies, two arms --------------------------------------
    def test_two_interested_replies_land_in_different_arms(self):
        box_a = self.interested(self.a)
        box_b = self.interested(self.b, msgid="<b-first@mail.example>")
        r = self.inbox(**self.on())
        self.assertIn("arm A, Taylor's call", r.stdout)
        self.assertIn("arm B, Patch answers", r.stdout)
        rows = self.rows()
        ra, rb = rows[self.p[self.a]["email"]], rows[self.p[self.b]["email"]]
        self.assertEqual(("A", "E3", "taylor", False), (ra["arm"], ra["experiment_id"], ra["close_by"], ra["answered"]))
        self.assertEqual(("B", "E3", "patch", True), (rb["arm"], rb["experiment_id"], rb["close_by"], rb["answered"]))
        self.assertEqual("answer-interested", rb["answer_template"])
        # the thread carries the arm too
        seqs = {s["email"]: s for s in self.seqs()}
        self.assertEqual(("A", "E3"), (seqs[self.p[self.a]["email"]]["arm"], seqs[self.p[self.a]["email"]]["experiment_id"]))
        self.assertEqual("B", seqs[self.p[self.b]["email"]]["arm"])

        # arm A: nothing sent, Taylor told, as before
        sent = self.answers()
        self.assertEqual(1, len(sent))
        self.assertNotIn(self.p[self.a]["email"], sent[0]["to"])
        self.assertNotIn(box_a, [m["user"] for m in sent if self.p[self.a]["email"] in m["to"]])

        # arm B: one reply in the thread from its mailbox, Patch's name on it, the three links once each
        m = sent[0]
        self.assertEqual(box_b, m["user"])
        self.assertIn(self.p[self.b]["email"], m["to"])
        am = parsed(m["raw"])
        self.assertEqual("<b-first@mail.example>", am["In-Reply-To"])
        self.assertIn("Patch", am["From"])
        self.assertNotIn("Taylor Remund", am["From"])
        self.assertTrue(am["Subject"].startswith("Re: "))
        body = am.get_content()
        seq_b = seqs[self.p[self.b]["email"]]
        see = f"{LINK_BASE}/{seq_b['token']}"
        claim = f"{LINK_BASE}/{seq_b['claim_token']}"           # a see-link of kind claim, its target kept beside it
        self.assertEqual(CLAIM, seq_b["claim_target"])
        self.assertNotEqual(seq_b["token"], seq_b["claim_token"])
        for link in (see, claim, BOOKING):
            self.assertEqual(1, body.count(link), link)
        self.assertNotIn(CLAIM, body, "the product's claim URL went out from the cold lane")
        self.assertNotIn(PREVIEW, body, "the preview host went out from the cold lane; the see-link stands for it")
        self.assertIn(SIGNATURE + " ·", body)
        self.assertIn("weekdays 6:45–7:45am, 12:15–12:45pm or 6:15–7pm (Mountain)", body)
        self.assertFalse([l for l in body.splitlines() if l.strip().startswith("Taylor Remund")])
        self.assertNotIn("free week", body.lower())
        self.assertIn('Reply "no thanks"', body)

        # the pipeline lines carry the arm and the experiment
        by_place = {a[a.index("--place") + 1]: a for a in self.logs() if "--place" in a}
        for i, arm in ((self.a, "A"), (self.b, "B")):
            argv = by_place[self.p[i]["place_id"]]
            self.assertEqual("interested", argv[2])
            self.assertEqual(arm, argv[argv.index("--arm") + 1])
            self.assertEqual("E3", argv[argv.index("--experiment") + 1])

        # Taylor hears about both: arm A as before, arm B as a note that Patch answered and stopped
        notes = [n["argv"][0] for n in self.calls("notify")]
        self.assertEqual(2, len(notes))
        self.assertTrue(any("arm B: Patch answered once" in n for n in notes))

        # `status --by arm` shows both rows
        out = self.run_it("status", "--by", "arm", OUTREACH_NOW=f"{MONDAY}T16:00:00", **self.on()).stdout
        self.assertIn("Close test E3 (Taylor's call vs Patch's link): open", out)
        self.assertRegex(out, r"A Taylor\s+1\s+0 \(0\.0\)")
        self.assertRegex(out, r"B Patch\s+1\s+1 \(100\.0\)")
        self.assertIn("Too few to decide", out)

    def test_the_deal_is_stable_by_business(self):
        self.interested(self.b, text="Interested, give me a call")
        self.inbox(**self.on())
        first = self.rows()[self.p[self.b]["email"]]["arm"]
        self.assertEqual(arm_of(self.p[self.b]["place_id"]), first)

    def test_without_a_claim_link_from_leads_the_venture_claim_start_is_the_target(self):
        self.interested(self.b)
        self.inbox(**self.on(STUB_CLAIM_URL="__unset__", LEADS_CLAIM_START="https://start.example/start"))
        body = parsed(self.answers()[0]["raw"]).get_content()
        self.assertNotIn("start.example", body)
        seq = {s["email"]: s for s in self.seqs()}[self.p[self.b]["email"]]
        self.assertEqual("https://start.example/start", seq["claim_target"])

    def test_until_the_see_host_serves_claim_links_arm_b_stays_off_and_taylor_gets_it(self):
        self.interested(self.a)
        self.interested(self.b)
        r = self.inbox(**self.on(OUTREACH_CLAIM_LINKS="__unset__"))
        self.assertIn("close test E3 is off", r.stdout)
        self.assertIn("the see host has no claim links yet", r.stdout)
        self.assertEqual([], self.answers(), "Patch answered with the claim link on the product's domain")
        self.assertEqual(2, len(self.calls("notify")))
        self.assertEqual([], [c for c in self.calls("leads") if c["argv"][:1] == ["preview"]])
        for row in self.rows().values():
            self.assertNotIn("arm", row)
        for argv in self.logs():
            self.assertNotIn("--arm", argv)
        out = self.run_it("status", "--by", "arm", **self.on(OUTREACH_CLAIM_LINKS="__unset__")).stdout
        self.assertIn("off — ", out)
        self.assertIn("OUTREACH_CLAIM_LINKS=1 forces it on", out)

    # -- B147: the app's word on the links sync opens it -----------------------------------------
    def test_the_state_line_turns_ready_once_the_relay_says_the_app_serves_claim_links(self):
        out = self.run_it("status", "--by", "arm", **self.relay_says("press")).stdout
        self.assertIn("off — the see host has no claim links yet", out)          # an app from before B147
        out = self.run_it("status", "--by", "arm", **self.relay_says("press", "claim")).stdout
        self.assertIn("Close test E3 (Taylor's call vs Patch's link): open", out)
        self.assertNotIn("claim links", out)
        out = self.run_it("status", "--by", "arm", **dict(self.relay_says("press", "claim"),
                                                          OUTREACH_CLAIM_LINKS="0")).stdout
        self.assertIn("off — the see host has no claim links yet", out)          # the manual override wins

    def test_an_arm_b_reply_carries_both_links_on_the_sending_domain_and_the_booking_link_untouched(self):
        self.interested(self.b)
        r = self.inbox(**self.relay_says("press", "claim"))
        self.assertIn("arm B, Patch answers", r.stdout)
        body = parsed(self.answers()[0]["raw"]).get_content()
        seq = {s["email"]: s for s in self.seqs()}[self.p[self.b]["email"]]
        row = self.rows()[self.p[self.b]["email"]]
        host = LINK_BASE.split("//", 1)[1]
        for k in ("see_url", "start_url"):                       # {preview_url} and {start_url} as they went out
            self.assertEqual(host, row[k].split("/")[2], k)
            self.assertEqual(1, body.count(row[k]))
        self.assertEqual(f"{LINK_BASE}/{seq['claim_token']}", row["start_url"])
        self.assertEqual(CLAIM, seq["claim_target"])             # what the see host redirects to
        self.assertEqual(1, body.count(BOOKING))                 # the booking link goes as it is
        self.assertNotIn("start.example", body)

    def test_a_claim_target_off_the_claim_start_falls_back_to_the_claim_start(self):
        self.interested(self.b)
        self.inbox(**self.on(STUB_CLAIM_URL="https://elsewhere.example/start?business=x"))
        seq = {s["email"]: s for s in self.seqs()}[self.p[self.b]["email"]]
        self.assertEqual("https://start.example/start", seq["claim_target"])

    # -- then it stops ----------------------------------------------------------------------
    def test_a_second_message_goes_to_taylor_in_either_arm_and_is_never_machine_answered(self):
        self.interested(self.a)
        self.interested(self.b)
        self.inbox(**self.on())
        self.assertEqual(1, len(self.answers()))
        # a price question would be machine-answered outside the test; inside it, the second message is Taylor's
        self.interested(self.a, text="How much does it cost?", msgid="<a-second@mail.example>")
        self.interested(self.b, text="Yes", msgid="<b-second@mail.example>")
        r = self.run_it("inbox", **self.on(OUTREACH_NOW=f"{MONDAY}T16:00:00"))
        self.assertEqual(2, r.stdout.count("a second message, so it is Taylor's"))
        self.assertEqual(1, len(self.answers()), "the machine answered a second message")
        notes = [n["argv"][0] for n in self.calls("notify")][2:]
        self.assertEqual(2, len(notes))
        self.assertTrue(all("wrote again" in n and "leads brief" in n for n in notes))
        self.assertTrue(any("Patch answered their first" in n for n in notes))
        rows = [x for x in self.state_rows("replies.jsonl") if x.get("close_followup")]
        self.assertEqual({"A", "B"}, {x["arm"] for x in rows})
        # still one business once in the report
        out = self.run_it("status", "--by", "arm", **self.on()).stdout
        self.assertRegex(out, r"A Taylor\s+1\s")
        self.assertRegex(out, r"B Patch\s+1\s")

    def test_a_no_after_patchs_answer_is_still_suppressed(self):
        self.interested(self.b)
        self.inbox(**self.on())
        self.interested(self.b, text="No thanks, please remove me", msgid="<b-no@mail.example>")
        r = self.run_it("inbox", **self.on(OUTREACH_NOW=f"{MONDAY}T16:00:00"))
        self.assertNotIn("a second message", r.stdout)
        supp = json.loads(self.run_it("suppress", "ls", "--json").stdout)
        self.assertIn({"value": self.p[self.b]["email"], "kind": "address"}, supp)

    # -- arm B that can't be served stays arm B, handed to Taylor ---------------------------------
    def test_arm_b_with_the_reply_cap_spent_goes_to_taylor_and_stays_in_arm_b(self):
        self.interested(self.b)
        r = self.inbox(**self.on(OUTREACH_MAX_REPLIES_PER_DAY="0"))
        self.assertIn("arm B, but Patch couldn't answer (the day's machine-reply cap is spent)", r.stdout)
        self.assertEqual([], self.answers())
        row = self.rows()[self.p[self.b]["email"]]
        self.assertEqual(("B", "taylor"), (row["arm"], row["close_by"]))
        self.assertEqual(1, len(self.calls("notify")))
        out = self.run_it("status", "--by", "arm", **self.on()).stdout
        self.assertRegex(out, r"B Patch\s+1\s+0 \(0\.0\)")

    def test_arm_b_with_no_preview_goes_to_taylor(self):
        self.interested(self.b)
        r = self.inbox(**self.on(STUB_PREVIEW_URL="__unset__"))
        self.assertIn("arm B, but Patch couldn't answer", r.stdout)
        self.assertEqual([], self.answers())

    # -- the counts -------------------------------------------------------------------------
    def test_by_arm_counts_claimed_and_paid_from_the_pipeline_and_the_previews(self):
        self.interested(self.a)
        self.interested(self.b)
        self.inbox(**self.on())
        pa, pb = self.p[self.a]["place_id"], self.p[self.b]["place_id"]
        self.pipeline.write_text(json.dumps({"place_id": pa, "outcome": "won"}) + "\n")
        meta = self.tmp / "previews" / "meta"
        meta.mkdir(parents=True)
        (meta / "b.json").write_text(json.dumps({"place_id": pb, "claimed": "2026-10-20"}))
        out = self.run_it("status", "--by", "arm", **self.on()).stdout
        self.assertRegex(out, r"A Taylor\s+1\s+0 \(0\.0\)\s+1 \(100\.0\)\s+1 \(100\.0\)")
        self.assertRegex(out, r"B Patch\s+1\s+1 \(100\.0\)\s+1 \(100\.0\)\s+0 \(0\.0\)")


class Template(Base):
    def test_the_template_passes_its_check_and_a_broken_one_does_not(self):
        r = self.run_it("approve", "--template", "answer-interested")
        self.assertIn("Approved answer-interested", r.stdout)
        self.assertIn(SIGNATURE, r.stdout)
        tpl = self.tpl / "answer-interested.md"
        good = tpl.read_text()
        for bad, says in ((good.replace("Patch, Taylor's AI operator · ", "Taylor Remund · "), "never signed as him"),
                          (good.replace("Book one here: {booking_url}", "Book one here: {booking_url} {booking_url}"),
                           "{booking_url} is in the letter 2 times"),
                          (good.replace("No call needed", "Try it free for a week. No call needed"), "free week"),
                          (good.replace("it's {price_line}", "it's $20 a month"), "money that isn't {price_line}"),
                          (good.replace("claim it at {start_url}", "claim it at https://patchlamp.com/start"),
                           "{start_url} is in the letter 0 times")):
            tpl.write_text(bad)
            r = self.run_it("approve", "--template", "answer-interested", expect=1)
            self.assertIn(says, r.stdout + r.stderr)
        tpl.write_text(good)

    def test_the_check_wants_both_see_links_on_the_sending_domain(self):
        """B147: {preview_url} and {start_url} render on the sending domain; anywhere else is a problem, the
        product's own domain or not."""
        import importlib.machinery, importlib.util, os  # noqa: E401
        from test_outreach_batch import OUTREACH
        spec = importlib.util.spec_from_loader("outreach_mod", importlib.machinery.SourceFileLoader(
            "outreach_mod", str(OUTREACH)))
        mod = importlib.util.module_from_spec(spec)
        os.environ["OUTREACH_TEMPLATES"] = str(self.tpl)
        try:
            spec.loader.exec_module(mod)
            mod.TEMPLATES = self.tpl
            vals = dict(mod.sample_values(), preview_url=mod.sample_link_base() + "-site")
            _, body = mod.load_template("answer-interested").render(vals)
            self.assertEqual([], mod.interested_problems(body, vals))
            for k, url in (("start_url", "https://elsewhere.example/start?b=1"),
                           ("preview_url", "https://preview-highland-pool.pages.dev/"),
                           ("start_url", f"https://{mod.V.site_host}/start")):
                v = dict(vals, **{k: url})
                _, body = mod.load_template("answer-interested").render(v)
                self.assertTrue([p for p in mod.interested_problems(body, v) if p.startswith("{%s} is on" % k)],
                                f"{k} = {url} passed")
        finally:
            os.environ.pop("OUTREACH_TEMPLATES", None)

    def test_the_installed_body_is_the_picked_text_verbatim(self):
        picked = _pathlib.Path.home() / "projects" / "marketing" / "copy" / "2026-10-08-answer-interested.picked.json"
        if not picked.exists():
            self.skipTest("the picked brief isn't on this machine")
        want = json.loads(picked.read_text())["body"]
        raw = (self.tpl / "answer-interested.md").read_text()
        head, _, body = raw.partition("\n---\n")
        subject = [l for l in head.splitlines() if l.startswith("Subject default:")]
        self.assertEqual(want, subject[0] + "\n\n" + body.rstrip("\n"))


class LeadsArm(unittest.TestCase):
    """`leads log … --arm B --experiment E3` keeps both on the pipeline line (the smallest change to `leads`)."""

    def test_the_arm_and_the_experiment_land_on_the_pipeline_line(self):
        import os, subprocess, tempfile
        from test_leads import fixture_census
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, LEADS_STATE=tmp, LEADS_LEDGER=f"{tmp}/ledger.jsonl", CLAUDE_TOOLS_ENV=f"{tmp}/no-env",
                       LEADS_PIPELINE=f"{tmp}/pipeline.jsonl", LEADS_PREVIEWS=f"{tmp}/previews", GOOGLE_MAPS_API_KEY="",
                       LEADS_DB=str(fixture_census(_pathlib.Path(tmp) / "census.db")), LEADS_SEGMENT="")
            leads = _pathlib.Path(__file__).resolve().parent.parent / "bin" / "leads"
            for arm in (None, "B"):
                extra = ["--arm", arm, "--experiment", "E3"] if arm else []
                subprocess.run([sys.executable, str(leads), "log", "Zz Nonesuch Plumbing", "interested", "replied",
                                "--via", "email", *extra], env=env, capture_output=True, text=True, timeout=60)
            p = _pathlib.Path(tmp) / "pipeline.jsonl"
            rows = [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []
        self.assertEqual(2, len(rows), "leads log didn't write both lines")
        self.assertNotIn("arm", rows[0])
        self.assertEqual(("B", "E3"), (rows[1]["arm"], rows[1]["experiment_id"]))


if __name__ == "__main__":
    unittest.main()
