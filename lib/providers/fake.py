"""The test provider (ROADMAP B144): everything a cold-mail vendor's API does, in one JSON file.

Nothing leaves the machine. The file ($INFRA_FAKE_STATE, else fake-provider.json in $INFRA_STATE) holds
the domains it "sold", their DNS records, the mailboxes and their passwords, warm-up enrolment, the
idempotency keys it has seen (a repeated key returns the first answer, as a careful vendor's would) and
a count of every call, so a test can say "one purchase, not two".

The same file is the fake *world* (FakeWorld): the DNS answers, the logins and the seed inboxes that
bin/infra's verify and certify read back. A real run reads real DNS and real IMAP instead.

Knobs, by env (tests only):
  INFRA_FAKE_CRASH=method[:n][:before|after]   end the process (exit 75) at the n-th call of that method,
                                               before it takes effect or after (default after, n=1)
  INFRA_FAKE_HUMAN=method                      that method raises a blocking human step (no card on file)
  INFRA_FAKE_REGISTRANT=0                      no registrant-verification step after a purchase
  INFRA_FAKE_DNS_BROKEN=1                      the vendor "sets" DNS but publishes no DMARC record
  INFRA_FAKE_PLACEMENT=92                      the vendor's own placement probe, percent in the inbox
  INFRA_FAKE_SEED_FOLDER=INBOX|Spam            where a probe lands in a seed inbox
  INFRA_FAKE_AUTH=pass|fail                    the seeds' Authentication-Results verdicts
  INFRA_FAKE_WARMUP=export                     warm-up as on Infraforge (B150): an API call only when
                                               INFRA_SALESFORGE_WORKSPACE and INFRA_WARMFORGE_WORKSPACE are set,
                                               else the non-blocking click in Warmforge
"""

import json
import os
import secrets
from pathlib import Path

from providers import HumanStep, ProviderError

TITLE = "the test provider"
DOMAIN_USD_YEAR = 12.0
MAILBOX_USD_MONTH = 4.0


def state_path():
    if os.environ.get("INFRA_FAKE_STATE"):
        return Path(os.environ["INFRA_FAKE_STATE"])
    base = Path(os.environ.get("INFRA_STATE") or Path.home() / ".local/state/claude-tools/infra")
    return base / "fake-provider.json"


def load():
    p = state_path()
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {"domains": {}, "mailboxes": {}, "keys": {}, "calls": {}, "seeds": {}}


def save(st):
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, sort_keys=True))
    tmp.replace(p)


