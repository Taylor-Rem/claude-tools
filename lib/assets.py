"""The capacity registry (ROADMAP B141; plan 55 § 5.3; VISION § Decided "Autonomous acquisition" #2).

What the outbound lanes send through, and whether they may, as rows instead of env strings and
memory. Four levels, each row pointing at its parent:

    mailbox  ->  domain  ->  tenant  ->  provider (the contract)

    import assets
    reg = assets.Registry()                  # $ASSETS_DB, else ~/.local/state/claude-tools/assets.db
    assets.seed(reg, tenant, provider_key, domains, mailboxes, initial_state="active")   # idempotent
    snap = assets.snapshot(reg, tenant)      # the tree, with each mailbox's verdict and parents
    cap = assets.capacity(snap, usage, default_cap)
    plan = assets.plan_tick(snap, usage, followups, fresh, default_cap)   # who sends what this tick
    assets.breaches(snap, usage, default_cap)                             # the evening check's list

Every row carries `tenant` (the venture's registry tenant, `V.tenant` in lib/venture.py), so a second
venture shares the store and never sees the first one's rows. Nothing here names a business: what
the venture is comes from the caller (bin/outreach today, bin/infra from B144).

**Contract verdicts** (the provider row, VISION #2): PERMITTED (the provider's terms allow cold
mail), ACCEPTED_RISK (Taylor wrote the risk into VISION by name; only he does), PROHIBITED (never
sends cold mail, first touch or follow-up). A provider nobody has read the terms of has no verdict
("unreviewed") and is treated as PROHIBITED until someone does: a guess about a contract is how a
whole tenant gets suspended. The verdicts of the providers we have read are in CONTRACTS below,
each with its clause and the day it was read.

**States** (every row): provisioning -> warming -> active; active <-> paused; any live state ->
draining -> retired. `retired` is refused while the asset (or anything under it) has open threads,
because a reply to a retired mailbox would land nowhere.

**The rules, in code (not learned):**

1. A first letter goes only through a mailbox that is `active`, under a domain, tenant and provider
   that are `active`, and whose contract is PERMITTED.
2. A follow-up goes from the mailbox that sent the first letter (it is the same thread), if that
   mailbox is `active` or `draining` and its contract is PERMITTED or ACCEPTED_RISK. A `paused`
   mailbox's follow-ups wait in their due order and go first when it is resumed; they never move to
   another mailbox, since a stranger's thread would then have two senders.
3. Follow-ups before first letters, one letter per mailbox per tick, round-robin across the
   mailboxes, everything under the mailbox's cap, the domain's cap and the contract's cap (a NULL
   cap on a domain or contract means only its mailboxes' caps bound it).
4. **No contract carries more than half of the day's first-touch capacity** (the sum of the caps of
   every mailbox rule 1 admits, across all contracts): a suspension of one provider must never take
   more than half the lane with it. With a single PERMITTED contract the lane therefore runs at half
   its mailboxes' first-letter caps; that is the decision, not a bug.
5. Pause on the mailbox's rule: the lane's own pause (an angry reply, bin/outreach's paused file)
   is mirrored here as `paused`, and lifted the same way.
6. Drain on reputation: a domain whose latest reading is bad (a Postmaster spam rate at or over the
   stop line, a Postmaster reputation LOW or BAD, a placement probe under PROBE_MIN_INBOX_PCT in the
   inbox) goes `draining` with its mailboxes: no first letters, the open threads finish. Coming back
   is a person's or the Factory's `set_state`, never automatic.

**Reputation** is a dated reading: `record_reading(asset, source, metric, value, date)` with source
`postmaster` (B136's daily read lands here) or `probe` (the provider's or our seed-inbox placement
probe). Metrics: `spam_rate` (percent), `reputation` (HIGH|MEDIUM|LOW|BAD), `inbox_pct` (percent).

**Renewal** of a domain comes from RDAP (rdap.org by default, $ASSETS_RDAP_BASE to point elsewhere):
one GET with a timeout, kept on the row for RDAP_MAX_AGE_DAYS, never required (offline it says
"unknown"). $ASSETS_RDAP=0 turns the lookup off.

For B144 (the Factory, `bin/infra`): `ensure()` a row (idempotent), `set_state()` it through its
lifecycle with a reason, `set_fields()` its caps, cost, renewal and `human_steps_open`, and read
`capacity()` for `infra plan`'s "whether" (demand decides when; the registry decides whether).
"""

import contextlib
import datetime as dt
import json
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

KINDS = ("mailbox", "domain", "tenant", "provider")
PARENT_KIND = {"mailbox": "domain", "domain": "tenant", "tenant": "provider", "provider": None}
STATES = ("provisioning", "warming", "active", "paused", "draining", "retired")
VERDICTS = ("PERMITTED", "ACCEPTED_RISK", "PROHIBITED")
LIVE = ("provisioning", "warming", "active", "paused", "draining")

