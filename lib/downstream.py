"""Downstream capacity, measured (ROADMAP B145; plan 55 § 5.10; VISION § Decided "Autonomous acquisition" #8).

The worry it answers: the machine wins forty customers in a month and each one needs the owner's hands to set
up, so the owner has been automated into a worse job. The contract is **pressure before throttle**: when the
human queue has been over the owner's daily budget for three days, first touches hold (follow-ups, replies and
the close arm go on), the morning message names the repeat keys taking the minutes and the row that would
remove each, and the hold lifts by itself when the same window comes back under budget. Nothing to switch off.

    import downstream
    downstream.record_day(path, day, total, by_key, rows, onboarding)   # `todo now` writes today's number
    d = downstream.measure(downstream.read_days(path), today)          # rule 7's input, pure
    d["hold"], d["why"], d["top_keys"], d["over_budget_days"], d["minutes_by_day"]
    downstream.capacity()                                               # the same, from the state file in env

**The window.** The last three days `todo now` ran, looked for within the last LOOKBACK calendar days (so a
weekend without a morning message neither breaks a hold nor starts one). A day with no run is unknown, never
zero; fewer than three known days is not a hold. A hold needs all three over the budget; one day back under it
lifts the hold.

**The budget** is TODO_DAILY_MINUTES (default 45, the owner's daily lane), the owner's and not a venture's: the
queue is one person's whatever the ventures are. Nothing here names a business (plan 55 § 5.12).

**The keys.** Each day's record keeps the minutes by repeat key (lib/todo_queue.py's `repeat_key`, the same
keys `todo audit` counts), and the row that would remove each key as the todo file says it that day (an entry
waiting on a row, or an `automatable:` note naming one) or `todo audit`'s proposal for it. The top three over
the window are what the morning message names.
"""

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path

BUDGET_ENV = "TODO_DAILY_MINUTES"
DEFAULT_BUDGET = 45
WINDOW = 3
LOOKBACK = 7
KEEP_DAYS = 60
NO_ROW = "no row yet: `todo audit` proposes one on Sunday"
ROW = re.compile(r"\b(B\d{2,3})\b")
# An onboarding step: a client being set up by hand. The hidden line's `onboarding=yes` says it outright;
# otherwise the title or first line names it. Counted for the message; the hold is decided by minutes alone.
ONBOARDING = re.compile(r"\bonboard\w*|\bwalk-?through\b|\bnew client\b|\bclient'?s (?:site|domain|setup|account|"
                        r"listing|google|stripe)\b|\bset(?:ting)? up (?:a|the|their) client\b", re.I)


def budget(env=None):
    v = (env if env is not None else os.environ).get(BUDGET_ENV, "")
    return int(v) if str(v).strip().isdigit() and int(v) > 0 else DEFAULT_BUDGET


def state_path(env=None):
    env = env if env is not None else os.environ
    base = Path(env.get("TODO_STATE_DIR") or "~/.local/state/claude-tools/todo").expanduser()
    return base / "minutes.json"


def read_days(path=None):
    """{iso date: {total, by_key, rows, onboarding}} from the state file; {} when it is missing or unreadable."""
    try:
        data = json.loads(Path(path or state_path()).read_text())
    except (OSError, ValueError):
        return {}
    days = data.get("days") if isinstance(data, dict) else None
    return days if isinstance(days, dict) else {}


def record_day(path, day, total, by_key, rows=None, onboarding=0):
    """Write one day's numbers (the latest `todo now` of the day wins), keeping KEEP_DAYS days. Never raises:
    a state file that can't be written costs a measurement, not the morning message."""
    path = Path(path)
    days = read_days(path)
    days[day.isoformat()] = {"total": int(total), "by_key": {k: int(v) for k, v in by_key.items()},
                             "rows": dict(rows or {}), "onboarding": int(onboarding)}
    cut = (day - timedelta(days=KEEP_DAYS)).isoformat()
    days = {d: v for d, v in sorted(days.items()) if d >= cut}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"days": days}, indent=1, sort_keys=True))
        tmp.replace(path)
    except OSError:
        return False
    return True


def window(days, today):
    """The last WINDOW days with a record, newest last, within LOOKBACK calendar days ending today."""
    lo = (today - timedelta(days=LOOKBACK - 1)).isoformat()
    known = [d for d in sorted(days) if lo <= d <= today.isoformat() and isinstance(days[d], dict)
             and isinstance(days[d].get("total"), int)]
    return known[-WINDOW:]


