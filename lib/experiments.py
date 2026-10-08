"""Measurement: the funnel counted by business, and the experiments registry (ROADMAP B142, plan 55 § 5.6).

    import experiments as X
    reg = X.registry(V)                      # ventures/<name>/experiments.json; {} when the venture has none
    cut = X.resolve_cut(["experiment", "E1"], reg)     # or X.Refused, whose message says why
    bizs = X.businesses(sends=..., replies=..., events=..., claimed=..., today=..., reg=reg)
    print("\n".join(X.render_experiment(bizs, "E1", reg, upto=today)))

Record everything, vary one thing (VISION § Decided "Autonomous acquisition" #12). Every send row carries its
dimensions; this module turns the rows the tools already keep (outreach's sends and replies, the pipeline's
events, the claimed previews) into one record per business, each with the date it first reached each of the
seven stages:

    delivered → reply → positive → trial → activated → paid → retained (30 and 90 days)

A business counts once at each stage however many events it has. A cut is either a whole-population dimension
(every business has a value: the channel the first message went by, its segment, its proposition, who sent it,
the provider, the asset, its strength) or a registered experiment's arm; anything else is recorded on the rows
and refused as a cut, because a count by a dimension nobody varied on purpose reads as a result it isn't.

The experiments are the venture's (plan 55 § 5.12): `experiments.json` beside its venture.toml. Each one names
its population, the one dimension it varies, its arms, its start, kill rule, decision owner and primary endpoint,
and where its arm is written on the rows (`fields`). The sequencing doctrine: a later experiment never varies a
dimension before an earlier one's primary endpoint, so an experiment's stages past its endpoint are printed in
grey (bracketed when there's no terminal) and split by the downstream experiment's arm, never as its result.

Knows no product: the stages, the dimensions and the doctrine are the engine's; the experiments and their words
come from the venture's file.
"""

import datetime as dt
import json
import sys
from pathlib import Path

STAGES = ("delivered", "reply", "positive", "trial", "activated", "paid", "retained_30", "retained_90")
STAGE_LABEL = {"delivered": "delivered", "reply": "reply", "positive": "positive", "trial": "trial",
               "activated": "activated", "paid": "paid", "retained_30": "ret 30", "retained_90": "ret 90"}
# The seven stages, as people say them (retained is one stage read at 30 and 90 days).
SEVEN = "delivered → reply → positive → trial → activated → paid → retained 30/90"

# Whole-population dimensions: every business has a value (or "(not recorded)"), none is varied on purpose, so a
# cut by one describes the population and is always allowed. name -> (the record's key, what it is).
DIMENSIONS = {
    "channel": ("channel", "where the first message went: email, facebook, instagram, …"),
    "segment": ("segment", "the census segment"),
    "proposition": ("proposition", "the venture's reason to write (observational except inside an experiment)"),
    "actor": ("actor", "who sent the first message: the machine, or a person by hand"),
    "provider": ("provider", "the sending provider"),
    "asset": ("asset", "the mailbox (asset) the first letter went from"),
    "strength": ("strength", "the lead's strength when the first message went"),
    "fault": ("fault_key", "the fault the first letter named"),
    "prebuilt": ("prebuilt", "whether a preview was built before the first letter"),
}
NOT_RECORDED = "(not recorded)"

# Pipeline outcomes (bin/leads OUTCOMES) read as stages. `visited` is our act, not their answer.
REPLY_OUTCOMES = ("talked", "inbound", "interested", "demo", "later", "trial", "won", "lost")
POSITIVE_OUTCOMES = ("inbound", "interested", "demo", "trial", "won")
# Reply classes (bin/outreach): what isn't a person answering, and what is a positive answer.
NOT_A_REPLY = ("bounce", "out of office", "probe", "pressed")
POSITIVE_CLASSES = ("yes", "interested", "question")
DM_CHANNELS = ("facebook", "instagram", "dm")

FLOOR = 100            # "too few to decide" under 100 delivered a cell (plan 55 § 5.6), unless an experiment says
ACTIVATED_WHY = ("activated (the free week by card) reads 0: nothing records a card-started free week yet, and "
                 "nothing here guesses one")
