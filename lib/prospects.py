"""One prospect record (ROADMAP B140, plan 55 § 5.1 and § 5.6; VISION § Decided "Autonomous acquisition" #1, #4, #12).

Three stores said who a business is and where it stands: the census (read-only, the facts), the pipeline
(`pipeline.jsonl`, append-only, what happened) and the email lane's state (the send rows, the suppression list,
the replies). This is the table that joins them, one row a business, that `leads`, `outreach` and `prep` read
and write through this module (the relay reads it through `leads prospects`, as it reads everything else):

    import prospects
    st = prospects.Store()                       # $PROSPECTS_DB, else ~/projects/private-docs/leads/prospects.db
    rec = st.get("place:ChIJ…") or st.by_place("ChIJ…")
    st.put(rec)                                  # whole records (leads builds them from the census)
    st.note_event(e) / st.note_send(row) / st.note_suppress(row)    # the write-through hooks

**The log stays the log.** `pipeline.jsonl` and outreach's rows are never rewritten from here; the table is
derived from them plus the census, and `rebuild(records)` (what `leads prospects rebuild` runs, and what a missing
table triggers) makes it again from scratch, so nothing is migrated by hand and a lost table costs one rebuild.
The table lives under private-docs/ (in no repo: it holds names, numbers and addresses).

**The record** (`record()` gives every key its default; plan 55 § 5.1):

    venture, key, place_id, name, city, segment, category
    identity   {phone, website, address, maps_url}
    routes     [{channel: email|instagram|facebook|phone|postal|form, value, evidence, verdict, why, checked}]
               verdict: high (tied to the place; the only one the gate admits), low, unsure, rejected, bounced,
               suppressed, duplicate (another listing has the same inbox and goes first), mx (no mail server)
    facts      [{key, sentence, evidence, footing}]       every one traced to a stored source
    proposition {id, lane, label, facts: [...], experiment, arm, letters, why}   the venture's classify + deal
    strength   {level: strong|good|weak, reasons: [keys], says: [words]}
    state      {stage, suppressed (why) | None, held (why) | None, excluded (why) | None, last}
    conversation {open, channel, class, at}                a reply or a text not yet closed
    close      {experiment, arm, open, why}               B137's deal for this place, from outreach
    consent    {ok, governed, line, reason} | None        B139's verdict, from the consent machine
    touches    [{date, channel, actor, template, variant, asset, arm, experiment, proposition, touch, source}]
    assets     [{kind, ...}]                              what a lane made for it (prep's preview)
    outcomes   {delivered, reply, positive, trial, activated, paid, retained: first date | None}
    footing    {field: source}                            `places` for a Places-derived field (VISION AA#11)

Nothing here names a business (plan 55 § 5.12): the venture is a column, and the paths are env names.
"""

import contextlib
import copy
import datetime as dt
import json
import os
import sqlite3
from pathlib import Path

FUNNEL = ("delivered", "reply", "positive", "trial", "activated", "paid", "retained")
CHANNELS = ("email", "instagram", "facebook", "phone", "postal", "form")
VERDICTS = ("high", "low", "unsure", "rejected", "bounced", "suppressed", "duplicate", "mx")
# pipeline outcome -> the funnel stages it reaches (leads OUTCOMES; a reply is anything that came back)
OUTCOME_FUNNEL = {"messaged": ("delivered",), "talked": ("reply",), "visited": (),
                  "inbound": ("reply", "positive"), "interested": ("reply", "positive"),
                  "demo": ("reply", "positive"), "later": ("reply",), "trial": ("reply", "positive", "trial"),
                  "won": ("reply", "positive", "trial", "activated", "paid"), "lost": ("reply",), "churned": ()}
# outreach's reply classes that are a person answering (a bounce and an out-of-office aren't)
REPLY_CLASSES = ("interested", "yes", "question", "not now", "no", "angry", "unsure", "other")
POSITIVE_CLASSES = ("interested", "yes")
OPEN_CLASSES = ("interested", "yes", "question", "unsure", "other")
TEXT_VIA = ("text", "sms")