def measure(days, today=None, budget_min=None):
    """-> rule 7's input: {budget, window, minutes_by_day, over_budget_days, known_days, hold, why, lifts,
    onboarding_steps_open, top_keys: [{repeat_key, minutes, row, proposal}]}. Pure."""
    today = today or date.today()
    b = budget_min or budget()
    win = window(days, today)
    by_day = {d: days[d]["total"] for d in win}
    over = [d for d in win if by_day[d] > b]
    hold = len(win) == WINDOW and len(over) == WINDOW
    sums, rows = {}, {}
    for d in win:
        for k, m in (days[d].get("by_key") or {}).items():
            sums[k] = sums.get(k, 0) + int(m)
        for k, r in (days[d].get("rows") or {}).items():
            if r:
                rows[k] = r                                   # the newest day's word on a key wins
    top = []
    for k, m in sorted(sums.items(), key=lambda km: (-km[1], km[0]))[:3]:
        r = rows.get(k) or ""
        row = ROW.fullmatch(r.strip()).group(1) if ROW.fullmatch(r.strip()) else None
        top.append({"repeat_key": k, "minutes": m, "row": row, "proposal": None if row else (r or NO_ROW)})
    onboarding = days[win[-1]].get("onboarding", 0) if win else 0
    d = {"budget": b, "window": win, "minutes_by_day": by_day, "over_budget_days": len(over),
         "known_days": len(win), "hold": hold, "why": None, "lifts": None, "onboarding_steps_open": onboarding,
         "top_keys": top}
    if hold:
        lead = top[0] if top else None
        d["why"] = (f"the human queue has been over the {b}-min daily budget for {WINDOW} days ("
                    + ", ".join(str(by_day[x]) for x in win) + " min)"
                    + (f"; the most minutes are {lead['repeat_key']} ({lead['minutes']} min, "
                       + (f"{lead['row']} would remove it" if lead["row"] else lead["proposal"]) + ")" if lead else ""))
        d["lifts"] = f"when one day of the last {WINDOW} is back at {b} min or under"
    return d


def capacity(path=None, today=None, env=None):
    """measure() over the state file `todo now` keeps: what `leads prospects route` passes as capacity['downstream']."""
    return measure(read_days(path or state_path(env)), today, budget(env))


def row_for(entries, key, audit_proposals=None, rk=None):
    """The row that would remove a repeat key, as the todo file says it: an open entry with that key waiting on
    a row, or naming one in its `automatable:` note; else `todo audit`'s proposal text for the key; else ''."""
    for e in entries:
        if e.get("done") or (rk(e) if rk else e.get("repeat_key")) != key:
            continue
        if e.get("waiting"):
            return e["waiting"]
        m = ROW.search(e.get("automatable_note") or "")
        if m:
            return m.group(1)
    for p in audit_proposals or ():
        if p.get("repeat_key") == key:
            verb = {"propose": "`todo audit` proposes a row", "queue": "`todo audit` queues a row",
                    "graduate": "`todo audit` proposes a trust rule"}.get(p.get("action"), "`todo audit` proposes a row")
            return f"no row yet: {verb} ({p.get('why') or 'recurring'})"
    return ""


def is_onboarding(e):
    meta = e.get("meta") or {}
    if str(meta.get("onboarding", "")).lower() in ("yes", "true", "1"):
        return True
    return bool(ONBOARDING.search((e.get("title") or "") + " " + (e.get("head") or "")))


def message_lines(d, short=False):
    """The morning message's lines for downstream capacity: [] under budget, one warning line when two of the
    last three days were over (the day before a hold), three when the hold is on (the hold, the top keys with their rows, the word to say)."""
    if not d or not d.get("known_days"):
        return []
    b, n, win = d["budget"], d["over_budget_days"], d["window"]
    mins = ", ".join(str(d["minutes_by_day"][x]) for x in win)
    if not d["hold"]:
        if n < WINDOW - 1 or short:       # the warning comes the day before a hold would start
            return []
        return [f"Downstream: over your {b}-min budget {n} of the last {len(win)} days ({mins} min); "
                "first touches hold when it is three days running."]
    tops = d["top_keys"]
    onb = d.get("onboarding_steps_open") or 0
    if short:
        lead = tops[0] if tops else None
        return [f"First touches hold: over {b} min {WINDOW} days running"
                + (f"; most minutes: {lead['repeat_key']} ({lead['row'] or 'no row yet'})" if lead else "") + "."]
    out = [f"Downstream hold: over your {b}-min budget {WINDOW} days running ({mins} min) — first touches "
           f"hold; follow-ups, replies and the close go on"
           + (f"; {onb} onboarding step{'s' if onb != 1 else ''} open" if onb else "") + "."]
    if tops:
        said, parts = False, []
        for t in tops:                    # the no-row sentence once; the keys after it just say "no row yet"
            what = t["row"] or t["proposal"]
            if what == NO_ROW:
                what, said = (NO_ROW if not said else "no row yet"), True
            parts.append(f"{t['repeat_key']} {t['minutes']} min → {what}")
        out.append("  Most minutes: " + "; ".join(parts))
    rows = [t["row"] for t in tops if t["row"]]
    out.append(("  Say `pull " + rows[0] + " forward` to build it next" if rows else
                "  Name the key to build next (`todo audit --sunday` proposes its row)")
               + f"; the hold lifts {d['lifts'] or 'when a day is back under budget'}.")
    return out
