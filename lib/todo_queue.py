"""The human queue (ROADMAP B138; plan 55 § 5.5; VISION § Rules 9): `todo now`, `todo audit`,
`todo reconcile`, over the owner's todo file and the done trail in the history file.

A utility, not an engine with a product in it (VISION § Rules 10): it reads markdown in the shape
the todo file has had since 2026-09-28 and knows no business's name, domain, price or phone.
Everything here is pure text in, text (or a dict) out; bin/todo does the file and process work.

The file's shape, as parsed here:
  ## 1. Now …              a section; `### 1b. …` / `### 1c. …` are sub-sections with their own id
  - [ ] **Title.** one line on what it unblocks …
    - **1.** a step …                       indented continuation lines belong to the entry
    _(who, 2026-10-07; repeat_key: k; human: money; ~10 min)_     the old metadata form
    _(reconcile 2026-10-07: STALE — why)_                         a reconcile proposal
    <!-- todo: repeat_key=k; human_reason=money; estimated_minutes=10 -->   the hidden form (B138)

Every classification below is a proposal with its reason, and any of them can come back "unsure":
a reader (Flint, then Taylor) decides, and nothing here moves an entry without the word.
"""

import re
from datetime import date, timedelta

# --- parsing -----------------------------------------------------------------

HEADER = re.compile(r"^(#{2,3}) (.*)$")
SEC_ID = re.compile(r"^(\d+[a-z]?)[.)]")
ENTRY = re.compile(r"^- \[( |x|X|~)\] (.*)$")
BOLD = re.compile(r"\*\*(.+?)\*\*")
DATE = re.compile(r"\b(20\d\d-\d\d-\d\d)\b")
WHO_LINE = re.compile(r"^_\(([^()]*?(?:\([^()]*\)[^()]*?)*)\)_\s*$")
HIDDEN = re.compile(r"^\s*<!--\s*todo:(.*?)-->\s*$")
RECONCILE = re.compile(r"_\(reconcile (20\d\d-\d\d-\d\d):\s*(.*?)\)_\s*$")
WAITING = re.compile(r"waiting:\s*(B\d+)")
ROW = re.compile(r"\b(B\d{2,3})\b")
CLASSES = ("HUMAN_NOW", "AUTOMATE", "SUPERSEDED", "WAITING_FOR_AUTOMATION", "DONE", "STALE")
# Where an entry may go besides the done trail: a proposal "→ § 3" / "→ § 4" moves it to that section.
MOVE_TO = re.compile(r"→\s*§\s*(\d+[a-z]?)")


def parse(text):
    """-> list of entries, in file order. Each entry: dict with section (its id: '1', '1b', '3' …),
    section_name, start/end line indexes (end exclusive, trailing blank lines not included),
    done, title, head (title + the rest of its first paragraph), lines (the block), and the
    parsed metadata (see `metadata`)."""
    lines = text.split("\n")
    out, sec, sec_name, i = [], None, "", 0
    while i < len(lines):
        line = lines[i]
        h = HEADER.match(line)
        if h:
            sec_name = h.group(2).strip()
            m = SEC_ID.match(sec_name)
            sec = m.group(1) if m else sec_name.lower()
            i += 1
            continue
        m = ENTRY.match(line)
        if m and sec is not None:
            j = i + 1
            while j < len(lines) and not ENTRY.match(lines[j]) and not HEADER.match(lines[j]) \
                    and (lines[j].startswith("  ") or not lines[j].strip()):
                j += 1
            end = j
            while end > i + 1 and not lines[end - 1].strip():
                end -= 1
            block = lines[i:end]
            e = {"section": sec, "section_name": sec_name, "start": i, "end": end,
                 "done": m.group(1) != " ", "lines": block}
            e.update(metadata(block))
            out.append(e)
            i = j
            continue
        i += 1
    return out


def _first_para(block):
    """The entry's first line plus any wrapped continuation before the first step or italic line."""
    para = [block[0][6:]]
    for l in block[1:]:
        s = l.strip()
        if not s or s.startswith("- ") or s.startswith("_(") or s.startswith("<!--"):
            break
        para.append(s)
    return " ".join(para)


