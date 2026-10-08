"""The acquisition policy, written down: which lane a prospect goes to next (ROADMAP B140, plan 55 § 5.2;
VISION § Decided "Autonomous acquisition" #1, #4).

    import policy
    plan = policy.route(prospect, capacity)        # pure: the same record and capacity give the same plan
    plan["lane"], plan["rule"], plan["decision"], plan["reason"]

`prospect` is one record of the prospects table (lib/prospects.py `record()` says each key). `capacity` is what
the registry says the lanes may carry today, as `capacity_view()` packs it (lib/assets.py's snapshot, the day's
usage and the default cap; `downstream`, rule 7's input, lib/downstream.py's measure; `today`, the date a follow-up's
due day is read against), or None when nobody read the registry.

**The rules.** Seven, numbered as plan 55 § 5.2 numbers them, each citing the decision it comes from. A change is a
VISION line first, then RULES below, then the playbook page (`policy.md` beside Steel's playbook in
private-docs/leads/), and tests/test_policy.py fails when the page and RULES disagree on a rule's number, lane or
decision. They are read in ORDER, and the first one that applies decides:

    1  suppressed, held, won, lost, no proposition       -> nothing
    6  a reply or a text is open                          -> the conversation (the consent machine for a text;
                                                             an interested email reply gets the close arm)
    7  downstream: the human queue over budget 3 days     -> first touches hold (B145); a follow-up in flight
                                                             goes on (the email lane, its sequence's next letter)
    2  strong, and a confirmed written channel Taylor works -> Taylor's queue; the email as touch three
    3  an email proposition, an address the gate admits,  -> the email lane, on a PERMITTED mailbox the registry
       and the facts its letter needs                        chooses (lib/assets.py plan_tick)
    4  the card proposition, or a bounced address, with   -> the card lane
       a postal address
    5  a contact form only                                -> Taylor by hand when strong, else nothing

Rules 6 and 7 are read before 2–5 because 2–5 are all first touches: a business that wrote back is in a
conversation whatever its strength, and a downstream hold stops first touches only. Nothing applying is a plan
too: lane `nothing`, with the reason each rule gave.

**Portable** (plan 55 § 5.12): the propositions are the venture's (`Venture.propositions()`); a proposition's lane
(`email`, `card` or none) is what rules 3 and 4 read, never an id by name. B137's close arm and B139's consent
verdict arrive on the record (lib/prospects.py fills them by asking outreach's deal and the consent machine), so
neither is copied here.

**What a plan is:** {lane, status, action, rule, decision, reason, asset_kind, asset, touch, sequence,
proposition, experiment, arm, handler, notes}. `lane` is one of LANES; `status` is `ready` (the lane may take it
now), `waiting` (the lane is right and has no room or isn't built: `reason` says which) or `none` (lane
`nothing`). `action` is the plan in one word, for a reader and a test: `send` (a touch may go now), `answer` (the
conversation), `hold first touches` (rule 7), `wait` or `nothing`.

**A follow-up** (B145) is the next letter of a sequence the email lane started: the record has the lane's own
touches and no reply. It is not a first touch, so rule 7 never holds it; it is rule 3's (the email lane), on the
thread's mailbox, `ready` once its day has come (`capacity["today"]`) and `waiting` before.
"""

import copy

LANES = ("nothing", "conversation", "hold", "taylor", "email", "card")
# The written channels Taylor works by hand (a DM from his phone). The email is the machine's; a phone number is
# not a written channel (the machine never texts first, #9; nobody cold calls, "Selling first" #2 and #12).
TAYLOR_CHANNELS = ("instagram", "facebook")
CLIENT_STAGES = ("won", "trialing")
CLOSED_STAGES = ("lost", "churned")
CONVERSATION_STAGES = ("interested", "negotiating")


class Rule:
    __slots__ = ("n", "name", "lane", "decision", "says")

    def __init__(self, n, name, lane, decision, says):
        self.n, self.name, self.lane, self.decision, self.says = n, name, lane, tuple(decision), says

    def __repr__(self):
        return f"Rule({self.n}, {self.name!r}, lane={self.lane!r}, decision={self.decision!r})"


