"""Consent as a state machine (ROADMAP B139; plan 55 § 5.9; VISION § Decided
"Autonomous acquisition" #6). The runbook is docs/consent.md.

Why this exists. A text to a mobile number is the highest-liability thing the
machine could do (TCPA per-text damages, Utah 13-25a's quiet hours, Sundays and
holidays, the carriers' fines). The one clean path to texting a prospect is a
mailed card that invites them to text a keyword first. What that keyword buys,
and what it does not, is decided here, in code, so a model can never talk past
it: the model is told "you may send this reply" or "you may not text this
number", never the state.

States, per number and program:

  INVITED           a card mailed (card id, version, the CTA's exact text and
                    hash, keyword, the number it tells people to text). Nothing
                    may be sent: we don't know who will text.
  KEYWORD_RECEIVED  the keyword from a number. One direct reply may go: the
                    compliance message (program, frequency, "Msg & data rates
                    may apply", STOP/HELP, the terms link) plus the thing the
                    card promised.
  DISCLOSED         that message sent and logged; its YES ask is the
                    confirmation. A reply to a text of theirs may go; nothing
                    unprompted.
  CONFIRMED         an affirmative reply, logged verbatim. The program's scope:
                    up to N messages on its subject within its time box, inside
                    8am-9pm local, never Sundays or the holiday list.
  ACTIVE            the first scoped message sent; each further one checks the
                    allowance, the hours and revocation before it leaves.
  EXPIRED           allowance spent or time box passed: replies only.
  REVOKED           STOP, or any reasonable means, on any program: every
                    program for the number ends at once (FCC 26-67), and
                    nothing may be sent to it again until the number texts
                    START.

HELP returns the help text and changes nothing. START (after a STOP) and a
web form's consent enter the same machine through opt_in() with their own
program's scope.

Portable (plan 55 § 5.12): no business is named here. The program's name, the
business name the messages carry, the terms link, the contact, the subject,
the allowance, the time box, the timezone and the holiday list are all data,
registered per (venture, program) with register_program(). The fixed carrier
phrases are the only fixed words.

The store is SQLite at $CONSENT_DB (default
~/.local/state/claude-tools/consent.db). `consents` is the transition log: one
row per event, with from_state/to_state (equal when the event changes no
state: a help text, a refusal, a reply sent). The current state is the last
row's to_state; counters are counted from the rows. Nothing is ever updated
or deleted.

Every function takes `now` (an aware datetime, default the real time) so the
tests can stand at 9:30pm on a Sunday.
"""

import contextlib
import hashlib
import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

INVITED = "INVITED"
KEYWORD_RECEIVED = "KEYWORD_RECEIVED"
DISCLOSED = "DISCLOSED"
CONFIRMED = "CONFIRMED"
ACTIVE = "ACTIVE"
EXPIRED = "EXPIRED"
REVOKED = "REVOKED"
STATES = (INVITED, KEYWORD_RECEIVED, DISCLOSED, CONFIRMED, ACTIVE, EXPIRED, REVOKED)

# The two lines a model may ever see (Rule 8: the reason in a plain voice, not the
# state to reason about).
MAY_REPLY = "You may send this reply."
MAY_NOT = "You may not text this number."

DEFAULT_TZ = "America/Denver"
QUIET_START = 8          # first hour a scoped text may go, local
QUIET_END = 21           # scoped texts stop at 9:00pm local
REPLY_WINDOW_HOURS = 24  # an unanswered text of theirs can be answered this long after

# STOP and its family (CTIA, Twilio's defaults) as a whole message, plus the
# "any reasonable means" phrases (FCC revocation rule, April 2025). Leaning
# toward revoking is deliberate: a lost lead costs less than a text to someone
# who asked us to stop.
STOP_WORDS = {"stop", "stopall", "stop all", "unsubscribe", "cancel", "end", "quit", "revoke",
              "opt out", "optout", "opt-out", "remove", "remove me"}