# Which state may follow which. Anything live may drain or retire (retire is refused with open threads).
TRANSITIONS = {
    "provisioning": {"warming", "active", "draining", "retired"},
    "warming": {"active", "paused", "draining", "retired"},
    "active": {"paused", "draining", "retired"},
    "paused": {"active", "warming", "draining", "retired"},
    "draining": {"active", "retired"},
    "retired": set(),
}

CONTRACT_SHARE = 0.5          # VISION #2: no contract above half of first-touch capacity
PROBE_MIN_INBOX_PCT = 50.0    # a placement probe landing in the inbox less often than this drains the domain
BAD_REPUTATION = ("LOW", "BAD")
RDAP_MAX_AGE_DAYS = 7
RDAP_TIMEOUT = 8

# The providers whose terms someone has read, by the key the registry uses. The clause is quoted as
# read; `read` is the day. A provider missing here is "unreviewed" and sends nothing cold.
CONTRACTS = {
    "google-workspace": {
        "title": "Google Workspace",
        "contract": "PROHIBITED",
        "clause": 'Acceptable Use Policy (rev. 2025-10-13): do not use the services for "unsolicited mass '
                  'email, promotions, advertisements, or other solicitations"; no volume threshold',
        "clause_date": "2026-10-07",
        "suspension_scope": "the whole Workspace account: every mailbox and every domain in the tenant, "
                            "the owner's own mail included",
        "decided": "VISION § Decided 2026-10-07 #2: Workspace sends no cold mail, at any volume, for any reason",
    },
    "fake": {
        "title": "the test provider",
        "contract": "PERMITTED",
        "clause": "tests only: nothing leaves the machine",
        "clause_date": "2026-10-08",
        "suspension_scope": "none",
        "decided": "",
    },
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
  id INTEGER PRIMARY KEY,
  tenant TEXT NOT NULL,
  kind TEXT NOT NULL,
  name TEXT NOT NULL,
  parent_id INTEGER,
  state TEXT NOT NULL,
  prior_state TEXT,
  state_why TEXT,
  state_ts TEXT,
  cap_day INTEGER,              -- NULL: the caller's default (a mailbox) or no own cap (domain, contract)
  contract TEXT,                -- provider rows: PERMITTED | ACCEPTED_RISK | PROHIBITED | NULL (unreviewed)
  clause TEXT,
  clause_date TEXT,
  suspension_scope TEXT,
  cost_usd_month REAL,
  renews TEXT,                  -- YYYY-MM-DD
  renews_source TEXT,           -- rdap | hand
  renews_checked TEXT,
  human_steps_open TEXT NOT NULL DEFAULT '[]',   -- JSON list of TAYLOR-TODO entry titles it waits on
  note TEXT,
  created TEXT NOT NULL,
  updated TEXT NOT NULL,
  UNIQUE (tenant, kind, name)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  tenant TEXT NOT NULL,
  asset_id INTEGER NOT NULL,
  kind TEXT NOT NULL,           -- state | incident | note
  from_state TEXT,
  to_state TEXT,
  text TEXT
);
CREATE TABLE IF NOT EXISTS readings (
  id INTEGER PRIMARY KEY,
  asset_id INTEGER NOT NULL,
  date TEXT NOT NULL,
  source TEXT NOT NULL,         -- postmaster | probe
  metric TEXT NOT NULL,         -- spam_rate | reputation | inbox_pct
  value TEXT NOT NULL,
  ts TEXT NOT NULL,
  UNIQUE (asset_id, date, source, metric)
);
"""

FIELDS = ("cap_day", "contract", "clause", "clause_date", "suspension_scope", "cost_usd_month", "renews",
          "renews_source", "renews_checked", "human_steps_open", "note")


class AssetError(Exception):
    """A refused change, in a sentence the caller prints as it stands."""


def db_path():
    return Path(os.environ.get("ASSETS_DB") or Path.home() / ".local/state/claude-tools/assets.db")


def _now(now=None):
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).isoformat(timespec="seconds")


class Registry:
    def __init__(self, path=None):
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)

    @contextlib.contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    # ---- reads --------------------------------------------------------------

    def rows(self, tenant):
        with self._db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM assets WHERE tenant=? ORDER BY id", (tenant,))]

    def get(self, asset_id):
        with self._db() as db:
            r = db.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        return dict(r) if r else None

    def find(self, tenant, ref):
        """A row by `name` or `kind:name` within one tenant (or by numeric id). AssetError when none or several."""
        ref = str(ref).strip()
        rows = self.rows(tenant)
        if ref.isdigit():
            hit = [r for r in rows if r["id"] == int(ref)]
        elif ":" in ref and ref.split(":", 1)[0] in KINDS:
            kind, name = ref.split(":", 1)
            hit = [r for r in rows if r["kind"] == kind and r["name"] == name.lower()]
        else:
            hit = [r for r in rows if r["name"] == ref.lower()]
        if not hit:
            raise AssetError(f"no asset {ref!r} in tenant {tenant!r} (`outreach assets` lists them)")
        if len(hit) > 1:
            raise AssetError(f"{ref!r} names {len(hit)} assets; say which: "
                             + ", ".join(f"{r['kind']}:{r['name']}" for r in hit))
        return hit[0]

    def events(self, asset_id=None, tenant=None, kind=None, limit=50):
        q, args = "SELECT * FROM events WHERE 1=1", []
        for col, v in (("asset_id", asset_id), ("tenant", tenant), ("kind", kind)):
            if v is not None:
                q += f" AND {col}=?"
                args.append(v)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self._db() as db:
            return [dict(r) for r in db.execute(q, args)]

    def readings(self, asset_id):
        with self._db() as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM readings WHERE asset_id=? ORDER BY date, id", (asset_id,))]

    # ---- writes -------------------------------------------------------------

    def ensure(self, tenant, kind, name, parent_id=None, state="active", now=None, **fields):
        """The row's id, creating it when missing. An existing row is left as it is (seeding twice changes
        nothing); `fields` only fill a new row. Use set_fields() / set_state() to change one."""
        if kind not in KINDS:
            raise AssetError(f"kind is one of {', '.join(KINDS)}, not {kind!r}")
        if state not in STATES:
            raise AssetError(f"state is one of {', '.join(STATES)}, not {state!r}")
        name = str(name).strip().lower()
        bad = set(fields) - set(FIELDS)
        if bad:
            raise AssetError(f"unknown field(s): {', '.join(sorted(bad))}")
        if "human_steps_open" in fields and not isinstance(fields["human_steps_open"], str):
            fields["human_steps_open"] = json.dumps(list(fields["human_steps_open"]))
        ts = _now(now)
        with self._db() as db:
            r = db.execute("SELECT id FROM assets WHERE tenant=? AND kind=? AND name=?", (tenant, kind, name)).fetchone()
            if r:
                return r["id"]
            cols = ["tenant", "kind", "name", "parent_id", "state", "state_ts", "created", "updated", *fields]
            vals = [tenant, kind, name, parent_id, state, ts, ts, ts, *fields.values()]
            cur = db.execute(f"INSERT INTO assets ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)
            db.execute("INSERT INTO events (ts, tenant, asset_id, kind, from_state, to_state, text) "
                       "VALUES (?,?,?,?,?,?,?)", (ts, tenant, cur.lastrowid, "state", None, state, "entered"))
            return cur.lastrowid

    def set_fields(self, asset_id, now=None, **fields):
        bad = set(fields) - set(FIELDS)
        if bad:
            raise AssetError(f"unknown field(s): {', '.join(sorted(bad))}")
        if "contract" in fields and fields["contract"] not in (*VERDICTS, None):
            raise AssetError(f"a contract verdict is one of {', '.join(VERDICTS)}, not {fields['contract']!r}")
        if "human_steps_open" in fields and not isinstance(fields["human_steps_open"], str):
            fields["human_steps_open"] = json.dumps(list(fields["human_steps_open"]))
        if not fields:
            return
        sets = ", ".join(f"{k}=?" for k in fields)
        with self._db() as db:
            db.execute(f"UPDATE assets SET {sets}, updated=? WHERE id=?", (*fields.values(), _now(now), asset_id))

    def set_state(self, asset_id, state, why, open_threads=0, now=None, cascade=False):
        """Move a row (and with cascade, every live row under it) to `state`, with a reason. Refuses a
        transition the lifecycle doesn't have, and `retired` while open_threads > 0."""
        if state not in STATES:
            raise AssetError(f"state is one of {', '.join(STATES)}, not {state!r}")
        row = self.get(asset_id)
        if row is None:
            raise AssetError(f"no asset with id {asset_id}")
        if state == "retired" and open_threads:
            raise AssetError(f"{row['kind']} {row['name']} has {open_threads} open thread(s); drain it and retire it "
                             "when they have finished (a reply to a retired mailbox lands nowhere)")
        targets = [row] + (self.descendants(row) if cascade else [])
        ts = _now(now)
        changed = []
        with self._db() as db:
            for r in targets:
                cur = r["state"]
                if cur == state:
                    continue
                if state not in TRANSITIONS[cur]:
                    if r is row:
                        raise AssetError(f"{r['kind']} {r['name']} is {cur}; it can go to "
                                         f"{', '.join(sorted(TRANSITIONS[cur])) or 'nothing (retired is final)'}, "
                                         f"not {state}")
                    continue          # a child that can't follow (retired, say) stays where it is
                db.execute("UPDATE assets SET state=?, prior_state=?, state_why=?, state_ts=?, updated=? WHERE id=?",
                           (state, cur, why, ts, ts, r["id"]))
                db.execute("INSERT INTO events (ts, tenant, asset_id, kind, from_state, to_state, text) "
                           "VALUES (?,?,?,?,?,?,?)", (ts, r["tenant"], r["id"], "state", cur, state, why))
                changed.append((r["kind"], r["name"], cur, state))
        return changed

    def descendants(self, row):
        rows = self.rows(row["tenant"])
        out, frontier = [], [row["id"]]
        while frontier:
            kids = [r for r in rows if r["parent_id"] in frontier]
            out += kids
            frontier = [r["id"] for r in kids]
        return out

    def incident(self, asset_id, text, now=None):
        row = self.get(asset_id)
        if row is None:
            raise AssetError(f"no asset with id {asset_id}")
        with self._db() as db:
            db.execute("INSERT INTO events (ts, tenant, asset_id, kind, from_state, to_state, text) "
                       "VALUES (?,?,?,?,?,?,?)", (_now(now), row["tenant"], asset_id, "incident", None, None, text))

    def record_reading(self, asset_id, source, metric, value, date, now=None):
        """One dated reputation reading; the same (asset, date, source, metric) again replaces it."""
        if source not in ("postmaster", "probe"):
            raise AssetError(f"a reading's source is postmaster or probe, not {source!r}")
        with self._db() as db:
            db.execute("INSERT INTO readings (asset_id, date, source, metric, value, ts) VALUES (?,?,?,?,?,?) "
                       "ON CONFLICT(asset_id, date, source, metric) DO UPDATE SET value=excluded.value, ts=excluded.ts",
                       (asset_id, str(date)[:10], source, metric, str(value), _now(now)))


