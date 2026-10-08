"""The Factory (ROADMAP B144, plan 55 § 5.7): `infra` against the fake provider.

    python3 -m unittest tests.test_infra   (from claude-tools/)

Every run gets its own state dir, ledger, TODO file, env file and registry, and the fake provider keeps
its world in a JSON file there, so nothing reaches the network, the real key file or Taylor's list.
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
import unittest  # noqa: E402
from pathlib import Path  # noqa: E402

import assets  # noqa: E402
import outreach_mail as mail  # noqa: E402

TOOLS = Path(__file__).resolve().parent.parent
INFRA = TOOLS / "bin" / "infra"
D = "send-one.example"
TODO = "# T\n\n## 1. Now\n\n- [ ] **An older entry.** text\n\n### 1b. Waiting\n\n- [ ] **Waiting.**\n\n## 3. Decisions\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="infra-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "TODO.md").write_text(TODO)
        (self.tmp / "env").write_text("SOME_OTHER_KEY=keep-me\n")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("INFRA_", "FACTORY_"))}
        self.env.update(INFRA_STATE=str(self.tmp / "infra"), INFRA_LEDGER=str(self.tmp / "ledger.jsonl"),
                        TODO_FILE=str(self.tmp / "TODO.md"), CLAUDE_TOOLS_ENV=str(self.tmp / "env"),
                        ASSETS_DB=str(self.tmp / "assets.db"), OUTREACH_STATE=str(self.tmp / "outreach"),
                        INFRA_PROVIDER="fake", INFRA_NOW="2026-10-08T15:00:00+00:00", VENTURE="patchlamp")

    def run_infra(self, *args, ok=True, **env):
        e = dict(self.env, **{k: str(v) for k, v in env.items()})
        r = subprocess.run([sys.executable, str(INFRA), *args], capture_output=True, text=True, env=e, timeout=60)
        if ok is True and r.returncode != 0:
            self.fail(f"infra {' '.join(args)} exited {r.returncode}:\n{r.stdout}\n{r.stderr}")
        if isinstance(ok, int) and ok is not True and r.returncode != ok:
            self.fail(f"infra {' '.join(args)} exited {r.returncode}, wanted {ok}:\n{r.stdout}\n{r.stderr}")
        return r

    def provision(self, *extra, ok=True, **env):
        return self.run_infra("provision", "--domain", D, "--mailboxes", "2", "--go", *extra, ok=ok, **env)

    def ledger(self):
        p = self.tmp / "ledger.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def intents(self):
        return [r for r in self.ledger() if r["phase"] == "intent"]

    def fake(self):
        p = self.tmp / "infra" / "fake-provider.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def rows(self):
        return {(r["kind"], r["name"]): r for r in assets.Registry(self.tmp / "assets.db").rows("patchlamp")}

    def todo(self):
        return (self.tmp / "TODO.md").read_text()

    def env_names(self):
        return [l.split("=", 1)[0] for l in (self.tmp / "env").read_text().splitlines() if "=" in l]


class ProvisionTest(Base):
    def test_without_go_it_only_plans(self):
        r = self.run_infra("provision", "--domain", D)
        self.assertIn("PLAN", r.stdout)
        self.assertIn("Nothing was bought or changed", r.stdout)
        self.assertIn("--go", r.stdout)
        self.assertEqual(self.ledger(), [])
        self.assertEqual(self.fake(), {})
        self.assertFalse((self.tmp / "infra" / "ops").exists())

    def test_plan_apply_verify_commit(self):
        r = self.provision()
        for word in ("PLAN", "VERIFY", "COMMIT"):
            self.assertIn(word, r.stdout)
        rows = self.rows()
        boxes = [n for k, n in rows if k == "mailbox"]
        self.assertEqual(sorted(boxes), sorted(f"{l}@{D}" for l in ("taylor", "taylor.remund")))
        for key in [("domain", D)] + [("mailbox", b) for b in boxes]:
            self.assertEqual(rows[key]["state"], "warming", key)
        self.assertEqual(rows[("provider", "fake")]["contract"], "PERMITTED")
        # one intent line per external call, each with its own key, before the call
        keys = [r["key"] for r in self.intents()]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(sorted(r["call"] for r in self.intents()),
                         sorted(["buy_domain", "set_auth_dns", "create_mailbox", "create_mailbox",
                                 "start_warmup", "start_warmup"]))
        self.assertTrue(all(r["venture"] == "patchlamp" and r["tenant"] == "patchlamp" for r in self.ledger()))
        commit = [r for r in self.ledger() if r["phase"] == "commit"]
        self.assertEqual(len(commit), 1)
        self.assertEqual(commit[0]["cost_usd"], 12.0)
        # credentials by asset id, never printed
        for b in boxes:
            aid = rows[("mailbox", b)]["id"]
            self.assertIn(f"OUTREACH_MAILBOX_{aid}_PASSWORD", self.env_names())
            self.assertIn(f"OUTREACH_MAILBOX_{aid}_*", rows[("mailbox", b)]["note"])
        pw = self.fake()["mailboxes"][boxes[0]]["password"]
        self.assertNotIn(pw, r.stdout + r.stderr)
        self.assertNotIn(pw, (self.tmp / "ledger.jsonl").read_text())
        self.assertIn("SOME_OTHER_KEY", self.env_names())
        # the human steps, filed once each with repeat keys, inside § 1 and above § 1b
        todo = self.todo()
        self.assertIn("repeat_key=domain-registrant-verify", todo)
        self.assertIn("repeat_key=postmaster-add-domain", todo)
        self.assertLess(todo.index("postmaster-add-domain"), todo.index("### 1b"))
        # a second run repeats nothing
        before = len(self.ledger())
        r2 = self.provision()
        self.assertIn("already provisioned", r2.stdout)
        self.assertEqual(len(self.ledger()), before)
        self.assertEqual(self.todo().count("infra_step=postmaster-add:"), 1)

    def test_crash_mid_apply_resumes_and_buys_once(self):
        r = self.provision(ok=75, INFRA_FAKE_CRASH="create_mailbox:2:after")
        self.assertNotIn("COMMIT", r.stdout)
        self.assertEqual(self.rows()[("domain", D)]["state"], "provisioning")
        self.provision()
        f = self.fake()
        self.assertEqual(f["purchases"], {D: 1})
        self.assertEqual(set(f["created"].values()), {1})
        self.assertEqual(f["calls"]["buy_domain"], 1)
        keys = [r["key"] for r in self.intents()]
        self.assertEqual(len(keys), len(set(keys)), "a resumed run writes no second intent line for a key")
        self.assertEqual(self.rows()[("domain", D)]["state"], "warming")

    def test_crash_after_the_purchase_is_found_not_repeated(self):
        self.provision(ok=75, INFRA_FAKE_CRASH="buy_domain:1:after")
        r = self.provision()
        self.assertIn("found at the provider", r.stdout)
        self.assertEqual(self.fake()["purchases"], {D: 1})

    def test_a_purchase_with_no_trace_is_never_repeated_blindly(self):
        self.provision(ok=75, INFRA_FAKE_CRASH="buy_domain:1:before")
        self.assertEqual(self.fake().get("purchases", {}), {})
        self.assertEqual([r["key"] for r in self.intents()], [f"provision-{D}:buy"], "the key is written before the call")
        r = self.provision(ok=6)
        self.assertIn("--retry-purchase", r.stderr)
        self.assertEqual(self.fake().get("purchases", {}), {})
        self.provision("--retry-purchase")
        self.assertEqual(self.fake()["purchases"], {D: 1})
        self.assertEqual([r["key"] for r in self.intents()].count(f"provision-{D}:buy"), 1)

    def test_a_blocking_human_step_is_filed_once_and_resumes(self):
        for _ in range(2):
            r = self.provision(ok=3, INFRA_FAKE_HUMAN="buy_domain")
            self.assertIn("TAYLOR-TODO", r.stderr)
        self.assertEqual(self.todo().count("repeat_key=provider-card"), 1)
        self.assertEqual(self.fake().get("purchases", {}), {})
        self.provision()
        self.assertEqual(self.fake()["purchases"], {D: 1})

    def test_verify_reads_the_world_and_rollback_never_rebuys(self):
        r = self.provision(ok=4, INFRA_FAKE_DNS_BROKEN="1")
        self.assertIn("no DMARC record", r.stdout)
        rows = self.rows()
        self.assertEqual(rows[("domain", D)]["state"], "provisioning")
        ev = assets.Registry(self.tmp / "assets.db").events(asset_id=rows[("domain", D)]["id"], kind="incident")
        self.assertTrue(ev and "verify failed" in ev[0]["text"])
        self.run_infra("rollback", f"provision-{D}")
        f = self.fake()
        self.assertEqual(f["mailboxes"], {})
        self.assertFalse(f["domains"][D]["autorenew"])
        self.assertEqual(f["purchases"], {D: 1})
        self.assertFalse(any(n.startswith("OUTREACH_MAILBOX_") for n in self.env_names()))
        self.assertEqual({r["state"] for (k, n), r in self.rows().items() if k in ("domain", "mailbox")}, {"retired"})
        r = self.provision(ok=2)
        self.assertIn("never bought twice", r.stderr)
        self.assertEqual(self.fake()["purchases"], {D: 1})

    def test_no_verdict_no_provision(self):
        r = self.run_infra("provision", "--domain", D, "--provider", "infraforge", "--go", ok=2)
        self.assertIn("no PERMITTED contract verdict", r.stderr)
        self.assertIn("repeat_key=provider-terms-verdict", self.todo())
        self.assertEqual(self.ledger(), [])
        self.run_infra("contract", "infraforge", "--verdict", "PERMITTED", "--clause", "built for cold outreach",
                       "--read", "2026-10-09", "--word", "Taylor, 2026-10-09, by text")
        r = self.run_infra("provision", "--domain", D, "--provider", "infraforge", "--go", ok=2)
        self.assertIn("INFRA_PROVIDER_API_KEY", r.stderr)
        r = self.run_infra("provision", "--domain", D, "--provider", "infraforge", "--go", "--dry-run")
        self.assertIn("POST {INFRA_PROVIDER_API_BASE}/domains", r.stdout)
        self.assertIn("POST {INFRA_PROVIDER_API_BASE}/mailboxes", r.stdout)
        self.assertEqual(self.ledger(), [])

    def test_contract_needs_whose_word(self):
        r = self.run_infra("contract", "infraforge", "--verdict", "PERMITTED", "--clause", "x", ok=1)
        self.assertIn("--word", r.stderr)

    def test_limits(self):
        r = self.provision(ok=2, INFRA_USD_PER_DAY="5")
        self.assertIn("INFRA_USD_PER_DAY", r.stderr)
        self.assertEqual(self.fake(), {})
        self.provision(INFRA_UNITS_PER_WEEK="1")
        r = self.run_infra("provision", "--domain", "send-two.example", "--go", ok=2, INFRA_UNITS_PER_WEEK="1")
        self.assertIn("INFRA_UNITS_PER_WEEK", r.stderr)


class HaltTest(Base):
    def test_halt_blocks_mutations_and_reads_go_on(self):
        self.run_infra("halt", "testing the stop")
        r = self.provision(ok=5)
        self.assertIn("halted", r.stderr)
        self.assertEqual(self.ledger(), [])
        self.assertEqual(self.fake().get("purchases", {}), {})
        self.assertIn("HALTED", self.run_infra("status").stdout)
        self.run_infra("plan", "--pool", "100")
        self.run_infra("resume")
        self.provision()
        self.assertEqual(self.rows()[("domain", D)]["state"], "warming")

    def test_env_halt(self):
        self.provision(ok=5, FACTORY_HALT="1")
        self.assertEqual(self.ledger(), [])
        r = self.run_infra("resume", FACTORY_HALT="1")
        self.assertIn("Still halted", r.stdout)

    def test_halt_blocks_rollback_and_seed_sends(self):
        self.provision(ok=4, INFRA_FAKE_DNS_BROKEN="1")
        self.run_infra("halt")
        self.run_infra("rollback", D, ok=5)
        self.assertTrue(self.fake()["mailboxes"])
        self.run_infra("seeds", "send", D, ok=5, INFRA_SEED_INBOXES="a@gmail.example")


class CertifyTest(Base):
    SEEDS = "seed1@gmail.example,seed2@outlook.example,seed3@ws.example"

    def ready(self, days=15):
        """Provisioned, then a seed round a day for `days` days, read back, and Postmaster reading."""
        self.provision()
        start = dt.datetime(2026, 10, 8, 15, tzinfo=dt.timezone.utc)
        for i in range(days):
            t = (start + dt.timedelta(days=i + 1)).isoformat()
            self.run_infra("seeds", "send", D, INFRA_NOW=t, INFRA_SEED_INBOXES=self.SEEDS)
            self.run_infra("seeds", "read", D, INFRA_NOW=t, INFRA_SEED_INBOXES=self.SEEDS)
        self.when = (start + dt.timedelta(days=days)).isoformat()
        out = self.tmp / "outreach"
        out.mkdir(exist_ok=True)
        with open(out / "postmaster-fetch.jsonl", "a") as f:
            f.write(json.dumps({"ts": self.when, "domain": D, "outcome": "no data", "detail": ""}) + "\n")

    def tick_todo(self):
        (self.tmp / "TODO.md").write_text(self.todo().replace("- [ ] **Click the registrant", "- [x] **Click the registrant")
                                          .replace("- [ ] **Add send-one", "- [x] **Add send-one")
                                          .replace("- [ ] **Make three seed", "- [x] **Make three seed"))

    def test_refuses_until_every_check_passes(self):
        self.provision()
        r = self.run_infra("certify", D, ok=1)
        for line in ("FAIL  seeds are ours", "FAIL  placement", "FAIL  warming", "FAIL  Postmaster",
                     "FAIL  no human step open"):
            self.assertIn(line, r.stdout)
        self.assertIn("repeat_key=seed-inboxes", self.todo())
        self.assertEqual(self.rows()[("domain", D)]["state"], "warming")

    def test_certifies_when_everything_passes(self):
        self.ready()
        r = self.run_infra("certify", D, ok=1, INFRA_NOW=self.when, INFRA_SEED_INBOXES=self.SEEDS)
        self.assertIn("FAIL  no human step open", r.stdout)
        self.tick_todo()
        r = self.run_infra("certify", D, INFRA_NOW=self.when, INFRA_SEED_INBOXES=self.SEEDS)
        self.assertNotIn("FAIL", r.stdout)
        rows = self.rows()
        self.assertEqual({r["state"] for (k, n), r in rows.items() if k in ("domain", "mailbox")}, {"active"})
        reading = assets.Registry(self.tmp / "assets.db").readings(rows[("domain", D)]["id"])
        self.assertEqual(reading[-1]["metric"], "inbox_pct")

    def test_spam_placement_fails(self):
        self.provision()
        self.run_infra("seeds", "send", D, INFRA_SEED_INBOXES=self.SEEDS, INFRA_FAKE_SEED_FOLDER="[Gmail]/Spam")
        self.run_infra("seeds", "read", D, INFRA_SEED_INBOXES=self.SEEDS)
        r = self.run_infra("certify", D, ok=1, INFRA_SEED_INBOXES=self.SEEDS)
        self.assertIn("[Gmail]/Spam", r.stdout)

    def test_a_seed_on_a_sending_domain_is_not_ours(self):
        self.provision()
        r = self.run_infra("certify", D, ok=1, INFRA_SEED_INBOXES=f"probe@{D}")
        self.assertIn("unknown to the vendor", r.stdout)

    def test_auth_failure_at_the_receiver_fails(self):
        self.ready(days=8)
        self.run_infra("seeds", "send", D, INFRA_NOW=self.when, INFRA_SEED_INBOXES=self.SEEDS)
        self.run_infra("seeds", "read", D, INFRA_NOW=self.when, INFRA_SEED_INBOXES=self.SEEDS, INFRA_FAKE_AUTH="fail")
        r = self.run_infra("certify", D, ok=1, INFRA_NOW=self.when, INFRA_SEED_INBOXES=self.SEEDS)
        self.assertIn("FAIL  spf, dkim, dmarc pass", r.stdout)
        self.assertIn("FAIL  warming", r.stdout)


class PlanStatusTest(Base):
    def test_plan_without_pool_proposes_nothing(self):
        r = self.run_infra("plan")
        self.assertIn("can't say without the pool", r.stdout)

    def test_plan_counts_the_half_rule(self):
        n = json.loads(self.run_infra("plan", "--pool", "2000", "--json").stdout)
        self.assertEqual(n["unit_first_per_day"], 30.0)        # 2 × 2 × 15, half behind one contract
        self.assertEqual(n["units_wanted"], 4)                  # 2000 / (30 × 21) → 4
        self.provision()
        n = json.loads(self.run_infra("plan", "--pool", "2000", "--json").stdout)
        self.assertEqual(n["warming_first_per_day"], 15.0)
        self.assertEqual(self.ledger()[-1]["phase"], "commit", "plan wrote nothing")

    def test_status_json(self):
        self.provision()
        s = json.loads(self.run_infra("status", "--json").stdout)
        self.assertFalse(s["halted"])
        self.assertEqual(s["ops"][0]["phase"], "committed")
        self.assertEqual(sorted(h["key"] for h in s["human_open"]),
                         sorted([f"registrant-verify:{D}", f"postmaster-add:{D}", "seed-inboxes"]))

    def test_dns_txt(self):
        self.provision()
        r = self.run_infra("dns-txt", D, "google-site-verification=abc")
        self.assertIn("visible in DNS", r.stdout)
        self.run_infra("dns-txt", D, "google-site-verification=abc")
        self.assertEqual([x["call"] for x in self.intents()].count("add_txt"), 1)


class CredentialsTest(unittest.TestCase):
    def test_asset_first_then_the_app_password(self):
        env = {"OUTREACH_MAILBOX_7_PASSWORD": "a", "OUTREACH_MAILBOX_7_SMTP": "smtp.x:465",
               mail.app_password_name("t@one.example"): "b"}
        c = mail.credentials("t@one.example", env.get, asset_id=7, imap_default="imap.lane:993")
        self.assertEqual((c["password"], c["user"], c["smtp"], c["imap"]), ("a", "t@one.example", "smtp.x:465", "imap.lane:993"))
        c = mail.credentials("t@one.example", env.get, asset_id=8)
        self.assertEqual(c["password"], "b")
        self.assertIsNone(mail.credentials("u@one.example", env.get))
        self.assertEqual(mail.credential_name("u@one.example", 9), "OUTREACH_MAILBOX_9_PASSWORD")

    def test_asset_id_of_reads_without_creating(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "assets.db"
            self.assertIsNone(mail.asset_id_of("a@x.example", "t", db))
            self.assertFalse(db.exists())
            reg = assets.Registry(db)
            mid = reg.ensure("t", "mailbox", "a@x.example")
            self.assertEqual(mail.asset_id_of("A@x.example", "t", db), mid)
            self.assertIsNone(mail.asset_id_of("a@x.example", "other", db))

    def test_auth_results(self):
        raw = b"Authentication-Results: mx.example; dkim=pass header.i=@x; spf=softfail smtp.mailfrom=y; dmarc=fail\r\n\r\n"
        self.assertEqual(mail.auth_results(raw), {"spf": "softfail", "dkim": "pass", "dmarc": "fail"})


class TickTest(Base):
    """B150: the daily tick. It certifies what's due, proposes a unit when the pool outruns thirty days of
    capacity, files the proposal for the morning message, and buys nothing until sixty clean days."""

    def pool(self, n):
        script = self.tmp / "pool.py"
        script.write_text(f"import json; print(json.dumps({{'qualify': {n}, 'with_address': 9999}}))\n")
        return f"{sys.executable} {script}"

    def proposal(self):
        return json.loads((self.tmp / "infra" / "proposal.json").read_text())

    def test_proposes_a_unit_and_buys_nothing_before_sixty_days(self):
        r = self.run_infra("tick", INFRA_POOL_CMD=self.pool(2000), INFRA_AUTO_PURCHASE="1")
        p = self.proposal()
        self.assertEqual(p["units_wanted"], 4)
        self.assertEqual(p["bought"], [])
        self.assertEqual(len(p["names"]), 2)                       # INFRA_UNITS_PER_WEEK's two
        self.assertIn("waits on Taylor's go until sixty clean days (no unit yet)", p["line"])
        self.assertIn("infra provision --domain", p["line"])
        self.assertNotIn("purchases", self.fake())
        self.assertIn("proposal: Factory:", r.stdout)
        self.provision()                                            # a unit, Taylor's go: day 0 of 60
        self.run_infra("tick", INFRA_POOL_CMD=self.pool(2000), INFRA_AUTO_PURCHASE="1",
                       INFRA_NOW="2026-11-20T15:00:00+00:00")
        p = self.proposal()
        self.assertEqual(p["clean_days"], 43)
        self.assertEqual(p["bought"], [])
        self.assertIn("43 of 60", p["line"])
        self.assertEqual(list(self.fake()["purchases"]), [D])

    def test_covered_pool_proposes_nothing(self):
        self.run_infra("tick", INFRA_POOL_CMD=self.pool(0))
        p = self.proposal()
        self.assertEqual(p["units_wanted"], 0)
        self.assertEqual(p["line"], "")

    def test_no_pool_is_said_not_guessed(self):
        r = self.run_infra("tick", INFRA_POOL_CMD=f"{sys.executable} -c pass")
        self.assertIn("couldn't: no pool", r.stdout)
        self.assertEqual(self.proposal()["units_wanted"], None)

    def test_after_sixty_clean_days_with_the_flag_it_buys_under_the_caps(self):
        self.provision()
        later = "2026-12-08T15:00:00+00:00"                          # 61 days on
        self.run_infra("tick", INFRA_POOL_CMD=self.pool(2000), INFRA_NOW=later)
        self.assertEqual(self.proposal()["bought"], [], "no INFRA_AUTO_PURCHASE, no purchase")
        r = self.run_infra("tick", INFRA_POOL_CMD=self.pool(2000), INFRA_NOW=later, INFRA_AUTO_PURCHASE="1")
        p = self.proposal()
        self.assertEqual(len(p["bought"]), 2, r.stdout)
        self.assertIn("61 clean days and INFRA_AUTO_PURCHASE=1", p["line"])
        self.assertEqual(len(self.fake()["purchases"]), 3)
        rows = self.rows()
        for d in p["bought"]:
            self.assertEqual(rows[("domain", d)]["state"], "warming")
            self.assertNotIn(d, ("patchlamp.com",))
        r = self.run_infra("tick", INFRA_POOL_CMD=self.pool(2000), INFRA_NOW=later, INFRA_AUTO_PURCHASE="1")
        self.assertEqual(self.proposal()["bought"], [], "the week's two units are spent")
        self.assertIn("INFRA_UNITS_PER_WEEK is spent", self.proposal()["line"])

    def test_an_incident_restarts_the_clean_days(self):
        self.provision()
        reg = assets.Registry(self.tmp / "assets.db")
        did = reg.find("patchlamp", f"domain:{D}")["id"]
        reg.incident(did, "a bounce storm", now=dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc))
        self.run_infra("tick", INFRA_POOL_CMD=self.pool(2000), INFRA_NOW="2026-12-08T15:00:00+00:00",
                       INFRA_AUTO_PURCHASE="1")
        p = self.proposal()
        self.assertEqual(p["clean_days"], 37)
        self.assertEqual(p["bought"], [])

    def test_the_weekend_only_certifies(self):
        r = self.run_infra("tick", INFRA_POOL_CMD=self.pool(2000), INFRA_NOW="2026-10-10T15:00:00+00:00")
        self.assertIn("weekends only certify", r.stdout)
        self.assertNotIn("units_wanted", self.proposal())


class TickCertifyTest(CertifyTest):
    def test_the_tick_certifies_a_domain_past_its_date(self):
        self.ready()
        self.tick_todo()
        early = "2026-10-15T15:00:00+00:00"
        r = self.run_infra("tick", "--pool", "0", INFRA_NOW=early, INFRA_SEED_INBOXES=self.SEEDS)
        self.assertIn(f"certify {D}: due 2026-10-22", r.stdout)
        self.assertEqual(self.rows()[("domain", D)]["state"], "warming")
        r = self.run_infra("tick", "--pool", "0", INFRA_NOW=self.when, INFRA_SEED_INBOXES=self.SEEDS)
        self.assertEqual(self.rows()[("domain", D)]["state"], "active", r.stdout)
        self.assertIn(D, self.proposal_line())
        st = self.run_infra("status", INFRA_NOW=self.when).stdout
        self.assertIn("this week the Factory added 2 mailbox(es) to the lane", st)

    def proposal_line(self):
        return json.loads((self.tmp / "infra" / "proposal.json").read_text())["line"]


class WarmupTest(Base):
    IDS = {"INFRA_SALESFORGE_WORKSPACE": "sf-1", "INFRA_WARMFORGE_WORKSPACE": "wf-1"}

    def test_without_the_ids_it_is_a_filed_click_and_warmup_turns_it_on_by_api(self):
        self.provision(INFRA_FAKE_WARMUP="export")
        self.assertIn("infra_step=warmup:", self.todo())
        self.assertEqual(self.fake().get("exports"), None)
        r = self.run_infra("warmup", INFRA_FAKE_WARMUP="export")
        self.assertIn("2 Factory mailbox(es) wait on it", r.stdout)
        self.assertIn("INFRA_SALESFORGE_WORKSPACE and INFRA_WARMFORGE_WORKSPACE unset", r.stdout)
        r = self.run_infra("warmup", "--go", INFRA_FAKE_WARMUP="export")
        self.assertIn("0 on, 2 still a click", r.stdout)
        self.assertEqual(self.todo().count("infra_step=warmup:"), 2, "filed twice")
        r = self.run_infra("warmup", "--go", INFRA_FAKE_WARMUP="export", **self.IDS)
        self.assertIn("2 on, 0 still a click, 0 failed", r.stdout)
        self.assertIn("read back: the vendor shows it enrolled", r.stdout)
        self.assertEqual(len(self.fake()["exports"]), 2)
        self.assertNotIn("- [ ] **Connect", self.todo())
        self.assertIn("done by the Factory", self.todo())
        j = json.loads((self.tmp / "infra" / "ops" / f"provision-{D}.json").read_text())
        self.assertFalse([k for k in j["human"] if k.startswith("warmup:")])
        self.assertIn("nothing to do", self.run_infra("warmup", "--go", INFRA_FAKE_WARMUP="export", **self.IDS).stdout)

    def test_a_click_ticked_in_todo_is_never_exported_again(self):
        self.provision(INFRA_FAKE_WARMUP="export")
        (self.tmp / "TODO.md").write_text(self.todo().replace("- [ ] **Connect", "- [x] **Connect"))
        r = self.run_infra("warmup", "--go", INFRA_FAKE_WARMUP="export", **self.IDS)
        self.assertIn("not called again", r.stdout)
        self.assertIn("nothing to do", r.stdout)
        self.assertEqual(self.fake().get("exports"), None)
        j = json.loads((self.tmp / "infra" / "ops" / f"provision-{D}.json").read_text())
        self.assertEqual({j["steps"][k]["status"] for k in j["steps"] if k.startswith("warmup:")}, {"done"})

    def test_with_the_ids_provision_warms_by_api(self):
        self.provision(INFRA_FAKE_WARMUP="export", **self.IDS)
        self.assertNotIn("infra_step=warmup:", self.todo())
        self.assertEqual(len(self.fake()["exports"]), 2)

    def test_halted_warmup_calls_nothing(self):
        self.provision(INFRA_FAKE_WARMUP="export")
        self.run_infra("halt", "test")
        self.run_infra("warmup", "--go", ok=5, INFRA_FAKE_WARMUP="export", **self.IDS)
        self.assertEqual(self.fake().get("exports"), None)


if __name__ == "__main__":
    unittest.main()