REQUIRED = ("name", "population", "varied", "arms", "start", "kill_rule", "decision_owner", "primary_endpoint",
            "fields")


class RegistryError(SystemExit):
    """An experiments.json that can't be read; a SystemExit, so the tool ends with the sentence."""

    def __init__(self, msg):
        super().__init__(f"experiments: {msg}")
        self.msg = msg


class Refused(Exception):
    """A cut the doctrine doesn't allow; str() is the reason, in words."""


# ---- the registry -------------------------------------------------------------------------------------------

def registry_path(v):
    """ventures/<name>/experiments.json for a lib/venture.py Venture."""
    return Path(v.path).parent / "experiments.json"


def load(path):
    """{id: spec} from one experiments.json, checked; {} when the file doesn't exist (a venture with none)."""
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise RegistryError(f"{path} isn't readable JSON: {e}")
    exps = data.get("experiments") if isinstance(data, dict) else None
    if not isinstance(exps, dict):
        raise RegistryError(f"{path} needs an \"experiments\" object: {{id: {{…}}}}")
    out = {}
    for eid, e in exps.items():
        if not isinstance(e, dict):
            raise RegistryError(f"{path}: {eid} isn't an object")
        missing = [k for k in REQUIRED if k not in e]
        if missing:
            raise RegistryError(f"{path}: {eid} is missing {', '.join(missing)}")
        if not (isinstance(e["arms"], list) and len(e["arms"]) >= 2 and all(isinstance(a, str) for a in e["arms"])):
            raise RegistryError(f"{path}: {eid}'s arms should be a list of two or more names")
        for k in ("primary_endpoint", "entry"):
            if k in e and e[k] not in STAGES:
                raise RegistryError(f"{path}: {eid}'s {k} {e[k]!r} isn't a stage ({', '.join(STAGES)})")
        f = e["fields"]
        if not (isinstance(f, dict) and f.get("arm") and (f.get("experiment") or f.get("member"))):
            raise RegistryError(f"{path}: {eid}'s fields need \"arm\" and one of \"experiment\" or \"member\" "
                                "(where the rows say a business is in it)")
        try:
            dt.date.fromisoformat(str(e["start"]))
        except ValueError:
            raise RegistryError(f"{path}: {eid}'s start {e['start']!r} isn't a date")
        fl = e.get("floor") or {"stage": "delivered", "n": FLOOR}
        if fl.get("stage") not in STAGES or not isinstance(fl.get("n"), int):
            raise RegistryError(f"{path}: {eid}'s floor should be {{\"stage\": a stage, \"n\": a number}}")
        out[eid] = dict(e, id=eid, entry=e.get("entry", "delivered"), floor=fl)
    return out


def registry(v):
    return load(registry_path(v))


def downstream(reg, eid):
    """The experiments that vary something only after eid's primary endpoint: their entry stage is at or past it."""
    end = STAGES.index(reg[eid]["primary_endpoint"])
    return [d for d in reg if d != eid and STAGES.index(reg[d]["entry"]) >= end]


def crossed(reg, a, b):
    """True when a and b vary things over the same stretch of the funnel (neither waits for the other)."""
    return b not in downstream(reg, a) and a not in downstream(reg, b)


def arm_field_owner(reg, word):
    """The experiment whose arm the rows write under this field name (`variant` -> E2), or None."""
    return next((eid for eid, e in reg.items() if e["fields"].get("arm") == word), None)


# ---- the cut ------------------------------------------------------------------------------------------------

class Cut:
    def __init__(self, kind, name, eid=None):
        self.kind, self.name, self.eid = kind, name, eid      # kind: "dim" | "experiment"

    def __repr__(self):
        return f"Cut({self.kind}, {self.name}, {self.eid})"