# ---- seeding ---------------------------------------------------------------------

def domain_of(address):
    return address.rsplit("@", 1)[-1].lower() if "@" in address else ""


def seed(reg, tenant, provider_key, domains, mailboxes, initial_state="active", now=None):
    """Enter a lane that already exists (idempotent): the provider with its contract from CONTRACTS, the
    tenant under it, each sending domain (the venture's, plus any a mailbox is on) and each mailbox.
    Rows already there are left alone, so a hand-set state or cap survives every later run."""
    c = CONTRACTS.get(provider_key) or {}
    pid = reg.ensure(tenant, "provider", provider_key, state="active", now=now,
                     contract=c.get("contract"), clause=c.get("clause"), clause_date=c.get("clause_date"),
                     suspension_scope=c.get("suspension_scope"),
                     note=c.get("decided") or ("" if c else "unreviewed: nobody has read this provider's terms; "
                                                            "it sends nothing cold until a verdict is entered"))
    tid = reg.ensure(tenant, "tenant", tenant, parent_id=pid, state="active", now=now)
    names = list(dict.fromkeys([d.lower() for d in domains] + [domain_of(m) for m in mailboxes if domain_of(m)]))
    dids = {d: reg.ensure(tenant, "domain", d, parent_id=tid, state="active", now=now) for d in names}
    for m in mailboxes:
        d = domain_of(m)
        if d:
            reg.ensure(tenant, "mailbox", m, parent_id=dids[d], state=initial_state, now=now)


