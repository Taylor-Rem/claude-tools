"""The Infraforge-class adapter (ROADMAP B144, plan 55 § 5.7): the first production line's vendor.

Why this class of vendor: its terms are written for cold outreach (the contract ceiling, plan 55
§ 3.1), the IPs are fixed and dedicated (never a vendor that swaps IPs "when they stop working", § 4.9),
and one API buys the domain, sets SPF/DKIM/DMARC, creates mailboxes and warms them.

**What is documented and what is not (2026-10-08).** Infraforge's own API reference wasn't reachable
before signup (the research brief, law-and-platforms.md § providers). Its sibling Mailforge (the same
company's shared-IP tier) publishes one at https://api.mailforge.ai/public, key in the Authorization
header: GET/POST /workspaces, GET /check-domain-availability, POST /domains (purchase), GET /domains,
GET|PUT /domains/{id}/dns, PUT /domains/{id}/enable-autorenew|disable-autorenew, POST|GET /mailboxes,
PATCH|DELETE /mailboxes/{id}; a 202 means accepted, not done; 402 means payment. The paths below follow
that shape and are marked CONFIRM: each is checked against Infraforge's reference on signup (Taylor's
account, TODO § 1) and corrected here before the first live call. Warm-up enrolment and the placement
probe are not in Mailforge's list at all, so they refuse until confirmed rather than guess an endpoint.
docs/infra.md keeps the same list.

Every method refuses with "needs INFRA_PROVIDER_API_KEY" until the key exists, and with
"needs INFRA_PROVIDER_API_BASE" until the base URL from the reference is set (no default: a guessed
host is a call to somebody else). With dry_run it prints the call it would make and makes none.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from providers import HumanStep, ProviderError

TITLE = "Infraforge"
KEY = "INFRA_PROVIDER_API_KEY"
BASE = "INFRA_PROVIDER_API_BASE"
WORKSPACE = "INFRA_PROVIDER_WORKSPACE"          # the vendor's workspace id, if its API scopes by one
TIMEOUT = 30
UNCONFIRMED = ("warm-up enrolment", "the placement probe")   # not in the sibling's documented list


class Adapter:
    name = "infraforge"
    title = TITLE
    needs = (KEY, BASE)

    def __init__(self, get_env, dry_run=False, say=print):
        self.get, self.dry_run, self.say = get_env, dry_run, say

    # ---- the wire ----------------------------------------------------------------

    def _req(self, method, path, body=None, query=None, key=None):
        base = (self.get(BASE) or "").rstrip("/")
        url_path = path + ("?" + urllib.parse.urlencode(query) if query else "")
        if self.dry_run:
            self.say(f"  [dry-run] {method} {{{BASE}}}{url_path}" + (f"  {json.dumps(body, sort_keys=True)}" if body else "")
                     + (f"  Idempotency-Key: {key}" if key else ""))
            return {"dry_run": True}
        api_key = self.get(KEY)
        if not api_key:
            raise ProviderError(f"needs {KEY} (TODO § 1 \"The production line's provider\": the key from its "
                                "dashboard, set with setenv.sh)")
        if not base:
            raise ProviderError(f"needs {BASE}: the API's base URL from Infraforge's reference, read on signup "
                                "(docs/infra.md, 'confirmed on signup')")
        headers = {"Authorization": api_key, "Accept": "application/json", "User-Agent": "claude-tools infra"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if key:
            headers["Idempotency-Key"] = key          # CONFIRM: honoured or ignored; harmless either way
        req = urllib.request.Request(base + url_path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 402:
                raise HumanStep(f"card:{self.name}", "provider-card", "Add a card or raise the plan at Infraforge",
                                ["Open Infraforge's dashboard → Billing.",
                                 "Add a card, or move to a plan that allows the mailboxes asked for, and save."],
                                "money", 5, then="Re-run the same `infra provision` line; it resumes where it stopped.",
                                blocking=True) from None
            raise ProviderError(f"{method} {path}: HTTP {e.code}") from None
        except (urllib.error.URLError, OSError) as e:
            raise ProviderError(f"{method} {path}: {type(e).__name__}") from None
        try:
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            raise ProviderError(f"{method} {path}: the answer wasn't JSON") from None

    @staticmethod
    def _items(got):
        if isinstance(got, list):
            return got
        return (got or {}).get("data") or (got or {}).get("items") or []

    # ---- reads -------------------------------------------------------------------

    def prices(self):
        # Published prices (infraforge.ai/pricing, 2026-10): $3–4 a mailbox a month; a domain ~$12–15 a year.
        return {"domain_usd_year": 15.0, "mailbox_usd_month": 4.0}

    def available(self, name):                      # CONFIRM: GET /check-domain-availability?domain=
        got = self._req("GET", "/check-domain-availability", query={"domain": name})
        if got.get("dry_run"):
            return {"available": True, "price_usd": self.prices()["domain_usd_year"]}
        return {"available": bool(got.get("available")), "price_usd": float(got.get("price") or 0)}

    def _domain_row(self, name):
        for d in self._items(self._req("GET", "/domains")):
            if str(d.get("name") or d.get("domain") or "").lower() == name:
                return d
        return None

    def domain(self, name):                         # CONFIRM: GET /domains
        if self.dry_run:
            self._req("GET", "/domains")
            return None
        d = self._domain_row(name)
        return {"owned": True, "id": d.get("id"), "prewarmed": bool(d.get("prewarmed"))} if d else None

    def mailboxes(self, domain):                    # CONFIRM: GET /mailboxes?domain=
        got = self._req("GET", "/mailboxes", query={"domain": domain})
        return [{"address": str(m.get("email") or m.get("address") or "").lower(), "id": m.get("id")}
                for m in self._items(got) if str(m.get("email") or m.get("address") or "").endswith("@" + domain)]

    def warmup(self, address):
        return None                                 # unconfirmed: the vendor's word is the lowest-trust signal anyway

    def placement(self, domain):
        return None                                 # unconfirmed; certification rests on our own seeds

    # ---- mutations ---------------------------------------------------------------

    def _domain_id(self, name):
        if self.dry_run:
            return "{id}"
        d = self._domain_row(name)
        if not d:
            raise ProviderError(f"{name} isn't in the Infraforge account")
        return d.get("id")

    def buy_domain(self, name, key, prewarmed=False):   # CONFIRM: POST /domains {"domains": [..]}
        body = {"domains": [name]}
        if self.get(WORKSPACE):
            body["workspaceId"] = self.get(WORKSPACE)
        if prewarmed:
            body["prewarmed"] = True                # CONFIRM: how pre-warmed inventory is chosen
        got = self._req("POST", "/domains", body=body, key=key)
        return {"id": got.get("id"), "cost_usd": float(got.get("price") or self.prices()["domain_usd_year"]),
                "human_steps": []}

    def set_auth_dns(self, name, key):               # CONFIRM: the vendor sets SPF/DKIM/DMARC itself on purchase;
        did = self._domain_id(name)                  # we read its records back and let verify judge them
        got = self._req("GET", f"/domains/{did}/dns")
        recs = [{"type": r.get("type"), "name": r.get("name") or r.get("host"), "value": r.get("value")}
                for r in self._items(got)]
        sel = next((str(r["name"]).split("._domainkey")[0] for r in recs if "_domainkey" in str(r["name"] or "")), None)
        return {"records": recs, "dkim_selector": sel}

    def add_txt(self, name, host, value, key):       # CONFIRM: PUT /domains/{id}/dns
        did = self._domain_id(name)
        self._req("PUT", f"/domains/{did}/dns", body={"records": [{"type": "TXT", "host": host or "@", "value": value}]},
                  key=key)
        return {}

    def remove_dns(self, name, key):
        raise HumanStep(f"remove-dns:{name}", "dns-record", f"Remove the mail records of {name} at Infraforge",
                        [f"Open Infraforge's dashboard → Domains → {name} → DNS.",
                         "Delete the MX, SPF, DKIM and DMARC records and save."],
                        "judgment", 3, then="Nothing else waits on it: the mailboxes are already gone. "
                        "(automatable: once the DNS-delete endpoint is confirmed on signup)", blocking=False)

    def create_mailbox(self, domain, local, password, key):   # CONFIRM: POST /mailboxes; password accepted?
        body = {"mailboxes": [{"email": f"{local}@{domain}", "password": password}]}
        got = self._req("POST", "/mailboxes", body=body, key=key)
        m = (self._items(got) or [got])[0] if not got.get("dry_run") else {}
        return {"id": m.get("id"), "address": f"{local}@{domain}", "user": f"{local}@{domain}",
                "smtp": m.get("smtp_host") and f"{m['smtp_host']}:{m.get('smtp_port') or 465}",
                "imap": m.get("imap_host") and f"{m['imap_host']}:{m.get('imap_port') or 993}",
                "cost_usd_month": self.prices()["mailbox_usd_month"]}

    def delete_mailbox(self, address, key):          # CONFIRM: DELETE /mailboxes/{id}
        mid = "{id}"
        if not self.dry_run:
            hit = [m for m in self.mailboxes(address.split("@", 1)[1]) if m["address"] == address]
            if not hit:
                return {}
            mid = hit[0]["id"]
        self._req("DELETE", f"/mailboxes/{mid}", key=key)
        return {}

    def start_warmup(self, address, key):
        # Not in the documented API yet: a dashboard switch until it is confirmed on signup.
        raise HumanStep(f"warmup:{address}", "warmup-enrol", f"Turn on warm-up for {address} at Infraforge",
                        [f"Open Infraforge's dashboard → Mailboxes → {address}.",
                         "Switch warm-up on (the vendor's default schedule) and save."],
                        "judgment", 2, then="Certification counts fourteen days of warming from the day it is on. "
                        "(automatable: once the warm-up endpoint is confirmed on signup)", blocking=False)

    def set_autorenew(self, name, on, key):          # CONFIRM: PUT /domains/{id}/enable-autorenew|disable-autorenew
        did = self._domain_id(name)
        self._req("PUT", f"/domains/{did}/{'enable' if on else 'disable'}-autorenew", key=key)
        return {}
