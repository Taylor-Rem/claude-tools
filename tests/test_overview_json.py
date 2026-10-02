"""B102: the three objects the relay pushes to patchlamp.com/account/overview (plan 42).

`books pl --json`, `leads pipeline --json` and `leads week --json` leave the laptop, so they carry counts and
totals only. The fixtures here plant a lead's name, phone, email and place id, and Stripe ids and a customer
email in the balance transactions; none of those strings may appear in any of the three outputs. Each
command's human output without `--json` is pinned byte for byte, since other sessions read it.

    python3 -m unittest tests.test_overview_json   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

HERE = Path(__file__).resolve().parent
BOOKS = HERE.parent / "bin" / "books"
LEADS = HERE.parent / "bin" / "leads"

# What must never leave the laptop.
SECRETS = ["Whistle Wok", "Mike Tran", "801-555-0142", "8015550142", "mike@whistlewok.example",
           "ChIJplantedPlaceId123", "cus_PLANTED123", "pi_PLANTED456", "ch_PLANTED789", "txn_PLANTED001",
           "payer@customer.example", "American Fork"]


def books_module(tmp):
    os.environ["PROJECTS_DIR"] = str(tmp)            # no ledgers, no manual rows: Stripe only
    spec = spec_from_loader("books_mod", SourceFileLoader("books_mod", str(BOOKS)))
    m = module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def bt(id_, type_, amount, fee, created, **extra):
    """One balance transaction shaped as Stripe returns it (amounts in cents)."""
    return dict({"id": id_, "type": type_, "amount": amount, "fee": fee, "net": amount - fee, "created": created,
                 "currency": "usd", "source": "ch_PLANTED789",
                 "description": "Subscription for payer@customer.example (cus_PLANTED123)"}, **extra)


# September 2026 as the real books had it, with planted ids: a sale, a sale, a Stripe fee, a refund, two adjustments.
SEPT = [bt("txn_PLANTED001", "adjustment", 37, 0, 1788300000),
        bt("txn_2", "charge", 45000, 1335, 1789600000, source="pi_PLANTED456"),
        bt("txn_3", "payment", 9900, 317, 1789680000),
        bt("txn_4", "stripe_fee", -69, 5, 1789690000),
        bt("txn_5", "refund", -9464, 0, 1789760000),
        bt("txn_6", "adjustment", 74, 0, 1789770000),
        bt("txn_7", "payout", -43593, 0, 1789780000)]

SEPT_HUMAN = """P&L 2026-09  (Stripe: patchlamp, plateful; cash basis; Denver time)
  gross income             $549.00
  − Stripe fees             $17.21
  − refunds                 $94.64   (fees kept by Stripe on refunds already counted above)
  ± other Stripe             $1.11   (adjustments/disputes — check `books income`)
  = net income             $438.26
  = net profit             $438.26   (before the statement-only vendors: Anthropic, Twilio, Porkbun, Laravel Cloud, Resend…)
  set aside 25–30%         $109.56 – $131.48
  notional plan usage        $0.00   (Claude Max — list price of the runs; not a cash cost, never deduct)
  paid out to bank         $435.93   (transfers, not income)