def _doctrine(reg, a, b):
    ea, eb = reg[a], reg[b]
    first, later = (a, b) if STAGES.index(ea["entry"]) <= STAGES.index(eb["entry"]) else (b, a)
    end = reg[first]["primary_endpoint"]
    if later in downstream(reg, first):
        return (f"{first} and {later} aren't crossed. {later} varies something only after {first}'s primary "
                f"endpoint ({end}), so {first} is read up to {end}, and its figures past that are printed inside "
                f"its own report split by {later}'s arm, never as a cross and never as {first}'s result (the "
                f"sequencing doctrine). Ask for one: `--by experiment {first}` or `--by experiment {later}`.")
    return (f"{a} and {b} vary things over the same stretch of the funnel, and the registry says never to cross "
            "them: a count of one inside the other would read a mixture as a result (the sequencing doctrine: "
            "one dimension varied at a time). Ask for one: "
            f"`--by experiment {a}` or `--by experiment {b}`.")


def resolve_cut(words, reg, dims=DIMENSIONS, views=()):
    """`--by` words -> a Cut, or Refused with the reason. Accepted: a whole-population dimension; `experiment ID`
    or a bare registered ID; the field an experiment's arm is written under (`variant`, `arm`), which is that
    experiment; and any of `views` (a tool's own whole-population view, e.g. `proposition`)."""
    words = [w for x in (words if isinstance(words, (list, tuple)) else [words]) for w in str(x).replace(",", " ").split()]
    if words and words[0] == "experiment":
        if len(words) == 1:
            raise Refused("say which: `--by experiment ID`" + (f" (registered: {', '.join(reg)})" if reg
                                                                 else " (this venture has no experiments registered)"))
        words = words[1:]
    cuts = []
    for w in words:
        if w in reg:
            cuts.append(Cut("experiment", w, w))
        elif arm_field_owner(reg, w):
            cuts.append(Cut("experiment", w, arm_field_owner(reg, w)))
        elif w in dims or w in views:
            cuts.append(Cut("dim", w))
        else:
            raise Refused(unknown(w, reg, dims, views))
    if not cuts:
        raise Refused("say what to cut by: " + choices(reg, dims, views))
    exps = sorted({c.eid for c in cuts if c.kind == "experiment"})
    if len(exps) >= 2:
        raise Refused(_doctrine(reg, exps[0], exps[1]))
    if len(cuts) > 1:
        raise Refused(f"one dimension a cut: {' × '.join(c.name for c in cuts)} would split the population into "
                      "cells nobody registered, and a difference between them would read as a result. Ask for each "
                      "on its own; " + choices(reg, dims, views))
    return cuts[0]


def choices(reg, dims=DIMENSIONS, views=()):
    d = ", ".join(sorted(set(dims) | set(views)))
    e = ", ".join(reg) if reg else "none registered"
    return f"the cuts are {d}; experiments: {e} (`--by experiment ID`)."


def unknown(word, reg, dims=DIMENSIONS, views=()):
    if word.upper().startswith("E") and word[1:].isdigit():
        return (f"{word} isn't a registered experiment. A test is counted only once it's in the venture's "
                "experiments.json with its population, the one dimension it varies, its arms, start, kill rule, "
                "owner and primary endpoint; until then nothing is read as its result. " + choices(reg, dims, views))
    return (f"{word} isn't a cut. It may be recorded on the rows, but nothing varies it on purpose and it isn't a "
            "property of the whole population, so counting replies by it would read a change nobody registered as a "
            "result (record everything, vary one thing). " + choices(reg, dims, views))


# ---- one record per business --------------------------------------------------------------------------------

def _date(row):
    d = str(row.get("date") or row.get("ts") or "")[:10]
    try:
        dt.date.fromisoformat(d)
        return d
    except ValueError:
        return ""


def _flat(row):
    """A row with its `outbound` tags (the pipeline keeps the send's fields there) lifted beside its own."""
    out = dict(row.get("outbound") or {}) if isinstance(row.get("outbound"), dict) else {}
    out.update({k: v for k, v in row.items() if k != "outbound"})
    return out