def metadata(block):
    first = _first_para(block)
    b = BOLD.search(first)
    title = (b.group(1) if b else first)[:200].strip()
    text = "\n".join(block)
    meta = {}
    # the old italic form: _(who, 2026-10-07; repeat_key: k; human: money; ~10 min)_
    for l in block:
        s = l.strip()
        for part in re.findall(r"(repeat_key|human|human_reason|estimated_minutes):\s*([^;)]+)", s) if "repeat_key" in s else []:
            k, v = part
            meta[{"human": "human_reason"}.get(k, k)] = v.strip()
        mm = re.search(r";\s*~(\d+)\s*min\)_\s*$", s)
        if mm and "repeat_key" in s:
            meta["estimated_minutes"] = mm.group(1)
    # the hidden form wins where both are present
    for l in block:
        h = HIDDEN.match(l)
        if h:
            for part in h.group(1).split(";"):
                if "=" in part:
                    k, _, v = part.partition("=")
                    meta[k.strip()] = v.strip()
    filed = None
    for l in block:
        w = WHO_LINE.match(l.strip())
        if w and not w.group(1).startswith("reconcile"):
            d = DATE.search(w.group(1))
            if d:
                filed = d.group(1)
                break
    rec = None
    for l in block:
        r = RECONCILE.search(l.strip())
        if r:
            rec = {"date": r.group(1), "text": r.group(2).strip()}
    done_on = None
    dm = re.search(r"\b(?:Done|done|Checked|ticked)\b[^0-9\n]{0,40}(20\d\d-\d\d-\d\d)", text)
    if dm:
        done_on = dm.group(1)
    waiting = meta.get("waiting") or (WAITING.search(rec["text"]).group(1) if rec and WAITING.search(rec["text"]) else None)
    automatable = re.search(r"automatable:\s*([^\n_]+)", text)
    kept = re.search(r"kept manual because:\s*([^\n_]+)", text)
    return {"title": title, "head": first, "text": text, "meta": meta, "filed": filed,
            "reconcile": rec, "done_on": done_on, "waiting": waiting,
            "automatable_note": automatable.group(1).strip() if automatable else None,
            "kept_manual": kept.group(1).strip() if kept else None}


def short_title(title, n=58):
    t = re.sub(r"\s*\([^()]*\)", "", title).strip().rstrip(".").strip()
    t = re.sub(r"\s+—.*$", "", t) if len(t) > n else t
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


# --- minutes -------------------------------------------------------------------

NUM = {"one": 1, "a": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10, "fifteen": 15,
       "twenty": 20, "thirty": 30, "forty-five": 45, "forty": 40, "sixty": 60}
MIN_RE = re.compile(r"\b(\d{1,3}|one|a|two|three|four|five|six|ten|fifteen|twenty|thirty|forty-five|forty|sixty)"
                    r"[ -](?:minutes?|min)\b", re.I)
HOUR_RE = re.compile(r"\b(an|one|two|\d)\s+hours?\b|\ban evening\b|\bone sitting\b|\ban afternoon\b", re.I)
DEFAULT_MINUTES = 10


def minutes(e):
    """(minutes, guessed): the entry's own estimate (hidden line, italic line, then the title, the
    first paragraph and the body), else DEFAULT_MINUTES marked as a guess."""
    v = e["meta"].get("estimated_minutes")
    if v and str(v).isdigit():
        return int(v), False
    for src in (e["title"], e["head"], e["text"]):
        m = MIN_RE.search(src)
        if m:
            w = m.group(1).lower()
            return (int(w) if w.isdigit() else NUM[w]), False
        h = HOUR_RE.search(src)
        if h:
            w = (h.group(1) or "").lower()
            if not w:
                return (180 if "evening" in h.group(0) or "afternoon" in h.group(0) else 60), False
            return (60 * (1 if w in ("an", "one") else 2 if w == "two" else int(w))), False
    return DEFAULT_MINUTES, True


def fmt_minutes(m):
    return f"{m} min" if m < 60 else f"{m // 60} h" + (f" {m % 60} min" if m % 60 else "")


# --- Rule 9: human-only or automatable -----------------------------------------------
# Signals are read from the entry's title and first paragraph (its "what it is"), not its steps:
# the steps of a human-only entry are full of copy-this-value detail that would mislead.