SCHEMA = """
CREATE TABLE IF NOT EXISTS prospects (
    venture TEXT NOT NULL, key TEXT NOT NULL, place_id TEXT, name TEXT, record TEXT NOT NULL, updated TEXT NOT NULL,
    PRIMARY KEY (venture, key));
CREATE INDEX IF NOT EXISTS prospects_place ON prospects (venture, place_id);
CREATE TABLE IF NOT EXISTS meta (venture TEXT NOT NULL, k TEXT NOT NULL, v TEXT, PRIMARY KEY (venture, k));
"""


def projects_dir():
    return Path(os.environ.get("PROJECTS_DIR") or Path.home() / "projects")


def db_path():
    return Path(os.environ.get("PROSPECTS_DB") or projects_dir() / "private-docs" / "leads" / "prospects.db")


def pipeline_path():
    return Path(os.environ.get("LEADS_PIPELINE") or projects_dir() / "private-docs" / "leads" / "pipeline.jsonl")


def outreach_state():
    return Path(os.environ.get("OUTREACH_STATE") or Path.home() / ".local/state/claude-tools/outreach")


def read_jsonl(path):
    out = []
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def now_iso():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def record(**kw):
    """A prospect record with every key present (the shape the module docstring gives)."""
    r = {"venture": None, "key": None, "place_id": None, "name": None, "city": None, "segment": None,
         "category": None, "identity": {"phone": None, "website": None, "address": None, "maps_url": None},
         "routes": [], "facts": [], "proposition": {"id": None, "lane": None, "label": None, "facts": [],
                                                    "experiment": None, "arm": None, "letters": [], "why": None},
         "strength": {"level": None, "reasons": [], "says": []},
         "state": {"stage": None, "suppressed": None, "held": None, "excluded": None, "last": None},
         "conversation": {"open": False, "channel": None, "class": None, "at": None},
         "close": {"experiment": None, "arm": None, "open": False, "why": None}, "consent": None,
         "touches": [], "assets": [], "outcomes": {k: None for k in FUNNEL}, "footing": {}}
    for k, v in kw.items():
        if isinstance(r.get(k), dict) and isinstance(v, dict):
            r[k].update(v)
        else:
            r[k] = v
    return r


# ---- folding the logs into a record (pure) -------------------------------------------------------------------

def _reach(rec, stage, date):
    if date and (rec["outcomes"].get(stage) is None or date < rec["outcomes"][stage]):
        rec["outcomes"][stage] = date


def apply_event(rec, e):
    """One pipeline event onto a record: the stage, the touch it was, the funnel, an open conversation."""
    if e.get("kind") == "strength":
        if e.get("strength"):
            rec["strength"] = {"level": e["strength"], "reasons": ["taylor"],
                               "says": [f"Taylor: \"{e['note']}\"" if e.get("note") else "Taylor's word"]}
            rec["footing"]["strength"] = "Taylor (leads strength)"
        return rec
    date = e.get("date")
    outcome = e.get("outcome")
    if e.get("kind") == "touch_due" or outcome == "seen":     # B152: a read receipt is not a touch or a stage
        return rec
    if e.get("stage"):
        rec["state"]["stage"] = e["stage"]
    rec["state"]["last"] = date
    for f in ("name", "city"):
        if e.get(f) and not rec.get(f):
            rec[f] = e[f]
    if not rec.get("place_id") and e.get("place_id"):
        rec["place_id"] = e["place_id"]
    machine = e.get("channel") == "email" and e.get("via") == "email"     # the email lane's own line (outreach)
    if outcome in ("messaged", "talked", "visited") and not machine:      # (its send row is the touch: apply_send)
        rec["touches"].append({"date": date, "channel": e.get("channel"), "actor": "taylor",
                               "template": (e.get("outbound") or {}).get("template"),
                               "variant": (e.get("outbound") or {}).get("variant"), "asset": None,
                               "arm": e.get("arm"), "experiment": e.get("experiment_id"),
                               "proposition": (e.get("outbound") or {}).get("proposition"), "touch": None,
                               "source": "pipeline"})
    for stage in OUTCOME_FUNNEL.get(outcome, ()):
        _reach(rec, stage, date)
    if outcome in ("inbound", "interested", "demo"):
        via = str(e.get("via") or e.get("channel") or e.get("source") or "").lower()
        ch = "text" if via in TEXT_VIA else ("email" if via in ("email",) or e.get("source") == "email" else via or None)
        rec["conversation"] = {"open": True, "channel": ch, "class": "interested", "at": date}
    elif outcome in ("won", "lost", "churned", "trial", "later", "held"):
        rec["conversation"] = {"open": False, "channel": None, "class": None, "at": None}
    if e.get("arm") and e.get("experiment_id"):
        rec["close"].update(experiment=e["experiment_id"], arm=e["arm"])
    return rec