STOP_PHRASES = re.compile(
    r"\b(stop (texting|messaging|contacting|sending)|unsubscribe|opt(-| )?out|remove me|take me off|"
    r"(do not|don't|dont) (text|message|contact|send)|no more (texts|messages)|leave me alone|"
    r"wrong number|not interested)\b", re.I)
HELP_WORDS = {"help", "info"}
START_WORDS = {"start", "unstop", "resume"}
YES_WORDS = {"yes", "y", "yeah", "yep", "yup", "sure", "ok", "okay", "yes please", "please do",
             "sounds good", "si", "sí"}

CARRIER_RATES = re.compile(r"(msg|message)s? (&|and) data rates may apply", re.I)
FREQUENCY = re.compile(r"\b\d+\s*(msgs?|messages|texts)\b|frequency", re.I)


class ConsentError(ValueError):
    """A call the machine refuses (a card without the carriers' lines, an unknown
    program). The message is the reason, written to be read by a person."""


@dataclass
class Verdict:
    ok: bool
    reason: str = ""
    kind: str = ""            # reply | scoped | (empty when ungoverned)
    governed: bool = True     # False: the machine doesn't know this number; nothing changes
    venture: str = ""
    program: str = ""

    @property
    def line(self):
        return MAY_REPLY if self.ok else MAY_NOT


@dataclass
class Decision:
    """What inbound() decided. `handled`: the machine answered (or chose silence);
    don't hand this text to anyone else. `reply`: text the relay may send now (the
    send still passes may_send, which allows exactly this one). `line`: the one
    sentence a model may be given when the text is passed on."""
    known: bool = False
    handled: bool = False
    reply: str = ""
    line: str = ""
    event: str = ""
    extra: dict = field(default_factory=dict)


def db_path():
    return Path(os.environ.get("CONSENT_DB") or Path.home() / ".local/state/claude-tools/consent.db")


def normalize(number):
    """5555550123, (555) 555-0123, +15555550123 -> +15555550123."""
    digits = re.sub(r"\D", "", str(number or ""))
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return "+" + digits if digits else ""


def cta_hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _words(text):
    return re.sub(r"[^\w\s'-]", "", (text or "").strip().lower()).strip()


def is_stop(text):
    w = _words(text)
    return w in STOP_WORDS or (w.split()[:1] == ["stop"]) or bool(STOP_PHRASES.search(text or ""))


def is_help(text):
    return _words(text) in HELP_WORDS


def is_start(text):
    return _words(text) in START_WORDS


def is_yes(text):
    w = _words(text)
    return w in YES_WORDS or w.split()[:1] == ["yes"]


# ---- holidays ---------------------------------------------------------------

def _nth_weekday(year, month, weekday, n):
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year, month, weekday):
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def utah_holidays(year):
    """Utah's legal holidays (Utah Code 63G-1-301), the days 13-25a-103(3) keeps
    solicitations off. A fixed date on a weekend is also blocked on its observed
    weekday (Friday or Monday): both days, the conservative reading. A day the
    Governor or President appoints can't be computed; add it to the program's
    holiday list by hand."""
    fixed = [date(year, 1, 1), date(year, 6, 19), date(year, 7, 4), date(year, 7, 24),
             date(year, 11, 11), date(year, 12, 25)]
    days = set(fixed)
    for d in fixed:
        if d.weekday() == 5:
            days.add(d - timedelta(days=1))
        elif d.weekday() == 6:
            days.add(d + timedelta(days=1))
    days |= {
        _nth_weekday(year, 1, 0, 3),     # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),     # Washington and Lincoln Day
        _last_weekday(year, 5, 0),       # Memorial Day
        _nth_weekday(year, 9, 0, 1),     # Labor Day
        _nth_weekday(year, 10, 0, 2),    # Columbus Day
        _nth_weekday(year, 11, 3, 4),    # Thanksgiving
    }
    return days


HOLIDAY_CALENDARS = {"utah": utah_holidays}


def holidays_for(spec, year):
    """`spec` is the program's holiday list: a calendar name from HOLIDAY_CALENDARS,
    a list of ISO dates, or a list mixing both."""
    if not spec:
        return set()
    items = [spec] if isinstance(spec, str) else list(spec)
    out = set()
    for item in items:
        if item in HOLIDAY_CALENDARS:
            out |= HOLIDAY_CALENDARS[item](year)
        else:
            out.add(date.fromisoformat(item))
    return out