# The decision ids: AA#n is VISION § Decided "Autonomous acquisition" #n; SF#n is § Decided "Selling first" #n.
RULES = (
    Rule(1, "stop", "nothing", ("SF#2", "AA#4"),
         "Suppressed, held, won, lost, or no proposition: nothing. A no is honoured before anything else, a held "
         "business waits out its hold, and a business without a reason to write isn't written to."),
    Rule(2, "taylor-first", "taylor", ("SF#2", "AA#1"),
         "Strong, with a confirmed written channel Taylor works (an Instagram or Facebook page tied to the place): "
         "Taylor's queue, by hand; the email comes as touch three."),
    Rule(3, "email", "email", ("AA#2", "AA#4"),
         "One of the venture's email propositions, an address the gate admits, and the true facts its letter "
         "needs: the email lane, on a PERMITTED mailbox the registry chooses (round-robin under cap, no contract "
         "above half the first touches)."),
    Rule(4, "card", "card", ("AA#4", "AA#6"),
         "The venture's card proposition, or an address that bounced, with a postal address: the card lane."),
    Rule(5, "form-only", "taylor", ("AA#10",),
         "A contact form is the only way in: Taylor by hand when it is strong, else nothing. The machine never "
         "fills in a form."),
    Rule(6, "conversation", "conversation", ("AA#5", "AA#6"),
         "A reply or a text is open: the conversation loop. A text goes to the consent machine, which alone says "
         "whether a reply may go; an interested email reply gets the arm the close experiment deals."),
    Rule(7, "downstream", "hold", ("AA#8",),
         "When the human queue has been over the owner's daily budget for three days, first touches hold while "
         "follow-ups, replies and the close arm continue, and the morning message names the keys taking the "
         "minutes and the row that would remove each (lib/downstream.py; it lifts when the window is back under)."),
)
BY_N = {r.n: r for r in RULES}
ORDER = (1, 6, 7, 2, 3, 4, 5)


def capacity_view(snapshot, usage, default_cap, offset=0, downstream=None, today=None):
    """The `capacity` argument: the registry as lib/assets.py reads it, plus rule 7's input (lib/downstream.py's
    measure, None when it wasn't read) and the day a follow-up's due date is read against (an ISO string)."""
    return {"snapshot": snapshot, "usage": usage or {}, "default_cap": default_cap, "offset": offset,
            "downstream": downstream, "today": str(today) if today else None}


def _plan(rule, lane, status, reason, **kw):
    r = BY_N[rule] if rule else None
    p = {"lane": lane, "status": status, "rule": rule, "decision": list(r.decision) if r else [],
         "reason": reason, "asset_kind": None, "asset": None, "touch": None, "sequence": [], "proposition": None,
         "experiment": None, "arm": None, "handler": None, "notes": []}
    p.update(kw)
    p["action"] = _action(p)
    return p


def _action(p):
    if p["lane"] == "hold":
        return "hold first touches"
    if p["lane"] == "conversation":
        return "answer"
    if p["lane"] == "nothing":
        return "nothing"
    return "send" if p["status"] == "ready" else "wait"


def _routes(p, channel):
    return [r for r in p.get("routes") or [] if r.get("channel") == channel]


def admitted(route):
    """The gate on a route: only a value tied to the place (`high`) and not refused since. For an email that also
    means MX answering; a bounced, suppressed or duplicate address is refused (its verdict says which)."""
    return route.get("verdict") == "high"


def _first(p, channel):
    return next((r for r in _routes(p, channel) if admitted(r)), None)


def _prop(p, propositions):
    """(id, spec) of the record's proposition, from the venture's table."""
    pr = p.get("proposition") or {}
    pid = pr.get("id")
    spec = (propositions or {}).get(pid) if pid else None
    return pid, (spec or {})