"""


class BooksJson(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = os.environ.get("PROJECTS_DIR")
        self.m = books_module(Path(self.tmp.name))
        self.m.TOOL_LEDGER = self.m.RELAY_LEDGER = Path(self.tmp.name) / "no-ledger.jsonl"
        self.m.accounts = lambda: {"patchlamp": "sk_fake_a", "plateful": "sk_fake_b"}
        self.txns = {"sk_fake_a": [], "sk_fake_b": SEPT}
        self.m.balance_transactions = lambda key, start, end: list(self.txns[key])

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("PROJECTS_DIR", None)
        else:
            os.environ["PROJECTS_DIR"] = self.saved
        self.tmp.cleanup()

    def run_books(self, *argv):
        out, err, code = io.StringIO(), io.StringIO(), 0
        old = sys.argv
        sys.argv = ["books", *argv]
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self.m.main()
        except SystemExit as exc:
            code = exc.code or 0
        finally:
            sys.argv = old
        return code, out.getvalue(), err.getvalue()

    def test_the_object_is_the_contract_and_agrees_with_the_human_pl_to_the_cent(self):
        code, out, _ = self.run_books("pl", "--json", "--month", "2026-09")
        self.assertEqual(code, 0)
        self.assertEqual(out.count("\n"), 1, "one object, one line, nothing else on stdout")
        d = json.loads(out)
        self.assertEqual(d, {"ok": True, "month": "2026-09", "currency": "usd", "gross_cents": 54900,
                             "fees_cents": 1721, "refunds_cents": 9464, "other_cents": 111, "net_cents": 43826,
                             "accounts": ["patchlamp", "plateful"]})
        self.assertEqual(d["net_cents"], d["gross_cents"] - d["fees_cents"] - d["refunds_cents"] + d["other_cents"])
        _, human, _ = self.run_books("pl", "--month", "2026-09")
        self.assertIn("= net income             $438.26", human)

    def test_without_the_flag_the_pl_is_byte_for_byte_what_it_was(self):
        code, out, _ = self.run_books("pl", "--month", "2026-09")
        self.assertEqual(code, 0)
        self.assertEqual(out, SEPT_HUMAN)

    def test_no_stripe_id_description_or_email_in_the_object(self):
        _, out, _ = self.run_books("pl", "--json", "--month", "2026-09")
        for s in SECRETS:
            self.assertNotIn(s, out)
        self.assertNotIn("cus_", out)
        self.assertNotIn("@", out)

    def test_a_refunded_fee_rides_in_other_so_net_still_adds_up(self):
        self.txns["sk_fake_b"] = [bt("t1", "charge", 10000, 320, 1789600000), bt("t2", "refund", -10000, -320, 1789700000)]
        d = json.loads(self.run_books("pl", "--json", "--month", "2026-09")[1])
        self.assertEqual((d["gross_cents"], d["fees_cents"], d["refunds_cents"], d["other_cents"], d["net_cents"]),
                         (10000, 320, 10000, 320, 0))

    def test_an_account_that_cannot_be_read_is_a_failure_not_a_smaller_number(self):
        def boom(key, start, end):
            if key == "sk_fake_a":
                raise RuntimeError("Stripe 401 on /balance_transactions: Invalid API Key provided")
            return SEPT
        self.m.balance_transactions = boom
        code, out, _ = self.run_books("pl", "--json", "--month", "2026-09")
        self.assertEqual(code, 1)
        d = json.loads(out)
        self.assertFalse(d["ok"])
        self.assertIn("patchlamp", d["why"])
        self.assertNotIn("sk_fake", out)

    def test_a_failure_line_quotes_no_key_fragment_id_or_email(self):
        def boom(key, start, end):
            raise RuntimeError("Stripe 401 on /balance_transactions: Invalid API Key provided: sk_live_****abcd "
                               "for cus_PLANTED123 payer@customer.example")
        self.m.balance_transactions = boom
        code, out, _ = self.run_books("pl", "--json", "--month", "2026-09")
        self.assertEqual(code, 1)
        for s in ("sk_live", "abcd", "cus_PLANTED123", "payer@customer.example"):
            self.assertNotIn(s, out)

    def test_no_key_is_a_failure_with_a_reason(self):
        self.m.accounts = lambda: {}
        code, out, _ = self.run_books("pl", "--json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out), {"ok": False, "why": "no STRIPE_KEY_* in the toolbelt"})

    def test_a_bad_month_or_a_year_is_refused_as_json(self):
        for argv in (("--month", "2026-13"), ("--year", "2026")):
            code, out, _ = self.run_books("pl", "--json", *argv)
            self.assertEqual(code, 1)
            self.assertFalse(json.loads(out)["ok"])


class LeadsJson(unittest.TestCase):
    NOW = "2026-10-01"                  # a Thursday; the week is Monday 28 Sep

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.pipeline = t / "pipeline.jsonl"
        self.env = dict(os.environ, LEADS_PIPELINE=str(self.pipeline), LEADS_STATE=str(t / "state"),
                        LEADS_DB=str(t / "no-census.db"), LEADS_PREVIEWS=str(t / "previews"),
                        OUTREACH_STATE=str(t / "outreach"), LEADS_STRENGTH=str(t / "no-strength.md"),
                        LEADS_NOW=self.NOW, LEADS_SEGMENT="")
        rows = [
            # the planted lead: messaged last week, replied and talked this week, due today
            self.ev("2026-09-24", "place:ChIJplantedPlaceId123", "Whistle Wok", "messaged", "contacted",
                    who="Mike Tran", phone="801-555-0142", email="mike@whistlewok.example",
                    place_id="ChIJplantedPlaceId123", next="2026-09-28", note="DM to mike@whistlewok.example"),
            self.ev("2026-09-29", "place:ChIJplantedPlaceId123", "Whistle Wok", "interested", "interested",
                    note="Mike Tran asked for the demo, 8015550142", next="2026-10-01"),
            self.ev("2026-09-30", "name:b", "Bee Plumbing", "messaged", "contacted", next="2026-10-04"),
            self.ev("2026-09-30", "name:c", "Cee Cleaning", "messaged", "contacted", next="2026-10-04"),
            self.ev("2026-09-30", "name:c", "Cee Cleaning", "talked", "contacted", next="2026-09-30"),
            self.ev("2026-09-29", "name:d", "Dee Landscaping", "lost", "lost"),
            self.ev("2026-09-29", "name:e", "Eee Pools", "held", "held"),
            self.ev("2026-09-20", "name:f", "Eff Roofing", "demo", "negotiating", next="2026-10-09"),
            self.ev("2026-09-30", "name:g", "Gee Walk-in", "inbound", "interested", next="2026-10-02"),
        ]
        self.pipeline.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def ev(date, key, name, outcome, stage, **extra):
        return dict({"ts": date + "T10:00:00-06:00", "date": date, "key": key, "name": name, "city": "American Fork",
                     "outcome": outcome, "stage": stage}, **extra)

    def leads(self, *args):
        return subprocess.run([sys.executable, str(LEADS), *args], capture_output=True, text=True, env=self.env)

    def test_pipeline_json_is_every_stage_and_due_today_and_nothing_else(self):
        r = self.leads("pipeline", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("\n"), 1)
        self.assertEqual(json.loads(r.stdout), {
            "ok": True, "due_today": 2,
            "stages": {"held": 1, "contacted": 2, "interested": 2, "negotiating": 1, "trialing": 0,
                       "won": 0, "lost": 1, "churned": 0}})

    def test_week_json_is_the_numbers_the_week_prints(self):
        r = self.leads("week", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.count("\n"), 1)
        d = json.loads(r.stdout)
        self.assertEqual(d, {"ok": True, "of": "2026-09-28", "messaged": 2, "replied": 2, "talked": 3,
                             "interested": 1, "demos": 0, "won": 0, "lost": 1})
        human = self.leads("week").stdout.splitlines()[0]
        self.assertEqual(human, "Week of 28 Sep: 3 conversations, 2 messages sent · 1 interested · 0 demos · 0 won · 1 lost")
        by = self.leads("week", "--by", "channel").stdout
        self.assertIn("replies 2", by)

    def test_no_name_phone_email_or_place_id_in_either_object(self):
        for args in (("pipeline", "--json"), ("week", "--json"), ("week", "--json", "--ago", "1")):
            out = self.leads(*args).stdout
            for s in SECRETS:
                self.assertNotIn(s, out, f"{s!r} leaked from leads {' '.join(args)}")
            self.assertNotIn("@", out)

    def test_human_output_without_the_flag_is_unchanged(self):
        self.assertEqual(self.leads("pipeline").stdout,
                         "held: 1\n  Eee Pools (American Fork) · last 2026-09-29\n"
                         "contacted: 2\n"
                         "  Cee Cleaning (American Fork) · next 2026-09-30 · last 2026-09-30\n"
                         "  Bee Plumbing (American Fork) · next 2026-10-04 · last 2026-09-30\n"
                         "interested: 2\n  Whistle Wok (American Fork) · next 2026-10-01 · last 2026-09-29\n"
                         "  Gee Walk-in (American Fork) · next 2026-10-02 · last 2026-09-30\n"
                         "negotiating: 1\n  Eff Roofing (American Fork) · next 2026-10-09 · last 2026-09-20\n"
                         "lost: 1\n")

    def test_the_b52_envelope_is_still_there_with_by_channel(self):
        d = json.loads(self.leads("week", "--by", "channel", "--json").stdout)
        self.assertEqual(d["week_of"], "2026-09-28")
        self.assertIn("by_channel", d)

    def test_a_broken_pipeline_line_is_a_failure_with_a_reason(self):
        with open(self.pipeline, "a") as f:
            f.write(json.dumps({"outcome": "messaged"}) + "\n")      # no key, no date
        with open(self.pipeline, "a") as f:
            f.write(json.dumps({"key": "x", "name": "Whistle Wok", "outcome": "messaged"}) + "\n")   # no date
        r = self.leads("pipeline", "--json")
        self.assertEqual(r.returncode, 1)
        for s in SECRETS:
            self.assertNotIn(s, r.stdout)
        d = json.loads(r.stdout)
        self.assertFalse(d["ok"])
        self.assertTrue(d["why"])


if __name__ == "__main__":
    unittest.main()