HUMAN = [
    ("identity", re.compile(r"\b(sign[- ]?up|signs? in|accounts?|identity|verif\w*|enrol\w*|passkey|2fa|"
                            r"dba|register\w*|open the|application|keys?|tokens?)\b", re.I)),
    ("money", re.compile(r"(\bbuy\b|\bpay\b|\bpayment|\bcredits\b|\bbilling\b|\bcard\b|\bcancel\b|"
                         r"\bsubscription|\btax\b|\bbank\b|\bchecking\b|\brefund|\bdon't pay\b|\bthe money\b|\bcpa\b)", re.I)),
    ("contract", re.compile(r"\b(terms|contract|agree\w*|lease|accept the)\b", re.I)),
    ("judgment", re.compile(r"(\bdecide\b|\bdecision\b|\bsay (?:go|the word|yes|ship|`?prep approve)|\bapprove\b|"
                            r"\bre-approve\b|\bread\b.*\bsay\b|\bkeep it\b|\bchoose\b|\bwhich\b|\bstays up\b|"
                            r"\bone word each\b|\btake them out\b|\bread (?:three|the|it|one)\b|\?)", re.I)),
    ("physical", re.compile(r"\b(from (?:a|your) phone|on your phone|the mac|laptop|photo|in person|"
                            r"visit|print\w*|encrypt\w*|scrub|lock the)\b", re.I)),
]

# (repeat_key, pattern on the title/first paragraph, the one-line "how" a machine would do it)
AUTOMATABLE = [
    ("env-value", re.compile(r"\benvs?\b|\benvironment\b|setenv|\b(?:one|two|three) lines? in\b", re.I),
     "the deploy host's API sets the variable and redeploys (one write-scoped token, once; "
     "the values are already in hand), so the step never comes back"),
    ("dns-record", re.compile(r"\bdns\b|\bcname\b|\btxt record\b|\bnameservers?\b", re.I),
     "the DNS host's API, with the zone token we hold, adds the record and reads it back"),
    ("live-check", re.compile(r"\blive checks?\b|\bchecks?\b.*\b(?:look|signed in)\b|\bfill\b.*\bonce\b|"
                              r"\bphone checks?\b|\bsee the\b.*\bonce\b|\btwo looks\b", re.I),
     "the headless browser (shot / Playwright) runs the check and reports what it saw"),
]


def rule9(e):
    """-> (class, reason_or_how, repeat_key_hint). class is 'human-only', 'automatable' or 'unsure'.
    The title is read first (it names the action); the first paragraph only when the title says
    nothing. Identity, money and contract outrank an automatable pattern; an automatable pattern
    outranks judgment or a physical act, whose part is named as staying human."""
    if e["automatable_note"]:
        return "automatable", e["automatable_note"], None
    hr = e["meta"].get("human_reason")
    if hr:
        return "human-only", hr, None
    for src in (e["title"], e["head"]):
        found = [(k, p.search(src)) for k, p in HUMAN]
        found = [(k, m) for k, m in found if m]
        autos = [(k, how) for k, p, how in AUTOMATABLE if p.search(src)]
        strong = sorted(((k, m) for k, m in found if k in ("identity", "money", "contract")),
                        key=lambda km: km[1].start())
        if strong:
            k, m = strong[0]
            return "human-only", f"{k} (\"{m.group(0).strip()}\")", None
        if autos:
            k, how = autos[0]
            extra = [kk for kk, _ in found]
            if extra:
                how += f"; the {extra[0]} part stays a human step"
            return "automatable", how, k
        if found:
            k, m = found[0]
            return "human-only", f"{k} (\"{m.group(0).strip()[:40]}\")", None
    return "unsure", "no Rule 9 signal in the title or first line; a reader decides", None


# --- repeat keys ------------------------------------------------------------------

KEY_RULES = [
    ("provider-account", re.compile(r"\b(?:open|create|sign up for)\b.*\baccounts?\b|\bthe accounts\b", re.I)),
    ("subscription-cancel", re.compile(r"\bcancel\b|\bdon't pay\b|\blet the trial lapse\b", re.I)),
    ("env-value", AUTOMATABLE[0][1]),
    ("dns-record", AUTOMATABLE[1][1]),
    ("approve-letters", re.compile(r"\bapprove\b.*\bletters?\b|\bre-approve\b|\bletter\b.*\bapprove\b", re.I)),
    ("read-plan-go", re.compile(r"\bread\b.*\bplans?\b|\bsay go\b|\bsay the word\b", re.I)),
    ("api-application", re.compile(r"\bapplication\b|\bapp review\b", re.I)),
    ("oauth-grant", re.compile(r"\bgrant\b|\boauth\b|\bconnect\b", re.I)),
    ("live-check", AUTOMATABLE[2][1]),
    ("key-rotate", re.compile(r"\b(?:retire|rotate|delete)\b.*\b(?:keys?|tokens?)\b", re.I)),
]