def sync_pauses(reg, tenant, paused, now=None):
    """Rule 5: mirror the lane's own pause file ({mailbox: {why, ts}}) onto the mailbox rows. A mailbox the
    lane paused goes `paused`; one whose pause the lane lifted (`outreach resume MAILBOX`) goes back to the
    state it had. -> [(name, from, to)]."""
    out = []
    paused = {k.lower(): v for k, v in (paused or {}).items()}
    for r in reg.rows(tenant):
        if r["kind"] != "mailbox":
            continue
        if r["name"] in paused and r["state"] in ("active", "warming"):
            why = "the lane's pause rule: " + str((paused[r["name"]] or {}).get("why") or "paused")
            reg.set_state(r["id"], "paused", why, now=now)
            out.append((r["name"], r["state"], "paused"))
        elif (r["name"] not in paused and r["state"] == "paused"
              and str(r["state_why"] or "").startswith("the lane's pause rule")):
            back = r["prior_state"] if r["prior_state"] in ("active", "warming") else "active"
            reg.set_state(r["id"], back, "the lane lifted its pause (outreach resume)", now=now)
            out.append((r["name"], "paused", back))
    return out


def sync_warmup(reg, tenant, mailboxes, warmed, why, now=None):
    """B150: the lane's own entry (OUTREACH_MAILBOXES) is seeded `warming` while its warm-up is young; once the
    lane's warm-up start is fourteen days old (`warmed`), those seeded rows go `active`, as the cap's ramp
    always said. Only rows seed() made and nobody moved since (no state_why): a Factory row or a hand-set
    state is never touched. -> [(name, from, to)]."""
    out = []
    if not warmed:
        return out
    want = {m.lower() for m in mailboxes}
    for r in reg.rows(tenant):
        if r["kind"] == "mailbox" and r["name"] in want and r["state"] == "warming" and not r["state_why"]:
            reg.set_state(r["id"], "active", why, now=now)
            out.append((r["name"], "warming", "active"))
    return out