def _arm(spec, row):
    f = spec["fields"]
    if f.get("experiment") and row.get(f["experiment"]) != spec["id"]:
        return None
    if f.get("member") and not row.get(f["member"]):
        return None
    a = row.get(f["arm"])
    return a if a in spec["arms"] else None


def _earliest(a, b):
    return b if not a or (b and b < a) else a


def businesses(sends=(), replies=(), events=(), claimed=None, today=None, reg=None,
               positive_classes=POSITIVE_CLASSES, not_a_reply=NOT_A_REPLY):
    """{key: business} from the tools' rows. A business is in the funnel once something was sent to it: a send row
    (the machine's letters) or a `messaged` pipeline event (a DM, a letter logged by hand). Its dimensions are its
    first message's; its arms are whatever the registry's fields say on any of its rows; its stages are the first
    date each was reached, filled forward (a paid business replied) except activated, which is only ever recorded.

    sends: outreach send rows (cold ones; Taylor's own answers aren't sends). replies: outreach reply rows.
    events: pipeline events. claimed: {place_id: date} of claimed previews. Rows may lack any field."""
    reg = reg or {}
    today = (today or dt.date.today()).isoformat() if not isinstance(today, str) else today
    alias = {}                            # email -> place_id, so a reply known only by address finds its business
    for r in (*sends, *replies, *events):
        if r.get("place_id") and r.get("email"):
            alias.setdefault(str(r["email"]).lower(), r["place_id"])

    def key(r):
        if r.get("place_id"):
            return r["place_id"]
        e = str(r.get("email") or "").lower()
        if e:
            return alias.get(e, e)
        return r.get("key")

    b = {}

    def biz(k):
        return b.setdefault(k, {"key": k, "name": None, "contact": None, "first_row": None, "first_kind": None,
                                "stages": dict.fromkeys(STAGES), "arms": {}, "bounced": False, "dm": False,
                                "churned": None})

    def note_arms(x, row):
        for eid, spec in reg.items():
            a = _arm(spec, row)
            if a and eid not in x["arms"]:
                x["arms"][eid] = a

    def stage(x, s, d):
        if d:
            x["stages"][s] = _earliest(x["stages"][s], d)

    order = lambda r: (str(r.get("ts") or r.get("date") or ""))      # noqa: E731
    for r in sorted(sends, key=order):
        k = key(r)
        if not k:
            continue
        x, d = biz(k), _date(r)
        x["name"] = x["name"] or r.get("name")
        if d and (not x["contact"] or d < x["contact"]):
            x["contact"], x["first_row"], x["first_kind"] = d, r, "send"
        note_arms(x, r)
    for e in sorted(events, key=order):
        if e.get("kind") in ("strength", "touch_due"):
            continue
        k = key(e)
        if not k:
            continue
        x, d, row, o = biz(k), _date(e), _flat(e), e.get("outcome")
        x["name"] = x["name"] or e.get("name")
        note_arms(x, row)
        if o == "messaged":
            if d and (not x["contact"] or d < x["contact"]):
                x["contact"], x["first_row"], x["first_kind"] = d, row, "event"
            if x["first_kind"] == "send" and not x.get("strength_row"):
                x["strength_row"] = row               # the pipeline line the send wrote carries the strength
            if row.get("channel") != "email" and not e.get("outbound"):
                x["dm"] = True
        if o in REPLY_OUTCOMES:
            stage(x, "reply", d)
        if o in POSITIVE_OUTCOMES:
            stage(x, "positive", d)
        if o == "trial":
            stage(x, "trial", d)
        if o == "activated":
            stage(x, "activated", d)
        if o == "won":
            stage(x, "paid", d)
        if o == "churned":
            x["churned"] = _earliest(x["churned"], d)
    for r in sorted(replies, key=order):
        k = key(r)
        if not k:
            continue
        x, d, cls = biz(k), _date(r), r.get("class")
        note_arms(x, r)
        if cls == "bounce":
            x["bounced"] = True
        elif cls not in not_a_reply:
            stage(x, "reply", d)
            if cls in positive_classes:
                stage(x, "positive", d)
    for pid, d in (claimed or {}).items():
        if pid in b:
            stage(b[pid], "trial", str(d or "")[:10] or today)

    out = {}
    for k, x in b.items():
        if not x["contact"]:
            continue                      # came to us without our writing first: not in this funnel
        st = x["stages"]
        if not (x["bounced"] and not x["dm"] and not st["reply"]):
            st["delivered"] = x["contact"]
        later = None                      # fill forward: a business that paid had replied, was positive, tried it
        for s in ("paid", "trial", "positive", "reply", "delivered"):
            if st[s]:
                later = _earliest(later, st[s])
            elif later:
                st[s] = later
        if st["paid"]:
            paid = dt.date.fromisoformat(st["paid"])
            for n in (30, 90):
                due = (paid + dt.timedelta(days=n)).isoformat()
                if due <= today and not (x["churned"] and x["churned"] < due):
                    st[f"retained_{n}"] = due
        first = x["first_row"] or {}
        sr = x.get("strength_row") or first
        out[k] = {"key": k, "name": x["name"], "stages": st, "arms": x["arms"], "dims": dims_of(first, x["first_kind"],
                                                                                             sr)}
    return out