def repeat_key(e):
    k = e["meta"].get("repeat_key")
    if k:
        return k
    head = e["title"]
    for key, p in KEY_RULES:
        if p.search(head):
            return key
    words = [w for w in re.findall(r"[a-z0-9]+", short_title(e["title"]).lower())
             if w not in ("the", "a", "an", "and", "or", "of", "to", "on", "for", "your", "one", "two", "in")]
    return "-".join(words[:4]) or "untitled"


# --- todo now --------------------------------------------------------------------

FUNNEL = re.compile(r"\b(lane|outreach|letters?|leads?|prospects?|sell\w*|batch|mailbox\w*|dms?|"
                    r"preview|prep|provider|funnel|sends?|replies|campaign|production line|press link)\b", re.I)
NOT_BEFORE = re.compile(r"\bon (20\d\d-\d\d-\d\d)\b")
TICK = re.compile(r"`([^`]+)`")
URL = re.compile(r"\b((?:https?://)?(?:[a-z0-9-]+\.)+(?:com|ai|io|dev|site|net|org|app|cloud)(?:/[^\s)`,;]*)?)",
                 re.I)


def command_for(e, n):
    """The first command or link in the entry's steps (one line, ≤ 44 chars), else `todo show N`.
    A backtick span counts as a command when it is marked `! …`, opens the step, or follows run /
    type / say / text; a backtick in the middle of prose is usually a reference, not the thing to do."""
    for l in e["lines"][1:]:
        s = l.strip()
        if not s.startswith("- **"):
            continue
        body = re.sub(r"^- \*\*[^*]+\*\*\s*", "", s)
        cands = []
        for m in TICK.finditer(body):
            span = m.group(1).strip()
            before = body[:m.start()].rstrip().lower()
            if not span.lstrip("! ") or (" " not in span and not span.startswith(("!", "./", "/"))):
                continue                     # a path, a name or a value: a reference, not a step
            if span.startswith("!") or not before or re.search(r"\b(run|type|say|text|then|paste)\b:?$", before) \
                    or before.endswith("→"):
                cands.append((m.start(), "`" + span.lstrip("! ").strip() + "`"))
        plain = TICK.sub(lambda m: " " * len(m.group(0)), body)
        for u in URL.finditer(plain):
            if u.start() and plain[u.start() - 1] in "@.":
                continue                     # an email address, not a link
            cands.append((u.start(), u.group(1)))
            break
        if cands:
            pick = min(cands)[1]
            return pick if len(pick) <= 44 else pick[:42] + "…" + ("`" if pick.startswith("`") else "")
    return f"`todo show {n}`"


def roadmap_status(roadmap_text):
    """{row id: its last table cell} from ROADMAP's tables (the status column)."""
    out = {}
    for line in (roadmap_text or "").splitlines():
        m = re.match(r"^\|\s*(B\d+)\s*\|", line)
        if m:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            out[m.group(1)] = cells[-1] if len(cells) > 2 else ""
    return out


def shipped(status):
    return bool(re.match(r"(?i)(done|built|shipped|live)\b", status or ""))


def stalled(e, rows, today):
    """A waiting entry comes back up when its row has not shipped thirty days after the entry was
    marked waiting (the reconcile line's date, else its filing date)."""
    since = (e["reconcile"] or {}).get("date") or e["filed"]
    if not since or shipped(rows.get(e["waiting"] or "", "")):
        return False
    return date.fromisoformat(since) <= today - timedelta(days=30)


def queue(entries, rows=None, today=None):
    """The entries `todo now` shows, in order: § 1 open entries that aren't waiting (plus waiting ones
    whose row stalled), funnel-blocking first, then file order; an entry dated in the future last."""
    today = today or date.today()
    rows = rows or {}
    picked = []
    for idx, e in enumerate(entries):
        if e["done"] or e["section"] not in ("1", "1b"):
            continue
        if e["section"] == "1b" or e["waiting"]:
            if not stalled(e, rows, today):
                continue
        later = NOT_BEFORE.search(e["title"])
        later = later and date.fromisoformat(later.group(1)) > today
        funnel = bool(FUNNEL.search(e["title"] + " " + e["head"]))
        cls, why, _ = rule9(e)
        group = "decide" if why.startswith("judgment") else "setup"
        picked.append({"entry": e, "n": idx, "later": bool(later), "funnel": funnel, "group": group})
    picked.sort(key=lambda p: (p["later"], not p["funnel"], p["n"]))
    return picked