def apply_send(rec, row):
    """One outreach send row: a touch with its channel, actor, template, variant, asset, arm and proposition."""
    rec["touches"].append({"date": row.get("date") or str(row.get("ts") or "")[:10], "channel": "email",
                           "actor": "machine", "template": row.get("template"), "variant": row.get("variant"),
                           "asset": row.get("mailbox"), "arm": row.get("proposition_arm") or row.get("arm"),
                           "experiment": row.get("proposition_experiment") or row.get("experiment_id"),
                           "proposition": row.get("proposition"), "touch": row.get("touch"),
                           "source": "outreach", "batch_id": row.get("batch_id")})
    _reach(rec, "delivered", row.get("date") or str(row.get("ts") or "")[:10])
    if not rec["state"].get("held"):       # a thread is open: its next letters are its sequence's, never a new first
        rec["state"]["held"] = f"written to by the email lane on {rec['touches'][-1]['date']} (its sequence's)"
    for r in rec["routes"]:
        if r.get("channel") == "email" and str(r.get("value") or "").lower() == str(row.get("email") or "").lower():
            r.setdefault("written", row.get("date"))
    return rec


def apply_reply(rec, row):
    """One outreach reply row: the funnel, and the conversation it opens or closes."""
    cls, date = row.get("class"), row.get("date") or str(row.get("ts") or "")[:10]
    if cls in REPLY_CLASSES:
        _reach(rec, "reply", date)
    if cls in POSITIVE_CLASSES:
        _reach(rec, "positive", date)
    if cls in OPEN_CLASSES and not row.get("answered_by") == "taylor":
        rec["conversation"] = {"open": True, "channel": "email", "class": cls, "at": date}
    elif cls in ("no", "angry"):
        rec["conversation"] = {"open": False, "channel": None, "class": cls, "at": date}
    if row.get("arm") and row.get("experiment_id"):
        rec["close"].update(experiment=row["experiment_id"], arm=row["arm"])
    if cls == "bounce":
        mark_route(rec, "email", row.get("email"), "bounced", "it bounced")
    return rec


def mark_route(rec, channel, value, verdict, why):
    for r in rec["routes"]:
        if r.get("channel") == channel and (value is None or str(r.get("value") or "").lower() ==
                                            str(value or "").lower()):
            r["verdict"], r["why"] = verdict, why
    return rec


