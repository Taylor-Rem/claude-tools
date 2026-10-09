"""The outreach deck's pieces (ROADMAP B152, plan ~/projects/plans/59-outreach-deck.md): the drafts file, the
day file's picked six, the channel links, and the page. `leads deck` gathers the leads; this module only
parses and renders, so it names no business (tests/test_portable.py) and needs nothing outside the stdlib.

The drafts file, `private-docs/leads/drafts/<slug>.md`, one a lead (written by Flint or Steel by hand):

    ---
    name: Halo Venue
    key: place:ChIJ...            (optional: the pipeline key; wins over the file name)
    channel: facebook             (facebook | instagram | text | call | email)
    send: 2026-10-13              (optional: the day it should go)
    when: Tuesday 13 Oct          (optional: the chip; defaults to the send date written out)
    why: Steel: a time, not a question.
    log: log Halo Venue messaged "offered two evenings" --channel facebook
    hold: (optional) keeps it off the deck; the footer gives this line as why
    written: 2026-10-09T10:40     (optional: when Steel wrote it; defaults to the file's mtime)
    ---
    The message, as plain paragraphs, exactly as it is to be sent.

`<slug>` is `slugify(name + " " + city)` — the preview slug's shape (`halo-venue-orem`); `leads deck --slugs`
prints each due lead's. The deck carries the body as written: nothing here shortens, fixes or re-drafts it.
"""

import datetime as dt
import html
import json
import re
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "deck" / "deck.html"
DRAFT_FIELDS = ("name", "key", "channel", "send", "when", "why", "log", "hold", "written")
CHANNEL_LABEL = {"instagram": "Instagram", "facebook": "Facebook", "text": "Text", "call": "Phone",
                 "email": "Email", "form": "Form"}
URL_RE = re.compile(r"https?://\S+|\b[a-z0-9-]+(?:\.[a-z0-9-]+)+/[^\s]*", re.I)


class DraftError(ValueError):
    pass


def parse_draft(text):
    """(fields, body) from a drafts file. Unknown header keys are an error naming the key, so a typo
    ('chanel:') is said, not silently dropped. No front matter at all: the whole file is the body."""
    lines = text.replace("\r\n", "\n").split("\n")
    fields = {}
    if lines and lines[0].strip() == "---":
        try:
            end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
        except StopIteration:
            raise DraftError("the front matter opens with --- and never closes")
        for raw in lines[1:end]:
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            k, sep, v = raw.partition(":")
            k = k.strip().lower()
            if not sep or k not in DRAFT_FIELDS:
                raise DraftError(f"unknown header line {raw.strip()!r} (fields: {', '.join(DRAFT_FIELDS)})")
            fields[k] = v.strip()
        lines = lines[end + 1:]
    body = "\n".join(lines).strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    if fields.get("send"):
        try:
            dt.date.fromisoformat(fields["send"])
        except ValueError:
            raise DraftError(f"send: is YYYY-MM-DD, not {fields['send']!r}")
    if fields.get("channel"):
        fields["channel"] = fields["channel"].lower()
        if fields["channel"] not in CHANNEL_LABEL:
            raise DraftError(f"channel: is one of {', '.join(CHANNEL_LABEL)}, not {fields['channel']!r}")
    return fields, body


def written_at(fields, path):
    """When the draft was written, as an aware-or-naive ISO string comparable to a pipeline `ts`'s first 16
    characters: the `written:` field, else the file's mtime (local time)."""
    w = (fields.get("written") or "").strip()
    if w:
        return w.replace(" ", "T")[:16]
    return dt.datetime.fromtimestamp(Path(path).stat().st_mtime).isoformat(timespec="minutes")[:16]


def load_drafts(folder):
    """[{slug, path, fields, body, written, error}] for every *.md in the folder but README.md."""
    out = []
    folder = Path(folder)
    for p in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        if p.name.lower() == "readme.md":
            continue
        rec = {"slug": p.stem, "path": str(p), "fields": {}, "body": "", "written": None, "error": None}
        try:
            rec["fields"], rec["body"] = parse_draft(p.read_text())
            rec["written"] = written_at(rec["fields"], p)
            if not rec["body"] and not rec["fields"].get("hold"):
                rec["error"] = "no message under the header"
        except (OSError, DraftError) as e:
            rec["error"] = str(e)
        out.append(rec)
    return out


# ---- the day file's six (days/<date>.md § The six, after B133's passes) --------------------------------

SIX_HEAD = re.compile(r"^##\s+The six\b.*$", re.M)
PICK_HEAD = re.compile(r"^\*\*(D\d+)\s*·\s*(.+?)\*\*(.*)$")
RECEIPT = re.compile(r"^_Receipt:\s*(.*?)_\s*$")