def dims_of(row, kind, strength_row=None):
    """The whole-population dimensions of a business, from its first message."""
    def val(*names):
        for n in names:
            v = row.get(n)
            if v not in (None, ""):
                return v
        return None
    if kind == "send":
        channel = row.get("channel") or "email"
        actor = row.get("actor") or "machine"
    else:
        channel = row.get("channel") or row.get("source")
        actor = row.get("actor") or ("machine" if row.get("letter_sha") or row.get("batch_id") else "person")
    prebuilt = row.get("prebuilt")
    out = {"channel": channel, "actor": actor, "segment": val("segment"), "proposition": val("proposition"),
           "provider": val("provider"), "asset": val("asset", "mailbox"), "fault_key": val("fault_key"),
           "prebuilt": None if prebuilt is None else ("prebuilt" if prebuilt in (True, "true") else "not prebuilt"),
           "strength": (strength_row or {}).get("strength") or row.get("strength")}
    out["lane"] = lane_of_channel(out["channel"])
    return {k: (str(v) if v not in (None, "") else NOT_RECORDED) for k, v in out.items()}


def lane_of_channel(channel):
    c = str(channel or "").lower()
    return "email" if c == "email" else "dm" if c in DM_CHANNELS else (c or "other")


# ---- counting -----------------------------------------------------------------------------------------------

def _reached(x, s, upto, since=None):
    d = x["stages"].get(s)
    return bool(d) and d <= upto and (since is None or d >= since)


def count(bizs, group_of, upto, since=None):
    """{group: {"all": {stage: n}, "new": {stage: n}}}: businesses at each stage by `upto` and, of those, how many
    got there on or after `since`. A business is in a group once its first message is on or before upto."""
    out = {}
    for x in bizs.values():
        g = group_of(x)
        if g is None or not _first(x, upto):
            continue
        cell = out.setdefault(g, {"all": dict.fromkeys(STAGES, 0), "new": dict.fromkeys(STAGES, 0)})
        for s in STAGES:
            cell["all"][s] += _reached(x, s, upto)
            if since:
                cell["new"][s] += _reached(x, s, upto, since)
    return out


def _first(x, upto):
    d = min((v for v in x["stages"].values() if v), default=None)
    return d and d <= upto


def per_hundred(n, d):
    return f"{n} ({100.0 * n / d:.1f})" if d else f"{n} (–)"


def _grey(text, on):
    return f"\033[2m{text}\033[0m" if on else text


def use_colour(stream=None):
    s = stream or sys.stdout
    return hasattr(s, "isatty") and s.isatty()