def _stop(p, propositions):
    st = p.get("state") or {}
    stage = st.get("stage")
    convo = (p.get("conversation") or {}).get("open")
    if st.get("suppressed"):
        return f"suppressed: {st['suppressed']}"
    if stage in CLIENT_STAGES:
        return f"a client ({stage})"
    if stage in CLOSED_STAGES:
        return f"closed ({stage})"
    if st.get("excluded"):
        return f"no proposition: {st['excluded']}"
    pid, spec = _prop(p, propositions)
    if not pid:
        return "no proposition recorded"
    if not spec.get("lane"):
        return f"no proposition ({pid}: {spec.get('label') or 'not a lane'})" + (
            f": {(p.get('proposition') or {}).get('why')}" if (p.get('proposition') or {}).get('why') else "")
    if st.get("held") and not convo:
        return f"held: {st['held']}"
    return None


def _conversation(p):
    c = p.get("conversation") or {}
    if not c.get("open"):
        return None
    ch = c.get("channel") or "?"
    if ch == "text":
        consent = p.get("consent") or {}
        may = bool(consent.get("ok"))
        return _plan(6, "conversation", "ready", "a text came in: the consent machine answers it"
                     + (" (it may send one reply)" if may else " (it says no text may go)"),
                     handler="consent", touch={"channel": "text", "actor": "machine", "may_send": may,
                                               "line": consent.get("line")})
    close = p.get("close") or {}
    if c.get("class") == "interested" and ch == "email":
        if close.get("open") and close.get("arm"):
            return _plan(6, "conversation", "ready", f"an interested reply: {close.get('experiment')} deals arm "
                         f"{close['arm']}", handler="outreach inbox", experiment=close.get("experiment"),
                         arm=close["arm"], touch={"channel": "email", "actor": close.get("actor") or "taylor"})
        return _plan(6, "conversation", "ready", "an interested reply: Taylor's (the close test is off"
                     + (f": {close['why']})" if close.get("why") else ")"), handler="outreach inbox",
                     experiment=close.get("experiment"), touch={"channel": "email", "actor": "taylor"})
    return _plan(6, "conversation", "ready", f"a {c.get('class') or 'reply'} is open by {ch}",
                 handler="outreach inbox" if ch == "email" else "taylor",
                 touch={"channel": ch, "actor": "taylor" if ch != "email" else "machine"})


def _downstream(capacity):
    d = (capacity or {}).get("downstream")
    if d and d.get("hold"):
        return d.get("why") or "the human queue has been over the daily budget for three days"
    return None


def _no_hold_note(capacity):
    d = (capacity or {}).get("downstream")
    if not d:
        return "rule 7: no hold (downstream capacity wasn't read)"
    known = d.get("known_days") or 0
    if known < 3:
        return f"rule 7: no hold (the human queue has {known} recorded day{'s' if known != 1 else ''} of 3)"
    return f"rule 7: no hold (over the daily budget {d.get('over_budget_days') or 0} of the last {known} days)"


SEQUENCE_DAYS = (0, 3, 10)


def _sent(p):
    """The email lane's own touches on this record, oldest first."""
    return sorted((t for t in p.get("touches") or [] if t.get("actor") == "machine" and t.get("channel") == "email"
                   and t.get("date")), key=lambda t: t["date"])


