"""Google Postmaster Tools, read by API (ROADMAP B136, plan 55 § 3.1, § 4, § 5.3).

The email lane's stop rule says a Postmaster spam rate at or above 0.1% on a sending domain stops the
lane (VISION § Decided, 2026-10-01 answer 2). Until this module that reading was typed in by hand
(`outreach postmaster 0.08`) and in practice never was. Now `outreach postmaster fetch` (a daily timer)
asks Google for the last few days of every outreach domain the venture names and appends each new
day to the same `postmaster.jsonl` the stop rule already reads.

    import postmaster
    rows, problem = postmaster.fetch(domain, start, end, get)      # get(name) -> env value or None
    postmaster.record(path, rows)                                    # appends the days not yet recorded
    postmaster.reputation(domain)                                    # the registry's `postmaster` source

Which API. Google moved Postmaster Tools to v2 in 2026: `domains.domainStats.query` (POST, metric
SPAM_RATE) replaced v1's `domains.trafficStats.list`, and v2 publishes no domain reputation at all
(Google retired the reputation dashboards). So by default (POSTMASTER_API=auto) the spam rate comes
from v2, and v1 is asked only when v2 refuses; a v1 answer carries `domainReputation`, which is kept
when it comes. POSTMASTER_API=v1 or v2 pins one. A reading with no reputation says so; it is never
guessed.

What Google sends back when it has nothing: an empty list. Postmaster publishes a day only when the
domain sent enough mail to Gmail users that day (a few hundred a day), so a quiet domain has no
readings, and that is not a zero. Such a day is a "no data" line in the fetch log, never a row in
postmaster.jsonl, so it can't hide an earlier high reading from the stop rule.

Credentials, by env name (read through the caller's `get`, never printed):
  POSTMASTER_CLIENT_ID / POSTMASTER_CLIENT_SECRET   an OAuth client of type "Desktop app"
  POSTMASTER_REFRESH_TOKEN    written by `outreach postmaster grant --code …` (the one consent)
  POSTMASTER_ACCESS_TOKEN     tests, or a token minted elsewhere; skips the refresh
  POSTMASTER_API_BASE / POSTMASTER_TOKEN_URL / POSTMASTER_AUTH_URL   tests only: stand-in hosts
The account that grants must have the domain verified (or be added as a user) in Postmaster Tools.

Rows in postmaster.jsonl (the shape `outreach` has read since B90; fields only ever added):
  {"ts", "domain", "rate"}                     a hand reading: rate is a percent
  + {"date", "source": "api", "api": "v2"|"v1", "spam_ratio", "reputation"}   an API reading:
    date is the day Google measured, rate = spam_ratio x 100, reputation HIGH|MEDIUM|LOW|BAD or null.

No product literal lives here (plan 55 § 5.12, tests/test_portable.py): domains come from the caller.
"""

import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API_BASE = "https://gmailpostmastertools.googleapis.com"
TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
# v2's query takes postmaster.traffic.readonly; v1's list takes postmaster.readonly. Both, so either works.
SCOPES = ("https://www.googleapis.com/auth/postmaster.traffic.readonly",
          "https://www.googleapis.com/auth/postmaster.readonly")
REDIRECT = "http://127.0.0.1:8765/"     # a Desktop client accepts any loopback; nothing needs to listen there
REPUTATIONS = ("HIGH", "MEDIUM", "LOW", "BAD")
LOOKBACK_DAYS = 4                        # Google publishes a day a day or two late; ask for a few
STALE_DAYS = 3                           # no reading for this long is a HEALTH line (B136)
CRED_NAMES = ("POSTMASTER_CLIENT_ID", "POSTMASTER_CLIENT_SECRET", "POSTMASTER_REFRESH_TOKEN")


class PostmasterError(Exception):
    """Google said no, or couldn't be reached. `.status` is the HTTP status when there was one."""

    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


# ---- where the readings live ------------------------------------------------------

def state_dir():
    """The same directory `outreach` keeps (OUTREACH_STATE), so the registry can call reputation() alone."""
    return Path(os.environ.get("OUTREACH_STATE") or Path.home() / ".local/state/claude-tools/outreach")


def default_path():
    return state_dir() / "postmaster.jsonl"


def fetch_log_path(path=None):
    return Path(path or default_path()).with_name("postmaster-fetch.jsonl")


def read_rows(path=None):
    p = Path(path or default_path())
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _append(path, row):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(row) + "\n")


# ---- credentials ----------------------------------------------------------------

def missing_credentials(get):
    """The env names still unset ([] when it can run). An access token alone is enough (tests)."""
    if get("POSTMASTER_ACCESS_TOKEN"):
        return []
    return [k for k in CRED_NAMES if not get(k)]


def _post_form(url, fields, timeout=30):
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    return _open(req, timeout)