def table(cells, order, label, base="delivered", since=None, grey_from=None, colour=False):
    """Lines: one row a group, the seven stages (retained as 30/90), each 'n (per 100 of base)', '+k' new since."""
    w = max(len(label), *(len(str(g)) for g in order)) if order else len(label)
    heads = ["delivered", "reply", "positive", "trial", "activated", "paid", "retained 30/90"]
    gi = STAGES.index(grey_from) if grey_from else None

    def mark(s, text):
        if gi is None or STAGES.index(s) < gi:
            return text
        return _grey(f"[{text}]", colour)
    lines = [f"  {label:<{w}}  " + "  ".join(f"{h:>14}" for h in heads)]
    for g in order:
        c = cells[g]
        d = c["all"][base]
        row = []
        for s in STAGES[:6]:
            n = c["all"][s]
            plain = STAGES.index(s) <= STAGES.index(base)          # the base, and the stages before an entry
            t = (str(n) if plain else per_hundred(n, d)) + (f" +{c['new'][s]}" if since and c["new"][s] else "")
            row.append(f"{mark(s, t):>14}")
        r30, r90 = c["all"]["retained_30"], c["all"]["retained_90"]
        row.append(f"{mark('retained_30', f'{r30}/{r90}'):>14}")
        lines.append(f"  {str(g):<{w}}  " + "  ".join(row))
    return lines


def retained_note(bizs, upto):
    paid = sum(1 for x in bizs.values() if _reached(x, "paid", upto))
    if not paid:
        return "retained reads 0: no business has paid yet, so none can be 30 or 90 days on."
    young = sum(1 for x in bizs.values() if _reached(x, "paid", upto) and not _reached(x, "retained_30", upto))
    return (f"retained: a paid business still on a plan 30 and 90 days after its first charge ({young} of the {paid} "
            "paid is under 30 days on, so not counted either way yet)." if young == 1 else
            f"retained: a paid business still on a plan 30 and 90 days after its first charge ({young} of the {paid} "
            "paid are under 30 days on, so not counted either way yet)." if young else
            "retained: a paid business still on a plan 30 and 90 days after its first charge.")


def render_dim(bizs, dim, upto, since=None, floor=FLOOR, colour=False, scope="every business written to"):
    """`--by <dimension>`: the seven stages per value, counted by business, and too few to decide under the floor."""
    field = DIMENSIONS[dim][0] if dim in DIMENSIONS else dim
    cells = count(bizs, lambda x: x["dims"].get(field, NOT_RECORDED), upto, since)
    lines = [f"By {dim} ({DIMENSIONS.get(dim, (None, ''))[1]}) — {scope}, to {upto}; one business counts once at "
             "each stage; n (per 100 delivered)" + (f", +n since {since}" if since else "") + "."]
    if not cells:
        return lines + ["  nothing delivered yet, so nothing to count"]
    order = sorted(cells, key=lambda g: (g == NOT_RECORDED, -cells[g]["all"]["delivered"], str(g)))
    lines += table(cells, order, dim, since=since, colour=colour)
    small = [g for g in order if cells[g]["all"]["delivered"] < floor]
    if small:
        lines.append(f"Too few to decide: {', '.join(map(str, small))} "
                     f"{'has' if len(small) == 1 else 'have'} under {floor} delivered. A whole-population cut "
                     "describes who we wrote to; it isn't an experiment, so even above the floor it says where to "
                     "look, not what caused what.")
    lines += [ACTIVATED_WHY + ".", retained_note(bizs, upto)]
    return lines