def entered(reg, asset_id, state):
    """The day (YYYY-MM-DD) a row first entered `state`, from its events; None when it never has."""
    with reg._db() as db:
        r = db.execute("SELECT ts FROM events WHERE asset_id=? AND kind='state' AND to_state=? ORDER BY id LIMIT 1",
                       (asset_id, state)).fetchone()
    return str(r["ts"])[:10] if r else None


def week_moves(reg, tenant, since, names=None):
    """B150: what moved in and out of the lane since `since` (YYYY-MM-DD), mailboxes only, optionally only
    those in `names`: {"joined": [name], "left": [name]}. Joined is warming|provisioning|paused -> active
    (a certification, or a resume); left is -> draining|retired. A row that did both is in both."""
    out = {"joined": [], "left": []}
    kinds = {r["id"]: r for r in reg.rows(tenant) if r["kind"] == "mailbox"}
    with reg._db() as db:
        evs = [dict(e) for e in db.execute("SELECT * FROM events WHERE tenant=? AND kind='state' AND ts>=? ORDER BY id",
                                           (tenant, str(since)))]
    for e in evs:
        r = kinds.get(e["asset_id"])
        if r is None or (names is not None and r["name"] not in names):
            continue
        if e["to_state"] == "active" and e["from_state"] in ("warming", "provisioning"):
            if r["name"] not in out["joined"]:
                out["joined"].append(r["name"])
        elif e["to_state"] in ("draining", "retired") and e["from_state"] not in ("draining", "retired"):
            if r["name"] not in out["left"]:
                out["left"].append(r["name"])
    return out


# ---- the tree --------------------------------------------------------------------

def snapshot(reg, tenant):
    """{"tenant", "rows": [...], "by_id": {...}, "mailboxes": [...]} with each row's parents attached
    (row["domain"], row["tenant_row"], row["provider"]) and its latest readings (row["reading"])."""
    rows = reg.rows(tenant)
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        try:
            r["human_steps_open"] = json.loads(r["human_steps_open"] or "[]")
        except json.JSONDecodeError:
            r["human_steps_open"] = [r["human_steps_open"]]
        r["reading"] = latest_readings(reg.readings(r["id"]))
    for r in rows:
        chain, p = {}, by_id.get(r["parent_id"])
        while p is not None:
            chain[p["kind"]] = p
            p = by_id.get(p["parent_id"])
        r["parents"] = chain
        r["provider"] = r if r["kind"] == "provider" else chain.get("provider")
    return {"tenant": tenant, "rows": rows, "by_id": by_id,
            "mailboxes": sorted((r for r in rows if r["kind"] == "mailbox"), key=lambda r: r["name"])}


def latest_readings(readings):
    """{metric: {"value", "date", "source"}} — the newest reading of each metric."""
    out = {}
    for x in readings:
        out[x["metric"]] = {"value": x["value"], "date": x["date"], "source": x["source"]}
    return out


def verdict(row):
    p = row.get("provider") or {}
    return p.get("contract") or "unreviewed"


def chain_states(row):
    """[(kind, name, state)] from the row up to the provider."""
    out = [(row["kind"], row["name"], row["state"])]
    for k in ("domain", "tenant", "provider"):
        p = row["parents"].get(k)
        if p:
            out.append((k, p["name"], p["state"]))
    return out


def first_touch_ok(mb):
    """Rule 1. -> (ok, why-not)."""
    v = verdict(mb)
    if v != "PERMITTED":
        return False, f"contract {v}" + (" (first letters go through PERMITTED contracts only)" if v != "PROHIBITED"
                                         else " for cold mail")
    for kind, name, state in chain_states(mb):
        if state != "active":
            return False, f"{kind} {name} is {state}"
    return True, ""


def follow_up_ok(mb):
    """Rule 2. -> (ok, why-not)."""
    v = verdict(mb)
    if v not in ("PERMITTED", "ACCEPTED_RISK"):
        return False, f"contract {v}: it sends no cold mail, follow-ups included"
    if mb["state"] not in ("active", "draining"):
        how = (" (its follow-ups wait and go first when it is resumed)" if mb["state"] == "paused" else "")
        return False, f"mailbox {mb['name']} is {mb['state']}{how}"
    for kind, name, state in chain_states(mb)[1:]:
        if state not in ("active", "draining"):
            return False, f"{kind} {name} is {state}"
    return True, ""