def apply_suppression(rec, row):
    """A suppression row: a bounce refuses that address only; a no (or a domain, or the place) stops the business."""
    v = str(row.get("value") or "").strip().lower()
    reason = row.get("reason") or "suppressed"
    if not v:
        return rec
    emails = [str(r.get("value") or "").lower() for r in rec["routes"] if r.get("channel") == "email"]
    domains = {e.split("@", 1)[-1] for e in emails}
    site = str((rec.get("identity") or {}).get("website") or "").lower()
    hit = v == str(rec.get("place_id") or "").lower() or v in emails or v in domains or \
        (v and "." in v and "@" not in v and v in site)
    if not hit:
        return rec
    if "bounce" in reason and "@" in v:
        return mark_route(rec, "email", v, "bounced", reason)
    rec["state"]["suppressed"] = reason
    for e in emails:
        if e == v or e.split("@", 1)[-1] == v or v == str(rec.get("place_id") or "").lower():
            mark_route(rec, "email", e, "suppressed", reason)
    return rec


def fold(rec, events=(), sends=(), replies=(), suppress=()):
    """A record from the census, with the logs laid over it in order. Returns a new record."""
    rec = copy.deepcopy(rec)
    for e in events:
        apply_event(rec, e)
    for row in sends:
        apply_send(rec, row)
    for row in replies:
        apply_reply(rec, row)
    for row in suppress:
        apply_suppression(rec, row)
    return rec


def logs():
    """(events by key, sends by place, replies by place, suppression rows) from the files today's tools write."""
    by_key, by_place = {}, {}
    for e in read_jsonl(pipeline_path()):
        if e.get("key"):
            by_key.setdefault(e["key"], []).append(e)
        if e.get("place_id"):
            by_place.setdefault(e["place_id"], []).append(e)
    o = outreach_state()
    sends, replies = {}, {}
    for r in read_jsonl(o / "sends.jsonl"):
        sends.setdefault(r.get("place_id") or str(r.get("email") or "").lower(), []).append(r)
    for r in read_jsonl(o / "replies.jsonl"):
        if r.get("class") != "probe":
            replies.setdefault(r.get("place_id") or str(r.get("email") or "").lower(), []).append(r)
    return {"events": by_key, "events_by_place": by_place, "sends": sends, "replies": replies,
            "suppress": read_jsonl(o / "suppress.jsonl")}


def fold_logs(rec, L):
    """`fold` with the rows of `logs()` that belong to this record (by key, place id or address)."""
    keys = {rec.get("key")} | ({f"place:{rec['place_id']}"} if rec.get("place_id") else set())
    events = sorted({id(e): e for k in keys for e in L["events"].get(k, [])}.values(),
                    key=lambda e: (e.get("ts") or e.get("date") or ""))
    addrs = {str(r.get("value") or "").lower() for r in rec.get("routes") or [] if r.get("channel") == "email"}
    ids = {rec.get("place_id")} | addrs

    def rows(table):
        seen, out = set(), []
        for i in ids:
            for r in table.get(i, []) if i else []:
                if id(r) not in seen:
                    seen.add(id(r))
                    out.append(r)
        return sorted(out, key=lambda r: r.get("ts") or r.get("date") or "")
    return fold(rec, events, rows(L["sends"]), rows(L["replies"]), L["suppress"])


# ---- the store ---------------------------------------------------------------------------------------------