class Adapter:
    name = "fake"
    title = TITLE
    needs = ()          # env names it needs: none

    def __init__(self, get_env, dry_run=False, say=print):
        self.get, self.dry_run, self.say = get_env, dry_run, say

    # ---- the plumbing every call goes through ----------------------------------------

    def _crash(self, method, when, st):
        spec = os.environ.get("INFRA_FAKE_CRASH", "")
        if not spec:
            return
        parts = spec.split(":")
        n = int(parts[1]) if len(parts) > 1 and parts[1] else 1
        w = parts[2] if len(parts) > 2 else "after"
        if parts[0] == method and w == when and st["calls"].get(method, 0) == n:
            save(st)
            os._exit(75)

    def _mutate(self, method, key, fn):
        st = load()
        if key in st["keys"]:
            return st["keys"][key]          # the same key again: the first answer, nothing done twice
        st["calls"][method] = st["calls"].get(method, 0) + 1
        if os.environ.get("INFRA_FAKE_HUMAN") == method:
            st["calls"][method] -= 1
            save(st)
            raise HumanStep(f"card:{self.name}", "provider-card", "Add a card to the provider account",
                            ["Open the provider's dashboard → Billing.", "Add a card and save."],
                            "money", 3, then="Re-run the same `infra provision` line; it resumes.", blocking=True)
        self._crash(method, "before", st)
        out = fn(st)
        st["keys"][key] = out
        save(st)
        self._crash(method, "after", st)
        return out

    # ---- reads -----------------------------------------------------------------

    def prices(self):
        return {"domain_usd_year": DOMAIN_USD_YEAR, "mailbox_usd_month": MAILBOX_USD_MONTH}

    def available(self, name):
        st = load()
        return {"available": name not in st["domains"], "price_usd": DOMAIN_USD_YEAR}

    def domain(self, name):
        d = load()["domains"].get(name)
        return {"owned": True, "id": d["id"], "prewarmed": d.get("prewarmed", False)} if d else None

    def mailboxes(self, domain):
        return [{"address": a, "id": m["id"]} for a, m in sorted(load()["mailboxes"].items())
                if a.endswith("@" + domain)]

    def warmup(self, address):
        m = load()["mailboxes"].get(address)
        return {"enrolled": bool(m and m.get("warmup")), "days": 0} if m else None

    def placement(self, domain):
        if domain not in load()["domains"]:
            return None
        return {"inbox_pct": float(os.environ.get("INFRA_FAKE_PLACEMENT", "92")), "date": None}

    # ---- mutations -------------------------------------------------------------

    def buy_domain(self, name, key, prewarmed=False):
        def fn(st):
            if name in st["domains"]:
                raise ProviderError(f"{name} is already registered")
            st["domains"][name] = {"id": f"d-{len(st['domains']) + 1}", "dns": [], "prewarmed": prewarmed,
                                   "autorenew": True}
            st.setdefault("purchases", {})[name] = st.setdefault("purchases", {}).get(name, 0) + 1
            steps = []
            if os.environ.get("INFRA_FAKE_REGISTRANT", "1") != "0":
                steps.append(HumanStep(
                    f"registrant-verify:{name}", "domain-registrant-verify",
                    f"Click the registrant-verification link for {name}",
                    [f"Open the mail from the registrar about {name} (subject like \"verify your contact details\").",
                     "Click the link in it. That's all."],
                    "identity", 2,
                    then="Registries suspend an unverified domain after fifteen days; nothing else waits on it.",
                    blocking=False).as_dict())
            return {"id": st["domains"][name]["id"], "cost_usd": DOMAIN_USD_YEAR, "human_steps": steps}
        return self._mutate("buy_domain", key, fn)

    def set_auth_dns(self, name, key):
        def fn(st):
            d = st["domains"].get(name)
            if not d:
                raise ProviderError(f"{name} isn't in this account")
            recs = [{"type": "MX", "name": name, "value": f"10 mx.fake-provider.invalid"},
                    {"type": "TXT", "name": name, "value": "v=spf1 include:_spf.fake-provider.invalid -all"},
                    {"type": "TXT", "name": f"fk1._domainkey.{name}", "value": "v=DKIM1; k=rsa; p=MIGfMA0FAKE"}]
            if os.environ.get("INFRA_FAKE_DNS_BROKEN") != "1":
                recs.append({"type": "TXT", "name": f"_dmarc.{name}", "value": "v=DMARC1; p=none; rua=mailto:x@" + name})
            d["dns"] = [r for r in d["dns"] if r.get("by") == "us"] + recs
            return {"records": recs, "dkim_selector": "fk1"}
        return self._mutate("set_auth_dns", key, fn)

    def dns(self, name):
        d = load()["domains"].get(name)
        if not d:
            raise ProviderError(f"{name} isn't in this account")
        return [{"type": r["type"], "name": r["name"], "value": r["value"]} for r in d["dns"]]

    def set_dns(self, name, records, key):           # the real vendor's PUT replaces the whole set; so does this
        def fn(st):
            d = st["domains"].get(name)
            if not d:
                raise ProviderError(f"{name} isn't in this account")
            d["dns"] = [{"type": r["type"], "name": r["name"], "value": r["value"]} for r in records]
            return {"records": d["dns"]}
        return self._mutate("set_dns", key, fn)

    def add_txt(self, name, host, value, key):
        def fn(st):
            d = st["domains"].get(name)
            if not d:
                raise ProviderError(f"{name} isn't in this account")
            fq = name if host in ("", "@") else f"{host}.{name}"
            d["dns"].append({"type": "TXT", "name": fq, "value": value, "by": "us"})
            return {}
        return self._mutate("add_txt", key, fn)

    def remove_dns(self, name, key):
        def fn(st):
            if name in st["domains"]:
                st["domains"][name]["dns"] = []
            return {}
        return self._mutate("remove_dns", key, fn)

    def create_mailbox(self, domain, local, password, key):
        def fn(st):
            if domain not in st["domains"]:
                raise ProviderError(f"{domain} isn't in this account")
            addr = f"{local}@{domain}"
            if addr in st["mailboxes"]:
                raise ProviderError(f"{addr} already exists")
            st["mailboxes"][addr] = {"id": f"m-{len(st['mailboxes']) + 1}", "password": password, "warmup": False}
            st.setdefault("created", {})[addr] = st.setdefault("created", {}).get(addr, 0) + 1
            return {"id": st["mailboxes"][addr]["id"], "address": addr, "user": addr,
                    "smtp": "smtp.fake-provider.invalid:465", "imap": "imap.fake-provider.invalid:993",
                    "cost_usd_month": MAILBOX_USD_MONTH}
        return self._mutate("create_mailbox", key, fn)

    def delete_mailbox(self, address, key):
        def fn(st):
            st["mailboxes"].pop(address, None)
            return {}
        return self._mutate("delete_mailbox", key, fn)

    def start_warmup(self, address, key):
        if os.environ.get("INFRA_FAKE_WARMUP") == "export" and not (
                self.get("INFRA_SALESFORGE_WORKSPACE") and self.get("INFRA_WARMFORGE_WORKSPACE")):
            raise HumanStep(f"warmup:{address}", "warmup-enrol", f"Connect {address} in Warmforge and switch warm-up on",
                            ["Open Warmforge → Mailboxes → Add.", "Switch warm-up on and save."], "judgment", 2,
                            then="(automatable: the two workspace ids make it an API call)", blocking=False)

        def fn(st):
            if address not in st["mailboxes"]:
                raise ProviderError(f"{address} doesn't exist")
            st["mailboxes"][address]["warmup"] = True
            st.setdefault("exports", []).append(address)
            return {}
        return self._mutate("start_warmup", key, fn)

    def set_autorenew(self, name, on, key):
        def fn(st):
            if name in st["domains"]:
                st["domains"][name]["autorenew"] = bool(on)
            return {}
        return self._mutate("set_autorenew", key, fn)