def _follow_up(p, capacity, propositions, notes):
    """The sequence's next letter when the email lane has written and nobody answered; None otherwise (a first
    touch, a finished sequence, a reply). Rule 3's, never rule 7's: a hold stops first touches only."""
    sent = _sent(p)
    if not sent or (p.get("outcomes") or {}).get("reply"):
        return None
    pid, spec = _prop(p, propositions)
    letters = list(spec.get("letters") or ())
    k = len(sent)
    if spec.get("lane") != "email" or k >= min(len(letters), len(SEQUENCE_DAYS)):
        return None
    import datetime as _dt
    n = SEQUENCE_DAYS[k]
    due = (_dt.date.fromisoformat(sent[0]["date"][:10]) + _dt.timedelta(days=n)).isoformat()
    today = (capacity or {}).get("today")
    ready = bool(today) and today >= due
    pr = p.get("proposition") or {}
    if _downstream(capacity):
        notes.append("rule 7: a follow-up goes on under the downstream hold (first touches hold)")
    touch = {"n": n, "channel": "email", "actor": "machine", "template": letters[k], "due": due}
    return _plan(3, "email", "ready" if ready else "waiting",
                 f"{pid}: the follow-up, day {n} of the sequence"
                 + ("" if ready else (f", due {due}" if today else f", due {due} (no date given to read it against)")),
                 asset_kind="mailbox", asset=sent[-1].get("asset"), touch=touch, proposition=pid,
                 experiment=pr.get("experiment"), arm=pr.get("arm"), handler=f"outreach send --touch {n}",
                 sequence=[{"n": d, "channel": "email", "template": t} for d, t in zip(SEQUENCE_DAYS, letters)],
                 notes=notes)


def _email_plan(p, capacity, pid, spec, rule, actor_first=None):
    """Rule 3: the mailbox the registry chooses for one first letter, by assets.plan_tick (its rules 1-4)."""
    pr = p.get("proposition") or {}
    letters = list(spec.get("letters") or ())
    touch = {"n": 0, "channel": "email", "actor": "machine", "template": letters[0] if letters else None}
    kw = {"asset_kind": "mailbox", "touch": touch, "proposition": pid, "experiment": pr.get("experiment"),
          "arm": pr.get("arm"), "handler": "outreach send --batch",
          "sequence": [{"n": n, "channel": "email", "template": t} for n, t in zip((0, 3, 10), letters)]}
    if not capacity or not capacity.get("snapshot"):
        return _plan(rule, "email", "waiting", "the registry wasn't read, so no mailbox is chosen", **kw)
    import assets                                    # lib/assets.py: the registry's own rules, never a count here
    tick = assets.plan_tick(capacity["snapshot"], capacity.get("usage") or {}, [], [{"id": p.get("key")}],
                            capacity.get("default_cap") or 0, capacity.get("offset") or 0)
    if tick["send"]:
        kw["asset"] = tick["send"][0]["mailbox"]
        return _plan(rule, "email", "ready", f"{pid}: a first letter from {kw['asset']}", **kw)
    why = "; ".join(sorted({x["why"] for x in tick["refused"]})) or "no mailbox in the registry"
    return _plan(rule, "email", "waiting", f"{pid}: no mailbox may take a first letter today ({why})", **kw)