def now_lines(entries, *, numbers, replies=None, due=None, paused=None, day_sends=None, proposed=0,
              rows=None, today=None, max_lines=11, short=False):
    """The `todo now` message: under twelve lines, grouped. replies/due are ints or an error string
    ("couldn't read …"); paused is the pause's reason or None; day_sends a one-line pointer or None;
    numbers maps an entry's start line to its `todo ls` number."""
    q = queue(entries, rows, today)
    total = 0
    guessed = 0
    for p in q:
        m, g = minutes(p["entry"])
        p["min"], p["guess"] = m, g
        total += m
        guessed += g
    reply_min = replies * 3 if isinstance(replies, int) else 0
    head = (f"Yours now: {len(q)} on the list, about {fmt_minutes(total + reply_min)} in all"
            + (f" ({guessed} without an estimate, counted at {DEFAULT_MINUTES})" if guessed else "") + ".")
    if short:
        first = q[0] if q else None
        return [head + (f" First: {short_title(first['entry']['title'], 50)} (~{first['min']} min)." if first else "")
                + " `todo now` for the list."]
    fixed = []
    if isinstance(replies, int):
        fixed.append(f"Replies waiting on you: {replies}" + (f" — text `replies` · ~{fmt_minutes(reply_min)}"
                                                              if replies else " — nothing waiting"))
    else:
        fixed.append(f"Replies waiting on you: {replies or 'not read'}")
    if paused:
        held = f"; {due} follow-up{'s' if due != 1 else ''} held" if isinstance(due, int) and due else ""
        fixed.append(f"Send today: nothing — sends are paused ({paused}){held}")
    else:
        parts = []
        if day_sends:
            parts.append(day_sends)
        if isinstance(due, int) and due:
            parts.append(f"{due} follow-up{'s' if due != 1 else ''} due: `leads due` · ~{fmt_minutes(due * 2)}")
        elif isinstance(due, str):
            parts.append(f"follow-ups: {due}")
        fixed.append("Send today: " + ("; ".join(parts) if parts else "nothing due"))
    if proposed:
        fixed.append(f"Decide first: say \"reconcile: yes\" — {proposed} entries leave the list "
                     f"(`todo reconcile` shows why) · ~5 min")
    budget = max_lines - 1 - len(fixed) - 1           # header, fixed lines, the "more" line
    setup = [p for p in q if p["group"] == "setup"]
    decide = [p for p in q if p["group"] == "decide"]
    # both groups get room: two headers, then entries alternate by priority until the budget is spent
    n_setup = n_dec = 0
    room = budget - (1 if setup else 0) - (1 if decide else 0)
    while room > 0 and (n_setup < len(setup) or n_dec < len(decide)):
        if n_setup < len(setup) and (n_setup <= n_dec or n_dec >= len(decide)):
            n_setup += 1
        else:
            n_dec += 1
        room -= 1
    if setup and not n_setup:
        setup = []
    if decide and not n_dec:
        decide = []

    def line(p):
        e = p["entry"]
        n = numbers.get(e["start"], "?")
        mark = "~" + str(p["min"]) + ("?" if p["guess"] else "") + " min"
        later = f" (from {NOT_BEFORE.search(e['title']).group(1)[5:]})" if p["later"] else ""
        return f"  {n}. {short_title(e['title'])}{later} — {command_for(e, n)} · {mark}"

    out = [head]
    if setup:
        out.append("Setup that blocks the lane:" if setup[0]["funnel"] else "Setup:")
        out += [line(p) for p in setup[:n_setup]]
    out += fixed[:2]
    if decide or len(fixed) > 2:
        out.append("Decide:")
        out += [ln.replace("Decide first: ", "  ") for ln in fixed[2:]]
        out += [line(p) for p in decide[:n_dec]]
    shown = n_setup + n_dec
    rest = q[shown:] if False else [p for p in setup[n_setup:]] + [p for p in decide[n_dec:]]
    rest += [p for p in q if p not in setup and p not in decide]
    if rest:
        out.append(f"+ {len(rest)} more in § 1, about {fmt_minutes(sum(p['min'] for p in rest))}: `todo ls`")
    return out