def _open(req, timeout=30):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            msg = (json.loads(body).get("error") or {})
            msg = msg.get("message") if isinstance(msg, dict) else (json.loads(body).get("error_description") or msg)
        except (json.JSONDecodeError, AttributeError):
            msg = body[:200]
        raise PostmasterError(f"HTTP {e.code}: {msg}", e.code)
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise PostmasterError(f"couldn't reach {req.full_url.split('?')[0]} ({getattr(e, 'reason', e)})")
    try:
        return json.loads(raw or b"{}")
    except json.JSONDecodeError:
        raise PostmasterError(f"{req.full_url.split('?')[0]} didn't answer JSON")


def access_token(get):
    tok = get("POSTMASTER_ACCESS_TOKEN")
    if tok:
        return tok
    r = _post_form(get("POSTMASTER_TOKEN_URL") or TOKEN_URL, {
        "client_id": get("POSTMASTER_CLIENT_ID"), "client_secret": get("POSTMASTER_CLIENT_SECRET"),
        "refresh_token": get("POSTMASTER_REFRESH_TOKEN"), "grant_type": "refresh_token"})
    if not r.get("access_token"):
        raise PostmasterError("the token endpoint gave no access token")
    return r["access_token"]


def grant_url(get):
    """The consent link: Taylor opens it signed in as the account that sees the domain in Postmaster Tools."""
    q = {"client_id": get("POSTMASTER_CLIENT_ID"), "redirect_uri": REDIRECT, "response_type": "code",
         "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "consent"}
    return (get("POSTMASTER_AUTH_URL") or AUTH_URL) + "?" + urllib.parse.urlencode(q)


def code_from(text):
    """The `code` out of the address the browser landed on (or the bare code)."""
    text = (text or "").strip()
    if "code=" in text:
        return urllib.parse.parse_qs(urllib.parse.urlsplit(text).query).get("code", [""])[0]
    return text


def exchange_code(get, code):
    """The one-time code -> a refresh token (returned, never printed)."""
    r = _post_form(get("POSTMASTER_TOKEN_URL") or TOKEN_URL, {
        "client_id": get("POSTMASTER_CLIENT_ID"), "client_secret": get("POSTMASTER_CLIENT_SECRET"),
        "code": code_from(code), "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
    if not r.get("refresh_token"):
        raise PostmasterError("Google returned no refresh token (open the link again: it asks for consent anew)")
    return r["refresh_token"]


# ---- the two APIs, parsed ----------------------------------------------------------

def _date(d):
    return {"year": d.year, "month": d.month, "day": d.day}


def _value(v):
    v = v or {}
    for k in ("doubleValue", "floatValue", "intValue"):
        if v.get(k) is not None:
            return float(v[k])
    if v.get("stringValue") is not None:
        try:
            return float(v["stringValue"])
        except ValueError:
            return None
    return None


def parse_v2(resp, domain):
    """QueryDomainStatsResponse -> [{date, spam_ratio}] by day. SPAM_RATE is a ratio (0.001 = 0.1%)."""
    days = {}
    for s in (resp or {}).get("domainStats") or []:
        d = s.get("date") or {}
        if not d.get("year"):
            continue
        day = dt.date(int(d["year"]), int(d["month"]), int(d["day"])).isoformat()
        if s.get("metric") == "spam_rate":
            val = _value(s.get("value"))
            if val is not None:
                days.setdefault(day, {})["spam_ratio"] = val
    return [_row(domain, day, v.get("spam_ratio"), None, "v2") for day, v in sorted(days.items())
            if v.get("spam_ratio") is not None]


def parse_v1(resp, domain):
    """ListTrafficStatsResponse -> rows. `name` ends in /trafficStats/YYYYMMDD."""
    out = []
    for s in (resp or {}).get("trafficStats") or []:
        stamp = str(s.get("name") or "").rsplit("/", 1)[-1]
        try:
            day = dt.datetime.strptime(stamp, "%Y%m%d").date().isoformat()
        except ValueError:
            continue
        ratio = s.get("userReportedSpamRatio")
        rep = s.get("domainReputation")
        rep = rep if rep in REPUTATIONS else None
        if ratio is None and rep is None:
            continue
        out.append(_row(domain, day, None if ratio is None else float(ratio), rep, "v1"))
    return sorted(out, key=lambda r: r["date"])


def _row(domain, day, ratio, reputation, api):
    return {"domain": domain, "date": day, "spam_ratio": ratio,
            "rate": None if ratio is None else round(ratio * 100, 6),
            "reputation": reputation, "source": "api", "api": api}


def query_v2(domain, start, end, token, base):
    body = {"metricDefinitions": [{"name": "spam_rate", "baseMetric": {"standardMetric": "SPAM_RATE"}}],
            "timeQuery": {"dateRanges": {"dateRanges": [{"start": _date(start), "end": _date(end)}]}},
            "aggregationGranularity": "DAILY", "pageSize": 200}
    url = f"{base.rstrip('/')}/v2/domains/{urllib.parse.quote(domain)}/domainStats:query"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    return parse_v2(_open(req), domain)


def query_v1(domain, start, end, token, base):
    end_excl = end + dt.timedelta(days=1)          # v1's endDate is exclusive
    q = {"startDate.year": start.year, "startDate.month": start.month, "startDate.day": start.day,
         "endDate.year": end_excl.year, "endDate.month": end_excl.month, "endDate.day": end_excl.day,
         "pageSize": 200}
    url = f"{base.rstrip('/')}/v1/domains/{urllib.parse.quote(domain)}/trafficStats?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    return parse_v1(_open(req), domain)


def fetch(domain, start, end, get, token=None):
    """(rows, problem). rows: one per day Google measured, oldest first; [] with problem None means Google
    had no data for those days (a quiet domain). problem is a sentence when the call itself failed."""
    miss = missing_credentials(get)
    if miss:
        return [], "not set up: " + ", ".join(miss) + " unset (TAYLOR-TODO § 1 \"Postmaster Tools by API\")"
    base = get("POSTMASTER_API_BASE") or API_BASE
    which = (get("POSTMASTER_API") or "auto").lower()
    try:
        token = token or access_token(get)
    except PostmasterError as e:
        return [], f"couldn't get an access token: {e}"
    if which == "v1":
        try:
            return query_v1(domain, start, end, token, base), None
        except PostmasterError as e:
            return [], f"v1 trafficStats: {e}"
    try:
        return query_v2(domain, start, end, token, base), None
    except PostmasterError as e2:
        if which == "v2":
            return [], f"v2 domainStats: {e2}"
        try:
            return query_v1(domain, start, end, token, base), None
        except PostmasterError as e1:
            return [], f"v2 domainStats: {e2}; v1 trafficStats: {e1}"


# ---- recording and reading back ---------------------------------------------------

def record(path, rows, now_iso=None):
    """Append the rows whose (domain, date) isn't in the file yet. Returns the rows written."""
    path = Path(path or default_path())
    have = {(r.get("domain"), r.get("date")) for r in read_rows(path) if r.get("source") == "api"}
    stamp = now_iso or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    out = []
    for r in rows:
        if (r["domain"], r["date"]) in have:
            continue
        row = {"ts": stamp, **r}
        _append(path, row)
        have.add((r["domain"], r["date"]))
        out.append(row)
    return out


def log_fetch(path, domain, outcome, detail, now_iso=None):
    """One line a domain a fetch in postmaster-fetch.jsonl: ok | no data | failed | not set up."""
    _append(fetch_log_path(path), {"ts": now_iso or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                                   "domain": domain, "outcome": outcome, "detail": detail})


def last_fetch(domain, path=None):
    rows = [r for r in read_rows(fetch_log_path(path)) if r.get("domain") == domain]
    return rows[-1] if rows else None


def latest(domain, path=None):
    """The newest API reading for a domain (by the day Google measured), or None."""
    rows = [r for r in read_rows(path) if r.get("domain") == domain and r.get("source") == "api" and r.get("date")]
    return max(rows, key=lambda r: r["date"]) if rows else None


def on_day(domain, day, path=None):
    for r in read_rows(path):
        if r.get("domain") == domain and r.get("source") == "api" and r.get("date") == day:
            return r
    return None


def reputation(domain, path=None, today=None):
    """The registry's `postmaster` reputation source for one domain (plan 55 § 5.3, B141 calls this):

        {"source": "postmaster", "domain", "date": "YYYY-MM-DD" | None, "reputation": HIGH|MEDIUM|LOW|BAD|None,
         "spam_rate_pct": float | None, "age_days": int | None, "stale": bool, "last_fetch": {...} | None}

    date is the day Google measured; age_days counts from today; stale is True with no reading or one
    STALE_DAYS old or more. reputation is None when Google didn't publish one (v2 publishes none)."""
    today = today or dt.date.today()
    r = latest(domain, path)
    age = (today - dt.date.fromisoformat(r["date"])).days if r else None
    return {"source": "postmaster", "domain": domain, "date": r["date"] if r else None,
            "reputation": r.get("reputation") if r else None,
            "spam_rate_pct": (float(r["rate"]) if r and r.get("rate") is not None else None),
            "age_days": age, "stale": age is None or age >= STALE_DAYS, "last_fetch": last_fetch(domain, path)}


def describe(r):
    """'reputation HIGH, spam rate 0.02%' for a row; the missing parts said plainly."""
    rep = r.get("reputation") or "not published by Google"
    rate = _pct(float(r["rate"])) if r.get("rate") is not None else "not published"
    return f"reputation {rep}, spam rate {rate}"


def _pct(x):
    s = f"{x:.3f}".rstrip("0").rstrip(".")
    return f"{s if '.' in s else s + '.0'}%"


def stale_lines(domains, path=None, today=None, days=STALE_DAYS):
    """The HEALTH lines: one per domain without a reading for `days` or more, with the last fetch's reason."""
    out = []
    for d in domains:
        rep = reputation(d, path, today)
        if rep["age_days"] is not None and rep["age_days"] < days:
            continue
        lf = rep["last_fetch"]
        why = f"last fetch {str(lf.get('ts'))[:16]}: {lf.get('outcome')}" + (f" ({lf['detail']})" if lf.get("detail") else "") \
            if lf else "never fetched"
        when = f"since {rep['date']} ({rep['age_days']} days)" if rep["date"] else "ever"
        out.append(f"Postmaster: no reading for {d} {when}; {why}")
    return out