class Store:
    """The prospects table. One SQLite file; every row carries its venture, and reads stay inside one."""

    def __init__(self, path=None, venture=None):
        self.path = Path(path or db_path())
        self.venture = venture or os.environ.get("VENTURE") or _default_venture()

    @contextlib.contextmanager
    def _db(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            db.executescript(SCHEMA)
            yield db
            db.commit()
        finally:
            db.close()

    def exists(self):
        if not self.path.exists():
            return False
        with self._db() as db:
            return bool(db.execute("SELECT 1 FROM meta WHERE venture=? AND k='built'", (self.venture,)).fetchone())

    def built(self):
        with self._db() as db:
            row = db.execute("SELECT v FROM meta WHERE venture=? AND k='built'", (self.venture,)).fetchone()
        return json.loads(row["v"]) if row else None

    def put(self, rec, db=None):
        rec = dict(rec, venture=self.venture)
        args = (self.venture, rec["key"], rec.get("place_id"), rec.get("name"),
                json.dumps(rec, ensure_ascii=False, sort_keys=True), now_iso())
        sql = ("INSERT INTO prospects (venture, key, place_id, name, record, updated) VALUES (?,?,?,?,?,?) "
               "ON CONFLICT (venture, key) DO UPDATE SET place_id=excluded.place_id, name=excluded.name, "
               "record=excluded.record, updated=excluded.updated")
        if db is not None:
            db.execute(sql, args)
            return rec
        with self._db() as d:
            d.execute(sql, args)
        return rec

    def get(self, key):
        with self._db() as db:
            row = db.execute("SELECT record FROM prospects WHERE venture=? AND key=?", (self.venture, key)).fetchone()
        return json.loads(row["record"]) if row else None

    def by_place(self, place_id):
        with self._db() as db:
            row = db.execute("SELECT record FROM prospects WHERE venture=? AND place_id=? ORDER BY key LIMIT 1",
                             (self.venture, place_id)).fetchone()
        return json.loads(row["record"]) if row else None

    def all(self):
        with self._db() as db:
            rows = db.execute("SELECT record FROM prospects WHERE venture=? ORDER BY key", (self.venture,)).fetchall()
        return [json.loads(r["record"]) for r in rows]

    def count(self):
        with self._db() as db:
            return db.execute("SELECT COUNT(*) FROM prospects WHERE venture=?", (self.venture,)).fetchone()[0]

    def rebuild(self, records, sources=None):
        """Replace this venture's rows with `records` (whole, already folded) in one transaction."""
        n = 0
        with self._db() as db:
            db.execute("DELETE FROM prospects WHERE venture=?", (self.venture,))
            for rec in records:
                self.put(rec, db)
                n += 1
            db.execute("INSERT OR REPLACE INTO meta (venture, k, v) VALUES (?, 'built', ?)",
                       (self.venture, json.dumps({"at": now_iso(), "records": n, "sources": sources or {}})))
        return n

    # -- the write-through hooks: each one updates the record it touches, if the table has it ---------------
    def _update(self, place_id, key, fn):
        if not self.path.exists():
            return None          # no table yet: the next `leads prospects rebuild` folds this row in from the log
        rec = (self.get(key) if key else None) or (self.by_place(place_id) if place_id else None)
        if rec is None:
            return None
        rec = fn(rec)
        self.put(rec)
        return rec

    def note_event(self, e):
        return self._update(e.get("place_id"), e.get("key"), lambda r: apply_event(r, e))

    def note_send(self, row):
        return self._update(row.get("place_id"), None, lambda r: apply_send(r, row))

    def note_reply(self, row):
        return self._update(row.get("place_id"), None, lambda r: apply_reply(r, row))

    def note_hold(self, row):
        """A hold a lane put on a business (prep's 56 days after its preview): state.held, and the asset it got."""
        def fn(r):
            r["state"]["held"] = row.get("why") or "held"
            if row.get("asset"):
                r.setdefault("assets", []).append(row["asset"])
            return r
        return self._update(row.get("place_id"), None, fn)

    def note_suppress(self, row):
        v = str(row.get("value") or "")
        pid = v if v and "." not in v and "@" not in v else None
        if pid:
            return self._update(pid, None, lambda r: apply_suppression(r, row))
        return None              # an address or a domain: folded in at the next rebuild (one scan, no index on it)


def note(kind, row):
    """The one-line hook a CLI calls after it appends to its log: never raises, never blocks the tool (the log is
    the record of truth; a failed note is fixed by the next rebuild)."""
    try:
        st = Store()
        return getattr(st, f"note_{kind}")(row)
    except Exception:            # noqa: BLE001 - a hook must never break the command that called it
        return None


def _default_venture():
    try:
        import venture
        return venture.venture().venture_name
    except SystemExit:
        return "default"