# --- todo audit ---------------------------------------------------------------------

def done_trail(history_text):
    """Entries in every '## …done trail…' section of the history file, parsed like the live file's."""
    out, keep = [], []
    lines = history_text.split("\n")
    in_trail = False
    for l in lines:
        if l.startswith("## "):
            in_trail = "done trail" in l.lower()
        keep.append(l if in_trail or l.startswith("#") else "")
    for e in parse("\n".join(keep)):
        e["trail"] = True
        out.append(e)
    return out


def audit(entries, trail, today=None):
    """-> dict: per § 1 entry its Rule 9 class; per repeat key its counts; the proposals."""
    today = today or date.today()
    since = today - timedelta(days=30)
    rows = []
    for e in entries:
        if e["section"] not in ("1", "1b", "1c") or e["done"]:
            continue
        cls, why, hint = rule9(e)
        m, g = minutes(e)
        rows.append({"title": e["title"], "section": e["section"], "class": cls, "why": why,
                     "repeat_key": e["meta"].get("repeat_key") or hint or repeat_key(e),
                     "minutes": m, "guessed": g, "kept_manual": e["kept_manual"], "filed": e["filed"]})
    keys = {}
    for e in [x for x in entries if x["section"] in ("1", "1b", "1c")] + list(trail):
        cls, why, hint = rule9(e)
        k = e["meta"].get("repeat_key") or hint or repeat_key(e)
        m, _ = minutes(e)
        when = e.get("done_on") or e["filed"]
        rec = keys.setdefault(k, {"repeat_key": k, "occurrence_count": 0, "cumulative_minutes": 0,
                                  "minutes_30d": 0, "classes": set(), "kinds": set(), "kept_manual": None, "titles": [],
                                  "days_open": []})
        rec["occurrence_count"] += 1
        rec["cumulative_minutes"] += m
        if when and date.fromisoformat(when) >= since:
            rec["minutes_30d"] += m
        rec["classes"].add(cls)
        rec["kinds"].add(why.split(" ")[0] if cls == "human-only" else cls)
        rec["kept_manual"] = rec["kept_manual"] or e["kept_manual"]
        rec["titles"].append(short_title(e["title"], 50))
        if e.get("done_on") and e["filed"]:
            rec["days_open"].append((date.fromisoformat(e["done_on"]) - date.fromisoformat(e["filed"])).days)
    proposals, exceptions = [], []
    for k, rec in sorted(keys.items()):
        auto = "automatable" in rec["classes"]
        # graduation is for a recurring approval: a human-only step whose reason is a judgment
        human = "human-only" in rec["classes"] and not auto and "judgment" in rec["kinds"]
        hot = rec["minutes_30d"] >= 30
        if rec["occurrence_count"] < 2 and not (hot and auto):
            continue
        if auto and rec["kept_manual"]:
            exceptions.append({"repeat_key": k, "reason": rec["kept_manual"], **_counts(rec)})
            continue
        if auto:
            action = "queue" if rec["occurrence_count"] >= 3 or hot else "propose"
            why = (f"{rec['occurrence_count']} occurrences" if rec["occurrence_count"] >= 2 else "")
            why += ("; " if why and hot else "") + (f"{rec['minutes_30d']} min in 30 days" if hot else "")
            proposals.append({"repeat_key": k, "action": action, "why": why, **_counts(rec)})
        elif human:
            proposals.append({"repeat_key": k, "action": "graduate",
                              "why": f"{rec['occurrence_count']} occurrences of a human-only step: propose a trust "
                                     f"rule (as 'two weeks of go, then unprompted') so it stops coming back",
                              **_counts(rec)})
    for rec in keys.values():
        rec["classes"] = sorted(rec["classes"])
        rec["kinds"] = sorted(rec["kinds"])
    asked = sum(r["minutes"] for r in rows if r["section"] == "1")
    waits = sorted(d for rec in keys.values() for d in rec["days_open"])
    return {"entries": rows, "keys": sorted(keys.values(), key=lambda r: -r["cumulative_minutes"]),
            "proposals": proposals, "exceptions": exceptions,
            "measured": {"minutes_asked": asked,
                         "days_until_ticked_median": waits[len(waits) // 2] if waits else None,
                         "ticked_with_dates": len(waits)}}


def _counts(rec):
    return {"occurrence_count": rec["occurrence_count"], "cumulative_minutes": rec["cumulative_minutes"],
            "minutes_30d": rec["minutes_30d"], "titles": rec["titles"][:4]}


# --- todo reconcile ---------------------------------------------------------------------

def propose(e, rows=None):
    """-> {cls, reason, target, row}: one of the five classes for an entry in § 1 / 1b / 1c, with a
    one-line reason. A '_(reconcile …)_' line already in the entry is read as the proposal."""
    rows = rows or {}
    rec = e["reconcile"]
    if e["done"]:
        return {"cls": "DONE", "reason": "ticked; ticked entries leave § 1 within the week", "target": "trail"}
    if rec:
        t = rec["text"]
        mv = MOVE_TO.match(t) or (MOVE_TO.search(t) if t.startswith("→") else None)
        if mv:
            return {"cls": "MOVE", "reason": re.sub(r"^→\s*§\s*\S+\s*[—-]?\s*", "", t) or t, "target": mv.group(1)}
        word = re.match(r"(HUMAN_NOW|AUTOMATE|SUPERSEDED|WAITING_FOR_AUTOMATION|DONE|STALE)", t)
        if word:
            cls = word.group(1)
            reason = t[len(cls):].lstrip(" —:-·").strip() or t
            if cls == "WAITING_FOR_AUTOMATION":
                row = e["waiting"]
                if row and shipped(rows.get(row, "")):
                    return {"cls": "DONE", "reason": f"its row {row} shipped ({rows[row][:40]}); ticked by code",
                            "target": "trail"}
                return {"cls": cls, "reason": reason, "target": "1b", "row": row}
            return {"cls": cls, "reason": reason, "target": "1" if cls == "HUMAN_NOW" else "trail"}
    if e["section"] == "1c":
        return {"cls": "STALE", "reason": "in § 1c with no reason line; a reader decides", "target": "trail",
                "unsure": True}
    if e["waiting"]:
        row = e["waiting"]
        if shipped(rows.get(row, "")):
            return {"cls": "DONE", "reason": f"its row {row} shipped; ticked by code", "target": "trail"}
        return {"cls": "WAITING_FOR_AUTOMATION", "reason": f"waiting on {row}", "target": "1b", "row": row}
    cls, why, _ = rule9(e)
    if cls == "automatable" and e["kept_manual"]:
        return {"cls": "HUMAN_NOW", "reason": f"automatable, kept manual because: {e['kept_manual']}", "target": "1"}
    if cls == "automatable":
        rowm = ROW.search(e["automatable_note"] or "")
        return {"cls": "AUTOMATE", "reason": f"automatable: {why}", "target": "trail",
                "row": rowm.group(1) if rowm else None, "unsure": True}
    if cls == "unsure":
        return {"cls": "HUMAN_NOW", "reason": "unsure — kept until a reader says otherwise", "target": "1",
                "unsure": True}
    return {"cls": "HUMAN_NOW", "reason": f"human-only: {why}", "target": "1"}


def reconcile_plan(entries, rows=None):
    plan = []
    for e in entries:
        if e["section"] not in ("1", "1b", "1c"):
            continue
        p = propose(e, rows)
        p["entry"] = e
        plan.append(p)
    return plan


def hidden_line(e, p=None):
    cls, why, hint = rule9(e)
    m, g = minutes(e)
    hr = e["meta"].get("human_reason") or (why.split(" (")[0] if cls == "human-only" else
                                            "automatable" if cls == "automatable" else "unsure")
    parts = [f"repeat_key={e['meta'].get('repeat_key') or hint or repeat_key(e)}",
             f"human_reason={hr}", f"estimated_minutes={m}"]
    if p and p.get("row") and p["cls"] == "WAITING_FOR_AUTOMATION":
        parts.append(f"waiting={p['row']}")
    return "  <!-- todo: " + "; ".join(parts) + " -->"


def apply(todo_text, history_text, plan, *, today=None, who="todo reconcile", only=None):
    """-> (new todo text, new history text, moves). Moves the entries the plan sends elsewhere:
    to the done trail (a new HISTORY section, each move named, the block kept whole and ticked), to
    § 3 / § 4 where marked, waiting entries into § 1b, kept ones into § 1; an emptied § 1c is
    removed; every entry left in § 1 / 1b gets its hidden metadata line if it has none.
    `only`: a set of plan indexes (1-based) to apply, for a line-by-line answer."""
    today = today or date.today()
    lines = todo_text.split("\n")
    by_target, moves, remove, after = {}, [], set(), {}
    for i, p in enumerate(plan, 1):
        e = p["entry"]
        has_meta = any(HIDDEN.match(l) for l in e["lines"])
        moving = (only is None or i in only) and p["target"] != e["section"]
        if not moving:
            if e["section"] in ("1", "1b") and not has_meta:
                after[e["end"] - 1] = hidden_line(e, p)
            continue
        block = list(lines[e["start"]:e["end"]])
        if p["target"] in ("1", "1b") and not has_meta:
            block.append(hidden_line(e, p))
        remove.update(range(e["start"], e["end"]))
        by_target.setdefault(p["target"], []).append((p, block))
        moves.append({"n": i, "title": e["title"], "cls": p["cls"], "from": e["section"], "to": p["target"],
                      "reason": p["reason"]})
    new = []
    for idx, l in enumerate(lines):
        if idx in remove:
            continue
        new.append(l)
        if idx in after:
            new.append(after[idx])
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(new))
    for tgt, items in by_target.items():
        if tgt != "trail":
            text = _insert_into_section(text, tgt, ["\n".join(b) for _, b in items])
    text = _drop_empty_subsection(text, "1c")
    hist = _history_section(history_text, by_target.get("trail", []), moves, today, who) if moves else history_text
    return text, hist, moves