def render_experiment(bizs, eid, reg, upto, since=None, colour=False):
    """`--by experiment ID`: the seven stages per arm; under the floor a cell says too few to decide; the stages past
    the primary endpoint in grey, split by each downstream experiment's arm, never read as this one's result."""
    e = reg[eid]
    members = {k: x for k, x in bizs.items() if eid in x["arms"]}
    cells = count(members, lambda x: x["arms"][eid], upto, since)
    end, entry, fl = e["primary_endpoint"], e["entry"], e["floor"]
    end_i = STAGES.index(end)
    grey_from = STAGES[end_i + 1] if end_i + 1 < len(STAGES) else None
    lines = [f"{eid} {e['name']} — {' vs '.join(e['arms'])} on {e['population']}; varies {e['varied']}; since "
             f"{e['start']}; {e.get('status') or 'open'}; decision: {e['decision_owner']}",
             f"Primary endpoint: {end}" + (f" (per 100 {entry})" if entry != "delivered" else "") +
             f". Kill rule: {e['kill_rule']}" + (f". Held at default: {e['held_at_default']}"
                                                 if e.get("held_at_default") else "") + ".",
             f"Counted by business, one business once at each stage, to {upto}; n (per 100 {entry})"
             + (f", +n since {since}" if since else "") + "."
             + (f" Stages past {end} are bracketed{' and grey' if colour else ''}: reported, not {eid}'s result."
                if grey_from else "")]
    empty = {"all": dict.fromkeys(STAGES, 0), "new": dict.fromkeys(STAGES, 0)}
    for a in e["arms"]:
        cells.setdefault(a, {"all": dict(empty["all"]), "new": dict(empty["new"])})
    order = list(e["arms"]) + sorted(g for g in cells if g not in e["arms"])
    lines += table(cells, order, "arm", base=entry, since=since, grey_from=grey_from, colour=colour)
    verdicts = []
    for a in e["arms"]:
        n = cells[a]["all"][fl["stage"]]
        if n < fl["n"]:
            verdicts.append(f"{a}: too few to decide ({n} {fl['stage']} of {fl['n']})")
        else:
            verdicts.append(f"{a}: {n} {fl['stage']}, past the floor")
    lines.append("  " + "  |  ".join(verdicts))
    k = kill_check(e, cells)
    if k:
        lines.append(k)
    if grey_from:
        for d in downstream(reg, eid):
            lines += _stratified(members, eid, d, reg, upto, grey_from, colour)
    others = [o for o in reg if o != eid and crossed(reg, eid, o)]
    for o in others:
        both = sum(1 for x in members.values() if o in x["arms"])
        if both:
            lines.append(f"Crossed: {both} business{'es are' if both != 1 else ' is'} in both {eid} and {o}, which the "
                         "registry says never happens; their counts can't be separated, so read neither until it's "
                         "explained.")
    lines.append(ACTIVATED_WHY + ".")
    lines.append(retained_note(members, upto))
    return lines


def _stratified(members, eid, d, reg, upto, grey_from, colour):
    e, de = reg[eid], reg[d]
    start = STAGES.index(de["entry"])
    shown = STAGES[start:]
    lines = [_grey(f"{eid} past {e['primary_endpoint']}, split by {d} ({de['name']}: {' vs '.join(de['arms'])}); "
                   f"reported, never {eid}'s result:", colour)]
    for a in e["arms"]:
        for da in [*de["arms"], None]:
            group = [x for x in members.values() if x["arms"].get(eid) == a and x["arms"].get(d) == da]
            if da is None:
                group = [x for x in group if _reached(x, de["entry"], upto)]
            if not group:
                continue
            parts = []
            for s in shown:
                if s == "retained_90":
                    continue
                n = sum(_reached(x, s, upto) for x in group)
                parts.append(f"{STAGE_LABEL[s]} {n}" if s != "retained_30"
                             else f"retained {n}/{sum(_reached(x, 'retained_90', upto) for x in group)}")
            lines.append(_grey(f"  [{a} · {d} {da or 'not dealt'}: " + ", ".join(parts) + "]", colour))
    if len(lines) == 1:
        lines.append(_grey(f"  [nothing past {e['primary_endpoint']} yet]", colour))
    return lines


def kill_check(e, cells):
    """The kill rule, when the registry says it in numbers: {"stage", "min_base", "under_ratio"}. It reports; pausing
    an arm is the decision owner's word."""
    k = e.get("kill")
    if not isinstance(k, dict):
        return None
    base = e["entry"]
    rates = {a: (cells[a]["all"][k["stage"]] / cells[a]["all"][base] if cells[a]["all"][base] else None)
             for a in e["arms"]}
    hit = []
    for a in e["arms"]:
        if cells[a]["all"][base] < k["min_base"] or rates[a] is None:
            continue
        best = max((r for o, r in rates.items() if o != a and r is not None
                    and cells[o]["all"][base] >= k["min_base"]), default=None)
        if best and rates[a] < k["under_ratio"] * best:
            hit.append(a)
    if not hit:
        return "Kill rule: not crossed."
    return (f"Kill rule crossed for {', '.join(hit)}: its {k['stage']} rate is under {k['under_ratio']:g} of the "
            f"other's with {k['min_base']}+ {base}. Pausing it is {e['decision_owner']}'s word; nothing here pauses it.")