def route(prospect, capacity=None, propositions=None):
    """-> the plan for this prospect: the first rule in ORDER that applies. Pure: it reads the record, the
    capacity and the venture's proposition table, and calls nothing that touches the world."""
    p = prospect or {}
    if propositions is None:
        propositions = _venture_propositions()
    notes = []

    stop = _stop(p, propositions)
    if stop and not stop.startswith("held: "):
        return _plan(1, "nothing", "none", stop, proposition=(p.get("proposition") or {}).get("id"))

    convo = _conversation(p)
    if convo:
        return convo

    follow = _follow_up(p, capacity, propositions, notes)       # not a first touch: rule 7 never holds it
    if follow:
        return follow
    if stop:
        return _plan(1, "nothing", "none", stop, proposition=(p.get("proposition") or {}).get("id"))

    hold = _downstream(capacity)
    if hold:
        return _plan(7, "hold", "waiting", f"first touches hold: {hold}",
                     proposition=(p.get("proposition") or {}).get("id"))
    notes.append(_no_hold_note(capacity))

    level = (p.get("strength") or {}).get("level")
    pid, spec = _prop(p, propositions)
    pr = p.get("proposition") or {}
    email = _first(p, "email")
    dm = next((r for ch in TAYLOR_CHANNELS for r in _routes(p, ch) if admitted(r)), None)

    if level == "strong" and dm:
        seq = [{"n": 0, "channel": dm["channel"], "actor": "taylor"}, {"n": 3, "channel": dm["channel"],
                                                                       "actor": "taylor"}]
        if email and spec.get("lane") == "email" and pr.get("facts"):
            seq.append({"n": 10, "channel": "email", "actor": "machine",
                        "template": (list(spec.get("letters") or ()) or [None])[0]})
        else:
            notes.append("no email for touch three (no admitted address, or no email proposition with its facts)")
        return _plan(2, "taylor", "ready", f"strong, and {dm['channel']} is confirmed: Taylor's queue",
                     asset_kind="taylor", touch=seq[0], sequence=seq, proposition=pid,
                     experiment=pr.get("experiment"), arm=pr.get("arm"), handler="leads today", notes=notes)

    why_not = []
    if spec.get("lane") == "email":
        if not email:
            why_not.append(f"{pid} is an email proposition and " + _email_refusal(p))
        elif not pr.get("facts"):
            why_not.append(f"{pid}'s letter can't be filled from true stored facts"
                           + (f" ({pr['why']})" if pr.get("why") else ""))
        else:
            plan = _email_plan(p, capacity, pid, spec, 3)
            plan["notes"] = notes + plan["notes"]
            return plan

    bounced = any(r.get("verdict") == "bounced" for r in _routes(p, "email"))
    if spec.get("lane") == "card" or bounced:
        post = _first(p, "postal")
        if post:
            return _plan(4, "card", "waiting", ("the card's proposition" if spec.get("lane") == "card" else
                                                "the address bounced") + ": the card lane (not built yet, B54)",
                         asset_kind="card", touch={"n": 0, "channel": "postal", "actor": "machine"},
                         proposition=pid, handler="the card lane (B54)", notes=notes)
        why_not.append("no postal address for a card")

    form = _first(p, "form")
    if form and not email and not dm:
        if level == "strong":
            return _plan(5, "taylor", "ready", "a contact form is the only way in, and it is strong: Taylor, by hand",
                         asset_kind="taylor", touch={"n": 0, "channel": "form", "actor": "taylor"},
                         proposition=pid, handler="leads today", notes=notes)
        why_not.append("a contact form only, and not strong")

    if level == "strong" and not dm and any(_routes(p, ch) for ch in TAYLOR_CHANNELS):
        why_not.append("strong, but its page isn't confirmed as theirs")
    return _plan(None, "nothing", "none", "; ".join(w for w in why_not if w) or
                 f"no rule applies ({pid}, {level or 'unscored'}, no route the policy may use)",
                 proposition=pid, notes=notes)


def _email_refusal(p):
    rs = _routes(p, "email")
    if not rs:
        return "there is no address"
    return "the address isn't one the gate admits (" + "; ".join(
        f"{r.get('value')}: {r.get('verdict')}" + (f", {r['why']}" if r.get("why") else "") for r in rs) + ")"


_PROPS = {}


def _venture_propositions():
    """The venture's PROPOSITIONS table (lib/venture.py), read once."""
    if "t" not in _PROPS:
        import venture
        mod = venture.venture().propositions()
        _PROPS["t"] = copy.deepcopy(mod.PROPOSITIONS) if mod else {}
    return _PROPS["t"]


# ---- the page ----------------------------------------------------------------------------------------------

def page_rules(text):
    """The playbook page's rules, as tests/test_policy.py compares them to RULES: [(n, lane, (decisions...))]
    from its lines `N. **lane** — … (decision: SF#2, AA#4)`, and the order from its `Read in this order:` line."""
    import re
    rules, order = [], None
    for line in text.splitlines():
        m = re.match(r"^(\d+)\. \*\*([a-z]+)\*\* .*\(decision: ([^)]+)\)\s*$", line.strip())
        if m:
            rules.append((int(m.group(1)), m.group(2), tuple(x.strip() for x in m.group(3).split(","))))
        m = re.match(r"^Read in this order: ([\d, ]+)\.?\s*$", line.strip())
        if m:
            order = tuple(int(x) for x in re.findall(r"\d+", m.group(1)))
    return rules, order


def code_rules():
    return [(r.n, r.lane, r.decision) for r in RULES], ORDER