def _section_span(lines, sid):
    """(header line, next header line) of the section or sub-section whose id is sid."""
    start = None
    for i, l in enumerate(lines):
        h = HEADER.match(l)
        if not h:
            continue
        if start is not None:
            return start, i
        m = SEC_ID.match(h.group(2).strip())
        if m and m.group(1) == sid:
            start = i
    return (start, len(lines)) if start is not None else (None, None)


def _insert_into_section(text, sid, blocks):
    lines = text.split("\n")
    s, e = _section_span(lines, sid)
    if s is None:
        return text.rstrip("\n") + "\n\n" + "\n\n".join(blocks) + "\n"
    at = e
    while at > s + 1 and not lines[at - 1].strip():
        at -= 1
    ins = [""] + "\n\n".join(blocks).split("\n")
    lines[at:at] = ins
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


def _drop_empty_subsection(text, sid):
    lines = text.split("\n")
    s, e = _section_span(lines, sid)
    if s is None or any(ENTRY.match(l) for l in lines[s:e]):
        return text
    del lines[s:e]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


def _history_section(history_text, trail, moves, today, who):
    head = [f"## TAYLOR-TODO — the done trail (reconciled {today.isoformat()})", "",
            f"Applied by `{who}` on Taylor's \"reconcile: yes\" (plan 55 § 5.5, VISION § Rules 9). "
            f"Every move, one line each; the entries that left the file follow whole, ticked, under their class.", ""]
    for m in moves:
        dest = {"trail": "done trail", "1": "§ 1", "1b": "§ 1b"}.get(m["to"], f"§ {m['to']}")
        head.append(f"- {m['cls']} · § {m['from']} → {dest} · **{short_title(m['title'], 90)}** — {m['reason']}")
    for cls in ("DONE", "STALE", "SUPERSEDED", "AUTOMATE"):
        group = [(p, b) for p, b in trail if p["cls"] == cls]
        if not group:
            continue
        head += ["", f"### {cls} ({len(group)})", ""]
        for p, b in group:
            b = [b[0].replace("- [ ]", "- [x]", 1)] + b[1:]
            if not p["entry"]["reconcile"]:
                b.append(f"  _(reconcile {today.isoformat()}: {p['cls']} — {p['reason']})_")
            head += b + [""]
    block = re.sub(r"\n{3,}", "\n\n", "\n".join(head)).rstrip("\n") + "\n\n"
    m = re.search(r"^## TAYLOR-TODO — the done trail", history_text, re.M)
    if m:
        return history_text[:m.start()] + block + history_text[m.start():]
    return history_text.rstrip("\n") + "\n\n" + block
