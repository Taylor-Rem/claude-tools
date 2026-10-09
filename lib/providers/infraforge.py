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
SALESFORGE_WORKSPACE = "INFRA_SALESFORGE_WORKSPACE"   # warm-up by API goes through a Salesforge export (2026-10-08)
WARMFORGE_WORKSPACE = "INFRA_WARMFORGE_WORKSPACE"
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
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            raise ProviderError(f"{method} {path}: HTTP {e.code}" + (f" — {detail}" if detail else "")) from None
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
            listed = d.get("name") or d.get("domain") or (f'{d.get("sld")}.{d.get("tld")}' if d.get("sld") else "")
            if str(listed).lower() == name:                # Infraforge lists sld + tld (confirmed 2026-10-08)
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

    def buy_domain(self, name, key, prewarmed=False):
        # Confirmed on the first live call (2026-10-08): POST /domains wants {"domains": [..], "workspaceId",
        # "contactDetails": {firstName, lastName, email, address1, city, province, postalCode, country,
        # organization, phone}} — the registrant, from the venture file's [registrant] (the business, never a
        # home address). The workspace id is INFRA_PROVIDER_WORKSPACE, else the account's only workspace.
        body = {"domains": [name], "workspaceId": self._workspace_id(), "contactDetails": self._contact()}
        if prewarmed:
            body["prewarmed"] = True                # CONFIRM: how pre-warmed inventory is chosen (none on offer 2026-10-08)
        got = self._req("POST", "/domains", body=body, key=key)
        item = got if isinstance(got, dict) and got.get("id") else (self._items(got) or [{}])[0]
        if not (isinstance(got, dict) and got.get("dry_run")):
            try:                                     # the vendor registers with auto-renew off (2026-10-08); on, so a lapse never retires a lane
                self.set_autorenew(name, True, f"{key}:autorenew")
            except ProviderError:
                pass                                 # verify/commit record the asset either way; `infra status` shows renewal by RDAP
        price = item.get("price") if isinstance(item, dict) else None
        if price is None:
            try:
                price = self.available(name).get("price_usd")
            except ProviderError:
                price = None
        return {"id": (item or {}).get("id"), "cost_usd": float(price or self.prices()["domain_usd_year"]),
                "human_steps": []}

    def _workspace_id(self):
        if self.get(WORKSPACE):
            return self.get(WORKSPACE)
        got = self._req("GET", "/workspaces")
        if isinstance(got, dict) and got.get("dry_run"):
            return "{workspace}"
        ws = self._items(got)
        if len(ws) == 1 and ws[0].get("id"):
            return ws[0]["id"]
        raise ProviderError(f"{len(ws)} workspaces at Infraforge; set {WORKSPACE} to the one the lane uses")

    def _contact(self):
        import venture as _venture
        r = _venture.venture().registrant
        return {"firstName": r.first_name, "lastName": r.last_name, "organization": r.organization,
                "email": r.email, "address1": r.address1, "city": r.city, "province": r.province,
                "postalCode": r.postal_code, "country": r.country, "phone": r.phone}

    def set_auth_dns(self, name, key):               # CONFIRM: the vendor sets SPF/DKIM/DMARC itself on purchase;
        did = self._domain_id(name)                  # we read its records back and let verify judge them
        got = self._req("GET", f"/domains/{did}/dns")
        recs = [{"type": r.get("type"), "name": r.get("name") or r.get("host"), "value": r.get("value")}
                for r in self._items(got)]
        sel = next((str(r["name"]).split("._domainkey")[0] for r in recs if "_domainkey" in str(r["name"] or "")), None)
        return {"records": recs, "dkim_selector": sel}

    def dns(self, name):                             # GET /domains/{id}/dns (confirmed 2026-10-08): the live set
        did = self._domain_id(name)
        got = self._req("GET", f"/domains/{did}/dns")
        if isinstance(got, dict) and got.get("dry_run"):
            return []
        return [{"type": r.get("type"), "name": r.get("name") or r.get("host"), "value": r.get("value")}
                for r in self._items(got)]

    def set_dns(self, name, records, key):           # PUT /domains/{id}/dns REPLACES the whole set
        # Confirmed the hard way 2026-10-08/09: the first TXT write sent one record and the vendor kept one
        # record — MX, SPF, DKIM and DMARC gone, the warm-up bouncing for a day (Cowork read it on 10-09).
        # So every write here carries the full set, and `infra dns-restore` puts a wiped set back.
        did = self._domain_id(name)
        body = {"records": [{"type": r["type"], "name": r["name"], "value": r["value"]} for r in records]}
        self._req("PUT", f"/domains/{did}/dns", body=body, key=key)
        return {"records": body["records"]}

    def add_txt(self, name, host, value, key):
        # Confirmed 2026-10-08 (the Postmaster TXT): {"records": [{"name", "type", "value"}]}, the name a full
        # hostname as the read returns them (the apex is the domain itself, not "@"). Read, add, write the lot.
        fqdn = name if host in (None, "", "@") else f"{host}.{name}"
        current = self.dns(name)
        if any(r.get("type") == "TXT" and r.get("name") == fqdn and r.get("value") == value for r in current):
            return {"unchanged": True}
        self.set_dns(name, current + [{"type": "TXT", "name": fqdn, "value": value}], key)
        return {}

    def remove_dns(self, name, key):
        raise HumanStep(f"remove-dns:{name}", "dns-record", f"Remove the mail records of {name} at Infraforge",
                        [f"Open Infraforge's dashboard → Domains → {name} → DNS.",
                         "Delete the MX, SPF, DKIM and DMARC records and save."],
                        "judgment", 3, then="Nothing else waits on it: the mailboxes are already gone. "
                        "(automatable: once the DNS-delete endpoint is confirmed on signup)", blocking=False)

    def create_mailbox(self, domain, local, password, key):   # CONFIRM: POST /mailboxes; password accepted?
        # Confirmed on the first live call (2026-10-08): POST /mailboxes wants
        # {"domains": [{"domain": D, "mailboxes": [{"email", "firstName", "lastName", ...}]}]}; the names are the
        # registrant's. Whether "password" is honoured is settled by VERIFY's login (a wrong one fails there).
        import venture as _venture
        r = _venture.venture().registrant
        box = {"email": f"{local}@{domain}", "firstName": r.first_name, "lastName": r.last_name, "password": password}
        body = {"domains": [{"domain": domain, "mailboxes": [box]}]}
        got = self._req("POST", "/mailboxes", body=body, key=key)
        if isinstance(got, dict) and got.get("dry_run"):
            m = {}
        else:
            items = self._items(got) or ([got] if isinstance(got, dict) else [])
            m = next((x for x in items if str(x.get("email") or "").lower() == f"{local}@{domain}"), items[0] if items else {})
        # The record carries no hosts and no id in the create answer (2026-10-08): the id comes from a re-list by
        # address, and SMTP/IMAP are the workspace's `mailserver` on 465/993 (both answered on the first unit).
        mid = m.get("id")
        if not mid and not (isinstance(got, dict) and got.get("dry_run")):
            mid = next((x.get("id") for x in self._items(self._req("GET", "/mailboxes"))
                        if str(x.get("email") or "").lower() == f"{local}@{domain}"), None)
        if mid and not (isinstance(got, dict) and got.get("dry_run")):
            # the create body's "password" is ignored (2026-10-08: the login was refused, 535, until this PATCH)
            self._req("PATCH", f"/mailboxes/{mid}", body={"password": password}, key=f"{key}:password")
        host = m.get("smtp_host") or self._mailserver()
        return {"id": mid, "address": f"{local}@{domain}", "user": f"{local}@{domain}",
                "smtp": host and f"{m.get('smtp_host') or host}:{m.get('smtp_port') or 465}",
                "imap": host and f"{m.get('imap_host') or host}:{m.get('imap_port') or 993}",
                "cost_usd_month": self.prices()["mailbox_usd_month"]}

    def _mailserver(self):
        """The workspace's mail host (GET /workspaces → `mailserver`), the SMTP and IMAP host of every mailbox in
        it; None in a dry run or when the account doesn't say."""
        got = self._req("GET", "/workspaces")
        if isinstance(got, dict) and got.get("dry_run"):
            return None
        for w in self._items(got):
            if w.get("mailserver") and (not self.get(WORKSPACE) or w.get("id") == self.get(WORKSPACE)):
                return w["mailserver"]
        return None

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
        # Infraforge doesn't warm (Taylor, 2026-10-08: "infraforge doesn't warm. I have to use warmforge for that").
        # Warm-up is Warmforge's, and the one API path to it is Infraforge's export to a Salesforge workspace
        # with `warmupActivated` (POST /mailboxes/export-to-salesforge: fromWorkspaceId, toWorkspaceId = the
        # Salesforge workspace, toWarmforgeWorkspaceId, tagName, warmupActivated, includedIds). With both ids in
        # env it is an API call; without them it is Taylor's click in Warmforge (connect the mailbox, warm-up on).
        sf, wf = self.get(SALESFORGE_WORKSPACE), self.get(WARMFORGE_WORKSPACE)
        if sf and wf:
            mid = next((x.get("id") for x in self._items(self._req("GET", "/mailboxes"))
                        if str(x.get("email") or "").lower() == address.lower()), None)
            if not mid:
                raise ProviderError(f"{address} isn't in the Infraforge account, so it can't be exported to warm-up")
            body = {"fromWorkspaceId": self._workspace_id(), "toWorkspaceId": sf, "toWarmforgeWorkspaceId": wf,
                    "tagName": self.get("INFRA_EXPORT_TAG") or "factory", "warmupActivated": True, "includedIds": [mid]}
            self._req("POST", "/mailboxes/export-to-salesforge", body=body, key=key)
            return {"warmup": "warmforge", "via": "salesforge-export"}
        raise HumanStep(f"warmup:{address}", "warmup-enrol", f"Connect {address} in Warmforge and switch warm-up on",
                        ["Open Warmforge (app.warmforge.ai) → Mailboxes → Add → pick the Infraforge mailbox "
                         f"{address} (the Forge products see each other's workspaces).",
                         "Switch warm-up on (the default schedule) and save."],
                        "judgment", 2, then="Certification counts fourteen days of warming from the day it is on. "
                        f"(automatable: with a Salesforge subscription, {SALESFORGE_WORKSPACE} and "
                        f"{WARMFORGE_WORKSPACE} in env make this an API call — TODO § 1 \"Warm-up: Warmforge\")",
                        blocking=False)

    def set_autorenew(self, name, on, key):          # CONFIRM: PUT /domains/{id}/enable-autorenew|disable-autorenew
        did = self._domain_id(name)
        self._req("PUT", f"/domains/{did}/{'enable' if on else 'disable'}-autorenew", key=key)
        return {}