def mailbox_cap(mb, default_cap):
    """A mailbox's cap today: its own `cap_day` when set, else the caller's default. The default is a number
    (every mailbox the same), or (B150) a callable taking the mailbox row, or a {name: cap} dict, so the lane
    can count each Factory mailbox's ramp from its own warm-up start while the Workspace entry keeps
    OUTREACH_WARMUP_START's."""
    if mb.get("cap_day") is not None:
        return int(mb["cap_day"])
    if callable(default_cap):
        return int(default_cap(mb) or 0)
    if isinstance(default_cap, dict):
        return int(default_cap.get(mb["name"], 0) or 0)
    return int(default_cap or 0)


def capacity(snap, usage, default_cap):
    """Today's caps and counts at every level, and the first-touch budget per contract.

    usage: {mailbox: {"today": n, "first_today": n, ...}} — what the lane sent today (the caller counts it
    from its own records). Returns {"mailboxes": {name: {...}}, "domains": {...}, "providers": {...},
    "first_capacity": total, "contract_limit": {provider: max first letters today}}."""
    out = {"mailboxes": {}, "domains": {}, "providers": {}}
    first_cap = 0
    for mb in snap["mailboxes"]:
        u = usage.get(mb["name"], {})
        cap = mailbox_cap(mb, default_cap)
        ok1, why1 = first_touch_ok(mb)
        okf, whyf = follow_up_ok(mb)
        out["mailboxes"][mb["name"]] = {"cap": cap, "today": int(u.get("today", 0)),
                                        "first_today": int(u.get("first_today", 0)),
                                        "first_ok": ok1, "first_why": why1, "follow_ok": okf, "follow_why": whyf}
        if ok1:
            first_cap += cap
        for level, key in (("domains", "domain"), ("providers", "provider")):
            parent = mb["parents"].get(key)
            if parent is None:
                continue
            agg = out[level].setdefault(parent["name"], {"cap": parent.get("cap_day"), "mailbox_caps": 0, "today": 0,
                                                         "first_today": 0, "first_capacity": 0})
            agg["mailbox_caps"] += cap
            agg["today"] += int(u.get("today", 0))
            agg["first_today"] += int(u.get("first_today", 0))
            if ok1:
                agg["first_capacity"] += cap
    out["first_capacity"] = first_cap
    out["contract_limit"] = {p: CONTRACT_SHARE * first_cap for p in out["providers"]}
    return out


def _room(level_cap, level_today):
    return level_cap is None or level_today < int(level_cap)