class FakeWorld:
    """What bin/infra reads back in a test: DNS from the fake's records, logins against its passwords,
    and seed inboxes that file each probe where INFRA_FAKE_SEED_FOLDER says."""

    def txt(self, name):
        out = []
        for d in load()["domains"].values():
            out += [r["value"] for r in d["dns"] if r["type"] == "TXT" and r["name"] == name]
        return out

    def login(self, creds):
        m = load()["mailboxes"].get(str(creds.get("user")).lower())
        if not m or m["password"] != creds.get("password"):
            raise ProviderError(f"the login for {creds.get('user')} was refused")
        return True

    def send(self, creds, to, subject, body):
        self.login(creds)
        st = load()
        st.setdefault("seeds", {}).setdefault(to.lower(), []).append(
            {"subject": subject, "from": creds["user"], "folder": os.environ.get("INFRA_FAKE_SEED_FOLDER", "INBOX")})
        save(st)

    def find(self, seed, token):
        """-> (folder or None, {"spf", "dkim", "dmarc"})"""
        for m in load().get("seeds", {}).get(seed.lower(), []):
            if token in m["subject"]:
                v = os.environ.get("INFRA_FAKE_AUTH", "pass")
                return m["folder"], {"spf": v, "dkim": v, "dmarc": v}
        return None, {"spf": None, "dkim": None, "dmarc": None}