# ---- the store --------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS programs (
  venture TEXT NOT NULL, program TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'keyword',
  name TEXT NOT NULL, business TEXT NOT NULL, subject TEXT NOT NULL,
  max_messages INTEGER NOT NULL, time_box_days INTEGER NOT NULL,
  terms_url TEXT NOT NULL, contact TEXT NOT NULL DEFAULT '',
  tz TEXT NOT NULL, holidays TEXT NOT NULL DEFAULT '[]', created TEXT NOT NULL,
  PRIMARY KEY (venture, program));
CREATE TABLE IF NOT EXISTS consents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,                  -- when this row was written (UTC ISO)
  number TEXT NOT NULL DEFAULT '',   -- the texter's number; '' on an INVITED card row
  venture TEXT NOT NULL, program TEXT NOT NULL,   -- '*' / '*' on a number-wide revoke/restart
  from_state TEXT NOT NULL DEFAULT '', to_state TEXT NOT NULL DEFAULT '',
  event TEXT NOT NULL,               -- card_mailed keyword inbound reply_sent confirmed scoped_sent
                                     -- expired revoked restarted opted_in help refused
  card_id TEXT NOT NULL DEFAULT '', card_version TEXT NOT NULL DEFAULT '',
  cta_text TEXT NOT NULL DEFAULT '', cta_hash TEXT NOT NULL DEFAULT '',
  keyword TEXT NOT NULL DEFAULT '', our_number TEXT NOT NULL DEFAULT '',
  recipient TEXT NOT NULL DEFAULT '', promise TEXT NOT NULL DEFAULT '',
  inbound_at TEXT NOT NULL DEFAULT '', inbound_text TEXT NOT NULL DEFAULT '',
  message_id TEXT NOT NULL DEFAULT '', outbound_text TEXT NOT NULL DEFAULT '',
  permits TEXT NOT NULL DEFAULT '',  -- what this row lets us do afterwards, in words
  reason TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS consents_number ON consents(number);