def plan_tick(snap, usage, followups, fresh, default_cap, offset=0):
    """Rules 1–4 for one tick: at most one letter a mailbox, follow-ups first.

    followups: [{"id", "mailbox", "due"}] due now (each must go from its own mailbox).
    fresh:     [{"id"}] first letters waiting, in the order they should go.
    offset:    the round-robin's turn (the tick passes a counter; mailboxes are taken from that position).
    -> {"send": [{"mailbox", "id", "kind": "follow"|"first"}],
        "held": [{"id", "mailbox", "why"}],          # follow-ups that wait (their mailbox can't send)
        "waiting": [{"id", "why"}],                  # first letters no mailbox may take this tick
        "refused": [{"mailbox", "why"}]}             # mailboxes refused a first letter, and why"""
    cap = capacity(snap, usage, default_cap)
    boxes = [m["name"] for m in snap["mailboxes"]]
    if boxes:
        k = offset % len(boxes)
        boxes = boxes[k:] + boxes[:k]
    mbs = {m["name"]: m for m in snap["mailboxes"]}
    today = {b: cap["mailboxes"][b]["today"] for b in boxes}
    dom_today = {d: v["today"] for d, v in cap["domains"].items()}
    prov_today = {p: v["today"] for p, v in cap["providers"].items()}
    prov_first = {p: v["first_today"] for p, v in cap["providers"].items()}
    used = set()
    plan = {"send": [], "held": [], "waiting": [], "refused": []}

    def under_caps(b):
        mb = mbs[b]
        if today[b] >= cap["mailboxes"][b]["cap"]:
            return False, f"mailbox {b} is at its cap ({cap['mailboxes'][b]['cap']} today)"
        d, p = mb["parents"].get("domain"), mb["parents"].get("provider")
        if d and not _room(d.get("cap_day"), dom_today.get(d["name"], 0)):
            return False, f"domain {d['name']} is at its cap ({d['cap_day']} today)"
        if p and not _room(p.get("cap_day"), prov_today.get(p["name"], 0)):
            return False, f"contract {p['name']} is at its cap ({p['cap_day']} today)"
        return True, ""

    def count(b, first):
        today[b] += 1
        mb = mbs[b]
        d, p = mb["parents"].get("domain"), mb["parents"].get("provider")
        if d:
            dom_today[d["name"]] = dom_today.get(d["name"], 0) + 1
        if p:
            prov_today[p["name"]] = prov_today.get(p["name"], 0) + 1
            if first:
                prov_first[p["name"]] = prov_first.get(p["name"], 0) + 1

    for f in sorted(followups, key=lambda x: (str(x.get("due") or ""), str(x.get("id")))):
        b = str(f.get("mailbox") or "").lower()
        if b not in mbs:
            plan["held"].append({"id": f["id"], "mailbox": b, "why": f"mailbox {b or '?'} isn't in the registry"})
            continue
        if b in used:
            plan["held"].append({"id": f["id"], "mailbox": b, "why": "one letter a mailbox a tick; next tick"})
            continue
        ok, why = cap["mailboxes"][b]["follow_ok"], cap["mailboxes"][b]["follow_why"]
        if ok:
            ok, why = under_caps(b)
        if not ok:
            plan["held"].append({"id": f["id"], "mailbox": b, "why": why})
            continue
        plan["send"].append({"mailbox": b, "id": f["id"], "kind": "follow"})
        used.add(b)
        count(b, first=False)

    queue = list(fresh)
    for b in boxes:
        if not queue:
            break
        if b in used:
            continue
        c = cap["mailboxes"][b]
        if not c["first_ok"]:
            plan["refused"].append({"mailbox": b, "why": c["first_why"]})
            continue
        ok, why = under_caps(b)
        if not ok:
            plan["refused"].append({"mailbox": b, "why": why})
            continue
        p = mbs[b]["parents"]["provider"]["name"]
        limit = cap["contract_limit"].get(p, 0)
        if prov_first.get(p, 0) + 1 > limit:
            plan["refused"].append({"mailbox": b, "why": (
                f"contract {p} has carried {prov_first.get(p, 0)} of today's first-touch capacity of "
                f"{cap['first_capacity']}; no contract above half ({limit:g})")})
            continue
        item = queue.pop(0)
        plan["send"].append({"mailbox": b, "id": item["id"], "kind": "first"})
        used.add(b)
        count(b, first=True)
    for item in queue:
        plan["waiting"].append({"id": item["id"], "why": "no mailbox may take a first letter this tick"})
    return plan


# ---- reputation (rule 6) ---------------------------------------------------------

def bad_reading(reading, spam_max_pct):
    """The latest readings of a domain -> the reason it should drain, or ""."""
    r = reading or {}
    sr = r.get("spam_rate")
    try:
        if sr and float(sr["value"]) >= float(spam_max_pct):
            return f"{sr['source']} spam rate {float(sr['value']):.2f}% on {sr['date']} (the line is {spam_max_pct:g}%)"
    except ValueError:
        pass
    rep = r.get("reputation")
    if rep and str(rep["value"]).upper() in BAD_REPUTATION:
        return f"{rep['source']} reputation {str(rep['value']).upper()} on {rep['date']}"
    ip = r.get("inbox_pct")
    try:
        if ip and float(ip["value"]) < PROBE_MIN_INBOX_PCT:
            return (f"{ip['source']} placement {float(ip['value']):.0f}% in the inbox on {ip['date']} "
                    f"(under {PROBE_MIN_INBOX_PCT:g}%)")
    except ValueError:
        pass
    return ""


def drain_on_reputation(reg, tenant, spam_max_pct, now=None):
    """Rule 6: every active/warming/paused domain with a bad latest reading goes `draining`, its mailboxes
    with it. -> [(kind, name, from, to, why)]."""
    out = []
    snap = snapshot(reg, tenant)
    for d in snap["rows"]:
        if d["kind"] != "domain" or d["state"] not in ("active", "warming", "paused"):
            continue
        why = bad_reading(d["reading"], spam_max_pct)
        if why:
            for kind, name, a, b in reg.set_state(d["id"], "draining", "reputation: " + why, now=now, cascade=True):
                out.append((kind, name, a, b, why))
    return out


# ---- the evening check -------------------------------------------------------------