def parse_six(markdown):
    """{'picks': [{id, name, line, message, receipt, instagram, facebook, phone, preview}], 'message_two': str|None}
    from a day file's `## The six` section: each pick is a `**D1 · Name** · reach · preview URL` line, the picked
    text as the paragraph(s) under it, and its `_Receipt: …_` line. Nothing found: no picks."""
    m = SIX_HEAD.search(markdown or "")
    if not m:
        return {"picks": [], "message_two": None}
    rest = markdown[m.end():]
    nxt = re.search(r"^##\s", rest, re.M)
    block = rest[:nxt.start()] if nxt else rest
    picks, cur, two, in_two = [], None, [], False
    for line in block.split("\n"):
        s = line.strip()
        if s.startswith("**Message two"):
            in_two, cur = True, None
            continue
        h = PICK_HEAD.match(s)
        if h:
            in_two = False
            cur = {"id": h.group(1), "name": h.group(2).strip(), "line": h.group(3).strip(" ·"), "body": [],
                   "receipt": None}
            picks.append(cur)
            continue
        if in_two:
            two.append(line)
            continue
        if cur is None:
            continue
        r = RECEIPT.match(s)
        if r:
            cur["receipt"] = r.group(1).strip()
            continue
        cur["body"].append(line)
    for p in picks:
        p["message"] = re.sub(r"\n{3,}", "\n\n", "\n".join(p.pop("body")).strip()) or None
        p.update(reach_from_line(p["line"]))
    two_text = re.sub(r"\n{3,}", "\n\n", "\n".join(two).strip()) or None
    return {"picks": picks, "message_two": two_text}


def reach_from_line(line):
    """The handles a pick's header line names: Instagram @x, a facebook.com page, a phone, the preview URL."""
    out = {"instagram": None, "facebook": None, "phone": None, "preview": None}
    m = re.search(r"Instagram\s+@([A-Za-z0-9_.]+)", line or "")
    if m:
        out["instagram"] = m.group(1).rstrip(".")
    m = re.search(r"(?:https?://)?(?:www\.)?(facebook\.com/[^\s·]+)", line or "")
    if m:
        out["facebook"] = m.group(1)
    m = re.search(r"\(?\d{3}\)?[ .-]?\d{3}-\d{4}", line or "")
    if m:
        out["phone"] = m.group(0)
    m = re.search(r"preview\s+(https?://\S+)", line or "")
    if m:
        out["preview"] = m.group(1)
    return out


# ---- the channel links ------------------------------------------------------------------------------------

def fb_target(page):
    """What m.me takes for a Facebook page: the numeric id of facebook.com/p/Name-123 or profile.php?id=123,
    else the vanity name. None for nothing usable."""
    p = re.sub(r"^(?:https?://)?(?:www\.|m\.)?facebook\.com/", "", (page or "").strip()).strip("/")
    if not p:
        return None
    m = re.search(r"[?&]id=(\d+)", p)
    if m:
        return m.group(1)
    if p.startswith("p/"):
        m = re.search(r"(\d{6,})$", p.split("?")[0])
        return m.group(1) if m else None
    first = p.split("?")[0].split("/")[0]
    return first or None


def tel_href(phone, scheme="tel"):
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = "1" + digits
    return f"{scheme}:+{digits}" if digits else None


def links(channel, instagram=None, facebook=None, phone=None, email=None):
    """{'open': {href, label} | None, 'page': {href, label} | None, 'phone': shown number | None} for a card."""
    out = {"open": None, "page": None, "phone": None}
    if channel == "instagram" and instagram:
        out["open"] = {"href": f"https://ig.me/m/{instagram}", "label": "Open Instagram DM"}
        out["page"] = {"href": f"https://www.instagram.com/{instagram}/", "label": "Profile"}
    elif channel == "facebook" and facebook:
        t = fb_target(facebook)
        if t:
            out["open"] = {"href": f"https://m.me/{t}", "label": "Open Messenger"}
        out["page"] = {"href": "https://www." + re.sub(r"^(?:https?://)?(?:www\.)?", "", facebook), "label": "Page"}
    elif channel == "call" and phone:
        out["open"] = {"href": tel_href(phone), "label": f"Call {phone}"}
        out["phone"] = phone
    elif channel == "text" and phone:
        out["open"] = {"href": tel_href(phone, "sms"), "label": f"Text {phone}"}
        out["phone"] = phone
    elif channel == "email" and email:
        out["open"] = {"href": f"mailto:{email}", "label": f"Email {email}"}
    return out


def has_link(text):
    return bool(URL_RE.search(text or ""))


# ---- the page ---------------------------------------------------------------------------------------------

def json_for_script(obj):
    """JSON safe inside <script type="application/json">: no '<', '>' or '&' survives as itself, so a lead's
    text can't close the element or open a comment; JSON.parse reads the escapes back as the characters."""
    s = json.dumps(obj, ensure_ascii=False, indent=None, separators=(",", ":"))
    return (s.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
             .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render(data, template=TEMPLATE):
    """The page: the template with the title (HTML-escaped) and the data (as JSON) in. Every string the page
    shows goes through textContent in the page's own script."""
    tpl = Path(template).read_text()
    return (tpl.replace("{{TITLE}}", html.escape(data.get("title") or "Outreach deck", quote=False))
               .replace("{{DATA}}", json_for_script(data)))
