"""What the three CLIs decide today, business by business, for the policy's no-drift test (ROADMAP B140).

`build_world(tmp)` makes one hermetic world: the made-up census of tests/test_propositions.py (the services
fixture, sixteen plumbers and roofers, seventeen more for the propositions: fifty-six businesses) and a few
lines of history laid over it (a won lead, a lost one, an interested email reply, a text in, a suppressed
place, an address already written to, a bounce, a batch hold, a strong lead with a confirmed page).
`capture(world)` runs the CLIs in it as they run today and reads back what each one did with each business:

    leads batch --city any --category any --n 50 --json --no-save            (the faulted rule)
    leads batch --proposition P3|P4|P5|P6 ... --json --no-save               (B135)
    outreach send --batch FILE --dry-run                                     (the screen: planned or skipped, why)
    leads kit --remote --segment S --census-only --n 60 --json --no-save    (Taylor's DMs and calls; each segment)
    prep pick --json --n 12   (PREP_RESERVE=60, so the cap never decides)    (the overnight previews, Taylor's)
    leads pipeline --all                                                     (the stage a conversation is at)
    outreach's close_arm_for(place_id)                                       (B137's deal, for an interested reply)

and folds them into one lane a business: `email` (a batch picked it and the screen planned it), `taylor` (a kit
or prep picked it), `conversation` (a reply is open in the pipeline), else `nothing`.

    python3 tests/policy_capture.py --write     # rewrite tests/fixtures/policy/today.json

tests/test_policy.py compares `route()` against that file, and this capture against the file, so a CLI that
changes what it decides fails the test as surely as a policy that drifts. Nothing reaches the network.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads

import datetime as dt  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import sqlite3  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from importlib.machinery import SourceFileLoader  # noqa: E402
from pathlib import Path  # noqa: E402

import test_leads_batch as tlb  # noqa: E402
import test_leads_preview as tp  # noqa: E402
import test_propositions as tpr  # noqa: E402

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
LEADS, OUTREACH, PREP = TOOLS / "bin" / "leads", TOOLS / "bin" / "outreach", TOOLS / "bin" / "prep"
GOLDEN = HERE / "fixtures" / "policy" / "today.json"
EMAIL_PROPS = ("P3", "P4", "P5", "P6")        # the slot propositions; the faulted rule is the plain batch
TODAY = dt.date.today()


def _day(n):
    return (TODAY - dt.timedelta(days=n)).isoformat()


def _event(pid, name, outcome, stage, days_ago, **kw):
    d = _day(days_ago)
    return {"ts": f"{d}T10:00:00-06:00", "date": d, "key": f"place:{pid}", "place_id": pid, "name": name,
            "outcome": outcome, "stage": stage, **kw}


# The history laid over the census, in the shape `leads log` and `outreach inbox` write it. Each line says why.
PIPELINE = [
    _event("FX_B09", "Iron Plumbing", "messaged", "contacted", 8, channel="email", next=_day(4)),   # held: messaged
    _event("FX_S06", "Summit Plumbing & Drain", "won", "won", 3, next=None),                # a client now
    _event("FX_C07", "Lens & Light Studio", "lost", "lost", 4, next=None),                  # said no on a call
    _event("FX_P501", "Pine 1 Plumbing", "messaged", "contacted", 6, channel="email", next=_day(2)),
    _event("FX_P501", "Pine 1 Plumbing", "interested", "interested", 1, note="replied to the email: yes, call me",
           next=_day(-1), source="email"),                                                  # an open reply: rule 6
    _event("FX_S11", "Canyon Air HVAC", "inbound", "interested", 0, note="texted the demo line", next=_day(-1),
           source="inbound", via="text"),                                                   # a text in: the consent machine
    {"ts": f"{_day(2)}T09:00:00-06:00", "date": _day(2), "key": "place:FX_C01", "place_id": "FX_C01",
     "name": "Photography by Jenna", "outcome": "strength", "kind": "strength", "strength": "strong",
     "reasons": ["taylor"], "by": "hand", "note": "met her at the expo"},                   # strong, and her page is hers
]
SUPPRESS = [{"value": "juniperplumbing.example", "kind": "domain", "reason": "replied no thanks"},
            {"value": "FX_P502", "kind": "place", "reason": "replied no thanks"},
            {"value": "office@pine4plumbing.example", "kind": "email", "reason": "bounced"}]   # outreach inbox's bounce
SENT = [{"date": _day(5), "touch": 0, "template": "p5-first", "place_id": "FX_P503", "name": "Pine 3 Plumbing",
         "email": "office@pine3plumbing.example", "provider": "fake", "mailbox": "a@trybox.example",
         "proposition": "P5", "variant": "intro", "batch_id": "old-0"}]
BOUNCES = [{"ts": f"{_day(2)}T10:00:00+00:00", "email": "office@pine4plumbing.example", "mailbox": "a@trybox.example"}]
BATCHED = [{"ts": f"{_day(10)}T09:00:00-06:00", "for": _day(10), "batch_id": "old-1", "place_ids": ["FX_P505"],
            "emails": ["office@pine5plumbing.example"], "mode": "batch"}]
# A strong lead with a confirmed page: its own Facebook page is its listed link, so the reach has evidence
REACH = {"FX_S01": {"facebook": "https://www.facebook.com/mikespoolcare"}}


def build_world(tmp):
    """-> {"env": {...}, "t": Path, "db": Path}. Everything under tmp."""
    t = Path(tmp)
    db = tpr.build_census(t / "census.db")
    conn = sqlite3.connect(db)
    conn.execute("UPDATE place_cache SET reviews = 120, rating = 4.9 WHERE place_id = 'FX_S01'")   # strong
    conn.commit()
    conn.close()
    (t / "prices.md").write_text(tpr.PRICES_MD)
    pages = json.loads(tlb.page_fixture(t / "pages.json").read_text())
    for pid, name, *rest in tpr.EXTRA:
        if rest[4]:
            pages[f"https://{rest[4].split('@')[1]}/"] = f"<footer>&copy; {tlb.YEAR} {name}</footer>"
    (t / "pages.json").write_text(json.dumps(pages))
    (t / "bin").mkdir()
    for name, body in (("site", tp.FAKE_SITE), ("client", tp.FAKE_CLIENT), ("img", tp.FAKE_IMG)):
        (t / "bin" / name).write_text(body)
        (t / "bin" / name).chmod(0o755)
    (t / "clients" / "kestrel").mkdir(parents=True)
    (t / "clients" / "kestrel" / "NOTES.md").write_text("Owner: Kay (owner@kestrelplumbing.example).\n")
    (t / "pipeline.jsonl").write_text("".join(json.dumps(e) + "\n" for e in PIPELINE))
    ostate = t / "outreach"
    ostate.mkdir()
    (ostate / "suppress.jsonl").write_text("".join(json.dumps(dict(s, ts=f"{_day(9)}T00:00:00+00:00")) + "\n"
                                                   for s in SUPPRESS))
    (ostate / "sends.jsonl").write_text("".join(json.dumps(s) + "\n" for s in SENT))
    (ostate / "bounces.jsonl").write_text("".join(json.dumps(b) + "\n" for b in BOUNCES))
    lstate = t / "leads"
    lstate.mkdir()
    (lstate / "batches.jsonl").write_text("".join(json.dumps(b) + "\n" for b in BATCHED))
    tpl = t / "tpl"
    shutil.copytree(TOOLS / "templates" / "outreach", tpl)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(t / "home"), "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8", "CLAUDE_TOOLS_ENV": str(t / "no-env"), "VENTURE": "patchlamp",
        "LEADS_DB": str(db), "LEADS_STATE": str(lstate), "LEADS_LEDGER": str(t / "ledger.jsonl"),
        "LEADS_PIPELINE": str(t / "pipeline.jsonl"), "LEADS_GROUPS_LOG": str(t / "groups.md"),
        "LEADS_PREVIEWS": str(t / "previews"), "LEADS_PREVIEW_HOST": "previews.example",
        "LEADS_PREVIEW_BIN": str(t / "bin"), "LEADS_IMG_BIN": str(t / "bin" / "img"),
        "FAKE_SITE_LOG": str(t / "site.jsonl"), "FAKE_IMG_LOG": str(t / "img.jsonl"),
        "GOOGLE_MAPS_API_KEY": "", "LEADS_MAIL_ADDRESS": "PO Box 1, Springfield, UT 84003",
        "LEADS_SEGMENT": "services", "PROJECTS_DIR": str(t / "projects"), "LEADS_CLIENTS_DIR": str(t / "clients"),
        "LEADS_OUTREACH_BIN": str(OUTREACH), "OUTREACH_STATE": str(ostate),
        "LEADS_PAGE_FIXTURE": str(t / "pages.json"), "LEADS_VENDOR_PRICES": str(t / "prices.md"),
        "LEADS_KIT_PREVIEWS": "", "LEADS_REACH_PY": str(t / "no-reach.py"),
        "OUTREACH_TEMPLATES": str(tpl), "OUTREACH_LEDGER": str(t / "o-ledger.jsonl"),
        "OUTREACH_LEADS_BIN": "/bin/false", "OUTREACH_NOTIFY_BIN": "/bin/true", "OUTREACH_PROVIDER": "fake",
        "PATCHLAMP_VOICE_NUMBER": "801-555-0100", "TAYLOR_TODO": str(t / "TODO.md"),
        "PREP_STATE": str(t / "prep"), "PREP_LEADS_BIN": str(LEADS), "PREP_RESERVE": "60",
        "PROSPECTS_DB": str(t / "prospects.db"), "ASSETS_DB": str(t / "assets.db"),
        "CONSENT_DB": str(t / "consent.db"),
        **{k: os.environ[k] for k in os.environ
           if k.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy", "claude_tools_offline_proxy")},
    }
    (t / "home").mkdir()
    return {"env": env, "t": t, "db": db}


def run(world, tool, *args, ok=(0,), stdin=None):
    r = subprocess.run([sys.executable, str(tool), *args], capture_output=True, text=True, env=world["env"],
                       timeout=300, input=stdin)
    if r.returncode not in ok:
        raise AssertionError(f"{tool.name} {' '.join(args)} exited {r.returncode}:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return r


def census_ids(db):
    conn = sqlite3.connect(db)
    try:
        return sorted(r[0] for r in conn.execute("SELECT place_id FROM businesses"))
    finally:
        conn.close()


def screen(world, batch):
    """{place_id: "plan" | the skip reason} from `outreach send --batch --dry-run`."""
    f = world["t"] / f"batch-{batch['batch_id']}.json"
    f.write_text(json.dumps(batch))
    out = run(world, OUTREACH, "send", "--batch", str(f), "--dry-run").stdout
    by_index = {i: p["place_id"] for i, p in enumerate(batch["picks"], 1)}
    got = {}
    for m in re.finditer(r"^(\d+)\. .+? <[^>]+> — \"", out, re.M):
        got[by_index[int(m.group(1))]] = "plan"
    for m in re.finditer(r"^  (\d+)\. .+ — skipped: (.+)$", out, re.M):
        got[by_index[int(m.group(1))]] = m.group(2).strip()
    return got


def outreach_module(world):
    saved = dict(os.environ)
    os.environ.update(world["env"])
    try:
        spec = importlib.util.spec_from_loader("outreach_for_policy", SourceFileLoader("outreach_for_policy",
                                                                                      str(OUTREACH)))
        m = importlib.util.module_from_spec(spec)
        argv, sys.argv = sys.argv, [str(OUTREACH)]
        try:
            spec.loader.exec_module(m)
        finally:
            sys.argv = argv
    finally:
        os.environ.clear()
        os.environ.update(saved)
    return m


def capture(world):
    """{place_id: {batch, screen, kit, prep, stage, arm, lane}} — what the CLIs decide today."""
    ids = census_ids(world["db"])
    out = {pid: {"batch": None, "screen": None, "kit": False, "prep": False, "stage": None, "arm": None}
           for pid in ids}
    common = ("--segment", "services", "--city", "any", "--category", "any", "--n", "50", "--json", "--no-save")
    for prop in (None,) + EMAIL_PROPS:
        r = run(world, LEADS, "batch", *common, *(("--proposition", prop) if prop else ()), ok=(0, 1))
        if r.returncode:
            continue                                                 # "no business … is left": nobody in it
        b = json.loads(r.stdout)
        for p in b["picks"]:
            out[p["place_id"]]["batch"] = p.get("proposition") or "P1"
        for pid, verdict in screen(world, b).items():
            out[pid]["screen"] = verdict
    for seg in ("services", "creatives", "retail", "nonprofit"):
        r = run(world, LEADS, "kit", "--remote", "--segment", seg, "--census-only", "--n", "60", "--json",
                "--no-save", ok=(0, 1))
        if r.returncode == 0:
            for p in json.loads(r.stdout)["picks"]:
                out[p["place_id"]]["kit"] = True
    r = run(world, PREP, "pick", "--json", "--n", "12")
    for p in json.loads(r.stdout)["picks"]:
        out[p["place_id"]]["prep"] = True
    text = run(world, LEADS, "pipeline", "--all").stdout
    stage = None
    names = {}
    conn = sqlite3.connect(world["db"])
    for pid, name in conn.execute("SELECT place_id, name FROM place_cache"):
        names[name] = pid
    conn.close()
    for line in text.splitlines():
        m = re.match(r"^(\w[\w ]*): \d+$", line)
        if m:
            stage = m.group(1)
            continue
        m = re.match(r"^  (.+?)(?: \(.+?\))?(?: [·—-] .*)?$", line)
        if m and stage:
            for name, pid in names.items():
                if m.group(1).startswith(name):
                    out[pid]["stage"] = stage
    o = outreach_module(world)
    for pid, row in out.items():
        if row["stage"] == "interested":
            row["arm"] = o.close_arm_for(pid)
        row["lane"] = lane_of(row)
    return out


CONVERSATION_STAGES = ("interested", "negotiating")      # a reply or a text is open (leads OUTCOMES)


def lane_of(row):
    """The one lane the CLIs give a business today."""
    if row["stage"] in CONVERSATION_STAGES:
        return "conversation"
    if row["batch"] and row["screen"] == "plan":
        return "email"
    if row["kit"] or row["prep"]:
        return "taylor"
    return "nothing"


def main():
    write = "--write" in sys.argv
    with tempfile.TemporaryDirectory() as tmp:
        got = capture(build_world(tmp))
    text = json.dumps(got, indent=1, sort_keys=True) + "\n"
    if write:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(text)
        print(f"wrote {GOLDEN} ({len(got)} businesses)", file=sys.stderr)
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