def breaches(snap, usage, default_cap):
    """Rule breaches, each a sentence. usage[mailbox] may carry "first_today", "follow_today", "today",
    "open_threads". Empty means the registry and the lane agree."""
    out = []
    cap = capacity(snap, usage, default_cap)
    for mb in snap["mailboxes"]:
        c = cap["mailboxes"][mb["name"]]
        u = usage.get(mb["name"], {})
        v = verdict(mb)
        # B150: the lane chooses first letters by rule 1, so a cap on a mailbox whose contract forbids cold mail
        # sends nothing new; it matters while that mailbox still has threads, which finish from it (bin/outreach's
        # Workspace entry). Then the cap is mail going out under a contract that forbids it, and that's a breach.
        if (v not in ("PERMITTED", "ACCEPTED_RISK") and c["cap"] > 0 and mb["state"] != "retired"
                and int(u.get("open_threads", 0))):
            out.append(f"mailbox {mb['name']} has a cold-mail cap of {c['cap']} today under contract {v} and "
                       f"{u['open_threads']} open thread(s): their follow-ups would go through it (set its cap to 0 "
                       "to hold them, or let them finish and retire it)")
        if int(u.get("first_today", 0)) and not c["first_ok"]:
            out.append(f"mailbox {mb['name']} sent {u['first_today']} first letter(s) today though {c['first_why']}")
        if int(u.get("follow_today", 0)) and not c["follow_ok"]:
            out.append(f"mailbox {mb['name']} sent {u['follow_today']} follow-up(s) today though {c['follow_why']}")
        if c["today"] > c["cap"]:
            out.append(f"mailbox {mb['name']} sent {c['today']} today, over its cap of {c['cap']}")
    for r in snap["rows"]:
        if r["state"] == "retired" and r["kind"] == "mailbox" and int(usage.get(r["name"], {}).get("open_threads", 0)):
            out.append(f"mailbox {r['name']} is retired with {usage[r['name']]['open_threads']} open thread(s)")
    for p, v in cap["providers"].items():
        limit = cap["contract_limit"].get(p, 0)
        if v["first_today"] > limit:
            out.append(f"contract {p} carried {v['first_today']} first letters today, over half of the first-touch "
                       f"capacity of {cap['first_capacity']} ({limit:g})")
        lc = next((r.get("cap_day") for r in snap["rows"] if r["kind"] == "provider" and r["name"] == p), None)
        if lc is not None and v["today"] > int(lc):
            out.append(f"contract {p} sent {v['today']} today, over its cap of {lc}")
    for d, v in cap["domains"].items():
        dc = next((r.get("cap_day") for r in snap["rows"] if r["kind"] == "domain" and r["name"] == d), None)
        if dc is not None and v["today"] > int(dc):
            out.append(f"domain {d} sent {v['today']} today, over its cap of {dc}")
    return out


def warnings(snap, today=None, renew_days=30):
    """Things to know that break no rule: a renewal within renew_days, open human steps, no verdict."""
    today = today or dt.date.today()
    out = []
    for r in snap["rows"]:
        if r["state"] == "retired":
            continue
        if r["kind"] == "domain" and r.get("renews"):
            try:
                left = (dt.date.fromisoformat(r["renews"][:10]) - today).days
            except ValueError:
                left = None
            if left is not None and left <= renew_days:
                out.append(f"domain {r['name']} renews {r['renews'][:10]} ({left} days)")
        if r["kind"] == "provider" and not r.get("contract"):
            out.append(f"provider {r['name']} has no contract verdict: it sends nothing cold until one is entered")
        for step in r["human_steps_open"]:
            out.append(f"{r['kind']} {r['name']} waits on Taylor: {step}")
    return out


# ---- RDAP (renewal) ----------------------------------------------------------------

def rdap_expiry(domain, base=None, timeout=RDAP_TIMEOUT):
    """The registration's expiry date (YYYY-MM-DD) from RDAP, or None. One GET; any failure is None."""
    base = (base or os.environ.get("ASSETS_RDAP_BASE") or "https://rdap.org/domain/").rstrip("/") + "/"
    req = urllib.request.Request(base + domain, headers={"Accept": "application/rdap+json",
                                                         "User-Agent": "claude-tools assets (RDAP renewal check)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    for ev in data.get("events") or []:
        if str(ev.get("eventAction") or "").lower() == "expiration" and ev.get("eventDate"):
            return str(ev["eventDate"])[:10]
    return None


def refresh_renewals(reg, tenant, now=None, force=False):
    """Fill each live domain's `renews` from RDAP when the last check is older than RDAP_MAX_AGE_DAYS.
    Off with ASSETS_RDAP=0. A failed lookup records the check and keeps the last known date."""
    if os.environ.get("ASSETS_RDAP", "1").strip() in ("0", "off", "no"):
        return []
    t = now or dt.datetime.now(dt.timezone.utc)
    out = []
    for r in reg.rows(tenant):
        if r["kind"] != "domain" or r["state"] == "retired" or r.get("renews_source") == "hand":
            continue
        if not force and r.get("renews_checked"):
            try:
                age = t - dt.datetime.fromisoformat(r["renews_checked"])
                if age < dt.timedelta(days=RDAP_MAX_AGE_DAYS):
                    continue
            except ValueError:
                pass
        exp = rdap_expiry(r["name"])
        fields = {"renews_checked": _now(t)}
        if exp:
            fields.update(renews=exp, renews_source="rdap")
        reg.set_fields(r["id"], now=t, **fields)
        out.append((r["name"], exp))
    return out