# ---- cost by lane -------------------------------------------------------------------------------------------

LANE_INCLUDES = {
    "email": "the reply classifier, the Factory's purchases (domains, mailboxes, as the ledger's commit lines say) "
             "and the batch's listing reads",
    "dm": "the kits' and previews' listing reads, the prep runs (research, build, judge) and the previews",
}


def lane_of_ledger(row):
    """The lane one ledger line paid for, or None when it serves both or neither (a brief, a diagnosis, social)."""
    tool, kind, what = str(row.get("tool") or ""), str(row.get("kind") or ""), str(row.get("for") or "")
    if tool == "outreach" or kind == "infra" or tool == "infra":
        return "email"
    if tool == "prep":
        return "dm"
    if tool == "leads":
        if what.startswith("batch"):
            return "email"
        if not what or what.startswith(("brief", "diagnose", "day-")):
            return None                   # a call's brief, a group-thread diagnosis, a follow-up read: either lane
        if kind == "preview" or kind.startswith("places"):
            return "dm"                   # the kits (Saturday, remote) and the previews they link
    return None


def costs(ledger_rows, venture_name, start, end):
    """{lane: usd} for ledger lines dated start..end (inclusive ISO dates), this venture's or unmarked; and the
    lines no lane owns, as lane None."""
    out = {}
    for r in ledger_rows:
        v = r.get("venture")
        if v and v != venture_name:
            continue
        d = str(r.get("ts") or "")[:10]
        if not (start <= d <= end):
            continue
        if r.get("kind") == "infra" and r.get("phase") != "commit":
            continue                      # intent lines plan a cost; the commit line is what was spent
        try:
            usd = float(r.get("cost_usd") or 0)
        except (TypeError, ValueError):
            continue
        lane = lane_of_ledger(r)
        out[lane] = out.get(lane, 0.0) + usd
    return out


def render_costs(bizs, ledger_rows, venture_name, upto, since, first_day="0000-01-01"):
    """Cost per conversation (this week) and per paid client (to date), by lane, from the ledger's own lines."""
    week = costs(ledger_rows, venture_name, since, upto)
    ever = costs(ledger_rows, venture_name, first_day, upto)
    lines = [f"Cost by lane (the ledger's lines; this week {since}..{upto}, and to date):"]
    for lane in ("email", "dm"):
        convo = sum(1 for x in bizs.values() if x["dims"]["lane"] == lane and _reached(x, "reply", upto, since))
        paid = sum(1 for x in bizs.values() if x["dims"]["lane"] == lane and _reached(x, "paid", upto))
        w, t = week.get(lane, 0.0), ever.get(lane, 0.0)
        per_c = f"${w / convo:.2f} a conversation" if convo else "no conversation this week"
        per_p = f"${t / paid:.2f} a paid client" if paid else "no paid client yet"
        lines.append(f"  {lane:<5} ${w:.2f} this week, {convo} conversation{'s' if convo != 1 else ''} → {per_c}; "
                     f"to date ${t:.2f}, {paid} paid → {per_p}")
        lines.append(f"        includes {LANE_INCLUDES[lane]}")
    if ever.get(None):
        lines.append(f"  not split by lane: ${week.get(None, 0.0):.2f} this week, ${ever[None]:.2f} to date (briefs, "
                     "diagnoses, follow-up reads, pictures: they serve both lanes or neither). Monthly fees (mailboxes, "
                     "domains) are on the registry, not in the ledger, so they aren't here.")
    else:
        lines.append("  Monthly fees (mailboxes, domains) are on the registry, not in the ledger, so they aren't here.")
    return lines