CREATE INDEX IF NOT EXISTS consents_keyword ON consents(event, keyword);
"""

COLS = ("at", "number", "venture", "program", "from_state", "to_state", "event", "card_id",
        "card_version", "cta_text", "cta_hash", "keyword", "our_number", "recipient", "promise",
        "inbound_at", "inbound_text", "message_id", "outbound_text", "permits", "reason", "source")

PERMITS = {
    INVITED: "nothing: we don't know who will text",
    KEYWORD_RECEIVED: "one direct reply: the compliance message and what the card promised",
    DISCLOSED: "a reply to a text of theirs; nothing unprompted",
    CONFIRMED: "the program's scope: up to {n} texts about {subject} within {days} days, 8am-9pm local, "
               "never Sundays or holidays",
    ACTIVE: "the rest of the program's scope ({left} of {n} left)",
    EXPIRED: "a reply to a text of theirs; nothing unprompted",
    REVOKED: "nothing, on any program, until the number texts START",
}


def _utc(now):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ConsentError("now must be timezone-aware")
    return now.astimezone(timezone.utc)


def _iso(now):
    return _utc(now).isoformat(timespec="seconds")


class Machine:
    def __init__(self, path=None):
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)

    @contextlib.contextmanager
    def _db(self):
        """One connection per call, committed on the way out (rolled back on an
        error) and closed: the relay calls this from several worker threads."""
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    # ---- writes -------------------------------------------------------------

    def _write(self, db, **row):
        row.setdefault("at", _iso(row.pop("now", None)))
        vals = [row.get(c, "") or "" for c in COLS]
        db.execute(f"INSERT INTO consents ({','.join(COLS)}) VALUES ({','.join('?' * len(COLS))})", vals)

    def register_program(self, venture, program, *, name, business, subject, max_messages,
                         time_box_days, terms_url, contact="", kind="keyword", tz=None, holidays=None,
                         now=None):
        """Define (or redefine) a program's scope. Every word a compliance message
        carries comes from here, so a second venture is a second row, not code."""
        for label, value in (("name", name), ("business", business), ("subject", subject),
                             ("terms_url", terms_url)):
            if not str(value or "").strip():
                raise ConsentError(f"a program needs its {label}")
        if int(max_messages) < 1 or int(time_box_days) < 1:
            raise ConsentError("a program needs at least one message and one day")
        tz = tz or os.environ.get("CONSENT_TZ") or DEFAULT_TZ
        ZoneInfo(tz)  # raises on a bad name
        hol = holidays if holidays is not None else []
        holidays_for(hol, 2000)  # raises on a bad entry
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO programs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (venture, program, kind, name, business, subject, int(max_messages),
                        int(time_box_days), terms_url, contact, tz, json.dumps(hol), _iso(now)))

    def program(self, venture, program):
        with self._db() as db:
            row = db.execute("SELECT * FROM programs WHERE venture=? AND program=?",
                             (venture, program)).fetchone()
        if not row:
            raise ConsentError(f"no program {venture}/{program}; register it first")
        p = dict(row)
        p["holidays"] = json.loads(p["holidays"])
        return p

    def programs(self):
        with self._db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM programs ORDER BY venture, program")]

    def invite(self, venture, program, *, card_id, version, cta_text, keyword, our_number,
               recipient="", promise="", number="", now=None):
        """INVITED: a card was mailed. The card's call to action must carry the
        carriers' lines (VISION #6): the program's name, the keyword, a frequency,
        "Msg & data rates may apply", STOP and HELP, and the terms link; a card
        without them can't start the machine, because the keyword text it
        produces wouldn't be a recognised opt-in. B54 (`leads mail`) calls this."""
        p = self.program(venture, program)
        keyword = (keyword or "").strip()
        if not keyword or " " in keyword:
            raise ConsentError("the keyword is one word")
        missing = []
        low = (cta_text or "").lower()
        if p["name"].lower() not in low:
            missing.append(f"the program's name ({p['name']})")
        if keyword.lower() not in low:
            missing.append(f"the keyword ({keyword})")
        if not FREQUENCY.search(cta_text or ""):
            missing.append("a message frequency (\"up to 3 msgs\")")
        if not CARRIER_RATES.search(cta_text or ""):
            missing.append("\"Msg & data rates may apply\"")
        if "stop" not in low or "help" not in low:
            missing.append("STOP and HELP")
        if p["terms_url"].lower() not in low:
            missing.append(f"the terms link ({p['terms_url']})")
        if missing:
            raise ConsentError("this card's call to action is missing " + ", ".join(missing)
                               + "; a keyword text from it would not be a recognised opt-in")
        with self._db() as db:
            dup = db.execute("SELECT 1 FROM consents WHERE event='card_mailed' AND card_id=?",
                             (card_id,)).fetchone()
            if dup:
                raise ConsentError(f"card {card_id} is already recorded")
            self._write(db, now=now, number=normalize(number) if number else "", venture=venture,
                        program=program, from_state="", to_state=INVITED, event="card_mailed",
                        card_id=card_id, card_version=str(version), cta_text=cta_text,
                        cta_hash=cta_hash(cta_text), keyword=keyword.upper(),
                        our_number=normalize(our_number), recipient=recipient, promise=promise,
                        permits=PERMITS[INVITED])
        return {"card_id": card_id, "cta_hash": cta_hash(cta_text), "keyword": keyword.upper()}

    def opt_in(self, number, venture, program, *, source, evidence, now=None):
        """START or a web form's consent: straight to CONFIRMED in that program's
        scope, with the words they agreed to kept verbatim as the evidence."""
        p = self.program(venture, program)
        number = normalize(number)
        with self._db() as db:
            if self._revoked(db, number) and source != "start":
                raise ConsentError("this number texted STOP; only its own START re-enters")
            if source == "start":
                self._write(db, now=now, number=number, venture="*", program="*", event="restarted",
                            inbound_at=_iso(now), inbound_text=evidence, source="start",
                            permits="programs may be opted into again")
            self._write(db, now=now, number=number, venture=venture, program=program,
                        from_state=self._state(db, number, venture, program) or "", to_state=CONFIRMED,
                        event="opted_in", inbound_at=_iso(now), inbound_text=evidence, source=source,
                        permits=self._permits(p, CONFIRMED))

    # ---- reads --------------------------------------------------------------

    def _rows(self, db, number, venture=None, program=None):
        q, args = "SELECT * FROM consents WHERE number=?", [number]
        if venture:
            q, args = q + " AND venture=? AND program=?", args + [venture, program]
        return [dict(r) for r in db.execute(q + " ORDER BY id", args)]

    def _state(self, db, number, venture, program):
        row = db.execute("SELECT to_state FROM consents WHERE number=? AND venture=? AND program=? "
                         "AND to_state != '' ORDER BY id DESC LIMIT 1", (number, venture, program)).fetchone()
        return row["to_state"] if row else None

    def _revoked(self, db, number):
        row = db.execute("SELECT event, at FROM consents WHERE number=? AND venture='*' "
                         "AND event IN ('revoked','restarted') ORDER BY id DESC LIMIT 1", (number,)).fetchone()
        return row["at"] if row and row["event"] == "revoked" else None

    def _programs_of(self, db, number):
        return [(r["venture"], r["program"]) for r in db.execute(
            "SELECT venture, program, MAX(id) AS last FROM consents WHERE number=? AND venture != '*' "
            "GROUP BY venture, program ORDER BY last DESC", (number,))]

    def _owed(self, db, number, now):
        """The latest text of theirs that hasn't been answered, if it's recent."""
        last_in = db.execute("SELECT * FROM consents WHERE number=? AND inbound_text != '' "
                             "AND event IN ('keyword','inbound','confirmed','help') ORDER BY id DESC LIMIT 1",
                             (number,)).fetchone()
        if not last_in:
            return None
        answered = db.execute("SELECT 1 FROM consents WHERE number=? AND event='reply_sent' AND id > ?",
                              (number, last_in["id"])).fetchone()
        if answered:
            return None
        if _utc(now) - datetime.fromisoformat(last_in["at"]) > timedelta(hours=REPLY_WINDOW_HOURS):
            return None
        return dict(last_in)

    def _scope(self, db, number, venture, program):
        """(confirmed_at, scoped messages sent since) for the latest confirmation."""
        conf = db.execute("SELECT id, at FROM consents WHERE number=? AND venture=? AND program=? "
                          "AND to_state=? AND event IN ('confirmed','opted_in') ORDER BY id DESC LIMIT 1",
                          (number, venture, program, CONFIRMED)).fetchone()
        if not conf:
            return None, 0
        sent = db.execute("SELECT COUNT(*) FROM consents WHERE number=? AND venture=? AND program=? "
                          "AND event='scoped_sent' AND id > ?", (number, venture, program, conf["id"])).fetchone()[0]
        return datetime.fromisoformat(conf["at"]), sent

    def _permits(self, p, state, left=None):
        return PERMITS[state].format(n=p["max_messages"], subject=p["subject"], days=p["time_box_days"],
                                     left=left if left is not None else p["max_messages"])

    def knows(self, number):
        number = normalize(number)
        if not number:
            return False
        with self._db() as db:
            return bool(db.execute("SELECT 1 FROM consents WHERE number=? LIMIT 1", (number,)).fetchone())

    def state(self, number, venture=None, program=None):
        """For people and doctor, never for a model: {(venture, program): state}
        plus '*': REVOKED when the number is revoked."""
        number = normalize(number)
        with self._db() as db:
            out = {f"{v}/{p}": self._state(db, number, v, p) for v, p in self._programs_of(db, number)
                   if not venture or (v, p) == (venture, program)}
            if self._revoked(db, number):
                out["*"] = REVOKED
        return out

    def history(self, number):
        with self._db() as db:
            return self._rows(db, normalize(number))

    def cards(self):
        with self._db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM consents WHERE event='card_mailed' ORDER BY id")]

    # ---- the messages -------------------------------------------------------

    def compliance_message(self, p, promise=""):
        return " ".join(filter(None, [
            f"{p['business']}: {p['name']}.",
            promise.strip(),
            f"Reply YES for up to {p['max_messages']} more texts about {p['subject']} "
            f"in the next {p['time_box_days']} days.",
            "Msg & data rates may apply. Reply STOP to end, HELP for help.",
            f"Terms: {p['terms_url']}",
        ]))

    def confirmed_message(self, p):
        return (f"Thanks. {p['business']}: up to {p['max_messages']} texts about {p['subject']} "
                f"over the next {p['time_box_days']} days. Msg & data rates may apply. "
                f"Reply STOP to end, HELP for help.")

    def help_message(self, p):
        return " ".join(filter(None, [
            f"{p['business']}: {p['name']}.",
            p["contact"].strip() and f"Questions: {p['contact'].strip()}.",
            f"Up to {p['max_messages']} msgs about {p['subject']}. Msg & data rates may apply.",
            f"Reply STOP to end. Terms: {p['terms_url']}",
        ]))

    # ---- inbound ------------------------------------------------------------

    def _match_card(self, db, text, to):
        words = _words(text).split()
        if not words:
            return None
        rows = db.execute("SELECT * FROM consents WHERE event='card_mailed' AND keyword=? ORDER BY id DESC",
                          (words[0].upper(),)).fetchall()
        to = normalize(to)
        for r in rows:
            if not r["our_number"] or not to or r["our_number"] == to:
                return dict(r)
        return None

    def inbound(self, number, text, *, to="", now=None, message_id=""):
        """A text arrived from `number` (to our number `to`). Decide, record, and
        say what may be sent back. A number the machine doesn't know, with no
        card's keyword in its text, gets Decision(known=False): carry on as before."""
        number = normalize(number)
        text = text or ""
        at = _iso(now)
        if not number:
            return Decision()
        with self._db() as db:
            known = bool(db.execute("SELECT 1 FROM consents WHERE number=? LIMIT 1", (number,)).fetchone())
            card = self._match_card(db, text, to)
            if not known and not card:
                return Decision()
            db.commit()
            db.execute("BEGIN IMMEDIATE")     # the decision and its row, as one step
            base = dict(now=now, number=number, inbound_at=at, inbound_text=text, message_id=message_id)
            progs = self._programs_of(db, number)

            if self._revoked(db, number):
                if is_start(text):
                    self._write(db, venture="*", program="*", event="restarted", source="start",
                                permits="programs may be opted into again; nothing is re-entered by itself", **base)
                    return Decision(known=True, handled=True, event="restarted")
                self._write(db, venture="*", program="*", event="refused", from_state=REVOKED, to_state="",
                            reason="a text from a revoked number: nothing may be sent", **base)
                return Decision(known=True, handled=True, line=MAY_NOT, event="ignored_revoked")

            if is_stop(text):
                for v, p in progs:
                    st = self._state(db, number, v, p)
                    if st != REVOKED:
                        self._write(db, venture=v, program=p, from_state=st or "", to_state=REVOKED,
                                    event="revoked", permits=PERMITS[REVOKED], **base)
                self._write(db, venture="*", program="*", event="revoked", to_state=REVOKED,
                            permits=PERMITS[REVOKED], **base)
                return Decision(known=True, handled=True, line=MAY_NOT, event="revoked")

            if is_help(text) and progs:
                v, p = progs[0]
                prog = self.program(v, p)
                st = self._state(db, number, v, p)
                self._write(db, venture=v, program=p, from_state=st, to_state=st, event="help",
                            permits="the help text; nothing changes", **base)
                return Decision(known=True, handled=True, reply=self.help_message(prog), line=MAY_REPLY,
                                event="help")

            if card:
                v, p = card["venture"], card["program"]
                st = self._state(db, number, v, p)
                if st in (None, INVITED, EXPIRED, REVOKED):
                    # A first keyword, or a fresh one after the program ran out (or after
                    # their own START lifted a STOP): they are asking again.
                    prog = self.program(v, p)
                    self._write(db, venture=v, program=p, from_state=st or INVITED, to_state=KEYWORD_RECEIVED,
                                event="keyword", card_id=card["card_id"], card_version=card["card_version"],
                                cta_text=card["cta_text"], cta_hash=card["cta_hash"], keyword=card["keyword"],
                                our_number=card["our_number"], recipient=card["recipient"],
                                promise=card["promise"], permits=PERMITS[KEYWORD_RECEIVED], **base)
                    return Decision(known=True, handled=True, line=MAY_REPLY, event="keyword",
                                    reply=self.compliance_message(prog, card["promise"]),
                                    extra={"card_id": card["card_id"], "venture": v, "program": p})
                if st == KEYWORD_RECEIVED:
                    # They sent the keyword again before our one reply went: it's still owed.
                    prog = self.program(v, p)
                    self._write(db, venture=v, program=p, from_state=st, to_state=st, event="inbound",
                                permits=PERMITS[st], **base)
                    return Decision(known=True, handled=True, line=MAY_REPLY, event="keyword_again",
                                    reply=self.compliance_message(prog, card["promise"]))

            disclosed = next(((v, p) for v, p in progs if self._state(db, number, v, p) == DISCLOSED), None)
            if disclosed and is_yes(text):
                v, p = disclosed
                prog = self.program(v, p)
                self._write(db, venture=v, program=p, from_state=DISCLOSED, to_state=CONFIRMED,
                            event="confirmed", permits=self._permits(prog, CONFIRMED), **base)
                return Decision(known=True, handled=True, line=MAY_REPLY, event="confirmed",
                                reply=self.confirmed_message(prog))

            if progs:
                v, p = progs[0]
            elif card:
                v, p = card["venture"], card["program"]
            else:
                v, p = "*", "*"
            st = self._state(db, number, v, p)
            self._write(db, venture=v, program=p, from_state=st or "", to_state=st or "", event="inbound",
                        permits="one reply to this text", **base)
            return Decision(known=True, handled=False, line=MAY_REPLY, event="inbound")

    # ---- outbound -----------------------------------------------------------

    def _expire(self, db, number, v, p, st, reason, now):
        self._write(db, now=now, number=number, venture=v, program=p, from_state=st, to_state=EXPIRED,
                    event="expired", reason=reason, permits=PERMITS[EXPIRED])

    def may_send(self, number, *, kind=None, venture=None, program=None, now=None):
        """Before a text leaves for `number`: yes or no, with the reason. `kind`
        is "reply" (answering a text of theirs) or "scoped" (unprompted, inside a
        CONFIRMED program); None decides from the record: a reply when a text of
        theirs is waiting, scoped otherwise. A number the machine doesn't know is
        not governed (ok, governed=False). Expiry found here is recorded."""
        number = normalize(number)
        if not number:
            return Verdict(ok=True, governed=False)
        with self._db() as db:
            if not db.execute("SELECT 1 FROM consents WHERE number=? LIMIT 1", (number,)).fetchone():
                return Verdict(ok=True, governed=False)
            db.commit()
            db.execute("BEGIN IMMEDIATE")
            revoked = self._revoked(db, number)
            if revoked:
                return Verdict(ok=False, kind=kind or "", reason=f"this number asked us to stop on "
                               f"{revoked[:10]}; nothing may be sent to it on any program")
            owed = self._owed(db, number, now)
            if kind is None:
                kind = "reply" if owed else "scoped"
            if kind == "reply":
                if owed:
                    return Verdict(ok=True, kind="reply", venture=owed["venture"], program=owed["program"])
                return Verdict(ok=False, kind="reply", reason="there's no text of theirs waiting for an "
                               "answer (each text of theirs gets one reply)")
            progs = self._programs_of(db, number)
            if venture:
                progs = [(venture, program)]
            states = {(v, p): self._state(db, number, v, p) for v, p in progs}
            live = [(v, p) for v, p in progs if states[(v, p)] in (CONFIRMED, ACTIVE)]
            if not live:
                st = next(iter(states.values()), None)
                why = {KEYWORD_RECEIVED: "they texted the keyword but haven't said YES yet",
                       DISCLOSED: "they haven't said YES yet",
                       EXPIRED: "the program they agreed to is over",
                       REVOKED: "they asked us to stop"}.get(st, "they haven't agreed to texts from us")
                return Verdict(ok=False, kind="scoped", reason=f"{why}: only a reply to a text of theirs may go")
            v, p = live[0]
            prog = self.program(v, p)
            confirmed_at, sent = self._scope(db, number, v, p)
            if confirmed_at and _utc(now) > confirmed_at + timedelta(days=prog["time_box_days"]):
                self._expire(db, number, v, p, states[(v, p)], "time box passed", now)
                db.commit()
                return Verdict(ok=False, kind="scoped", venture=v, program=p,
                               reason=f"the program's {prog['time_box_days']} days are over")
            if sent >= prog["max_messages"]:
                self._expire(db, number, v, p, states[(v, p)], "allowance spent", now)
                db.commit()
                return Verdict(ok=False, kind="scoped", venture=v, program=p,
                               reason=f"the allowance is spent ({sent} of {prog['max_messages']} sent)")
            local = _utc(now).astimezone(ZoneInfo(prog["tz"]))
            if local.weekday() == 6:
                return Verdict(ok=False, kind="scoped", venture=v, program=p,
                               reason="it's Sunday where they are; scoped texts never go on Sundays")
            if local.date() in holidays_for(prog["holidays"], local.year):
                return Verdict(ok=False, kind="scoped", venture=v, program=p,
                               reason=f"{local.date()} is a holiday where they are; no scoped texts today")
            if not QUIET_START <= local.hour < QUIET_END:
                return Verdict(ok=False, kind="scoped", venture=v, program=p,
                               reason=f"it's {local.strftime('%-I:%M%p').lower()} where they are "
                                      f"({prog['tz']}); scoped texts go 8am-9pm")
            return Verdict(ok=True, kind="scoped", venture=v, program=p)

    def refused(self, number, verdict, text="", now=None):
        """Log a refusal (the text that didn't go, and why)."""
        number = normalize(number)
        with self._db() as db:
            v, p = verdict.venture or "*", verdict.program or "*"
            st = self._state(db, number, v, p) or ""
            self._write(db, now=now, number=number, venture=v, program=p, from_state=st, to_state=st,
                        event="refused", outbound_text=text, reason=verdict.reason)

    def record_sent(self, number, verdict, text, *, now=None, message_id=""):
        """A text that may_send allowed has gone. The transitions it makes:
        the reply to a keyword, if it carried the carriers' lines, is the
        disclosure (KEYWORD_RECEIVED -> DISCLOSED); the first scoped text moves
        CONFIRMED -> ACTIVE; the last one the allowance holds -> EXPIRED."""
        if not verdict.governed:
            return
        number = normalize(number)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            v, p = verdict.venture, verdict.program
            st = self._state(db, number, v, p) or ""
            if verdict.kind == "reply":
                to = st
                if st == KEYWORD_RECEIVED and CARRIER_RATES.search(text or "") and "STOP" in (text or ""):
                    to = DISCLOSED
                self._write(db, now=now, number=number, venture=v, program=p, from_state=st, to_state=to,
                            event="reply_sent", outbound_text=text, message_id=message_id,
                            permits=PERMITS[DISCLOSED] if to == DISCLOSED else "")
                return
            prog = self.program(v, p)
            _, sent = self._scope(db, number, v, p)
            left = prog["max_messages"] - sent - 1
            self._write(db, now=now, number=number, venture=v, program=p, from_state=st, to_state=ACTIVE,
                        event="scoped_sent", outbound_text=text, message_id=message_id,
                        permits=self._permits(prog, ACTIVE, left))
            if left <= 0:
                self._expire(db, number, v, p, ACTIVE, "allowance spent", now)


# ---- module-level conveniences (the default store) -----------------------------

_default = None


def machine():
    global _default
    if _default is None or _default.path != db_path():
        _default = Machine()
    return _default
