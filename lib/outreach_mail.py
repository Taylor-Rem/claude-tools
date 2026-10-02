"""outreach_mail — the transport under `outreach`'s `google` provider (ROADMAP B90, plan
~/projects/plans/37-email-at-volume.md § 3, Taylor's answer 5): each outreach mailbox's own
Google mail server, SMTP to send and IMAP to read, standard library only.

Why a sender of our own: Instantly's $47 Growth plan warms the mailboxes but has no API,
so `outreach` sends and reads through the same path Instantly itself would use. This
module is only the wire: it builds a plain-text message, hands it to SMTP, reads new
mail by UID over IMAP and parses what came back (including delivery-status reports).
Everything about who, when and how many lives in `bin/outreach`.

Credentials arrive as arguments and are never logged, printed or put in an exception
message. A loopback host (the tests' in-process servers) is spoken to in plain text;
every other host gets TLS with the system's default certificate checks, so there is no
switch that turns TLS off for a real server.
"""

import email
import email.errors
import email.header
import email.policy
import email.utils
import imaplib
import os
import re
import secrets
import smtplib
import socket
import ssl
import time
from email.message import EmailMessage
from email.parser import HeaderParser

LOOPBACK = ("127.0.0.1", "localhost", "::1")


class MailError(Exception):
    """A transport fault, worded without the credential."""


def split_host(spec, default_port):
    spec = (spec or "").strip()
    if not spec:
        raise MailError("no host given")
    if spec.count(":") == 1:
        host, port = spec.split(":")
        host, port = host, int(port)
    else:
        host, port = spec, default_port
    if os.environ.get("CLAUDE_TOOLS_OFFLINE_PROXY") and not is_loopback(host):
        # Under the test suite (tests/_offline.py) a mail server is only ever a loopback fake.
        # SMTP and IMAP are raw sockets the suite's HTTP proxy can't catch, so the stop is here.
        raise MailError(f"the test suite never connects to a real mail server ({host})")
    return host, port


def is_loopback(host):
    return host in LOOPBACK


def domain_of(addr):
    return addr.rsplit("@", 1)[-1].strip().lower() if "@" in (addr or "") else ""


def make_message_id(domain):
    """A real Message-ID on the sending domain: random, so it says nothing about the list."""
    return f"<{secrets.token_hex(12)}.{int(time.time())}@{domain}>"


def build_message(from_addr, from_name, to, subject, body, message_id, in_reply_to=None,
                  references=None, unsubscribe_mailto=None, when=None):
    """Plain text only: no HTML part, no tracking pixel, no rewritten links. A follow-up
    carries In-Reply-To and References so it lands in the same thread."""
    msg = EmailMessage(policy=email.policy.SMTP)
    msg["From"] = email.utils.formataddr((from_name, from_addr)) if from_name else from_addr
    msg["To"] = to
    msg["Subject"] = subject
    msg["Date"] = email.utils.format_datetime(when) if when else email.utils.formatdate(localtime=True)
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    refs = [r for r in (references or []) if r]
    if refs:
        msg["References"] = " ".join(refs)
    if unsubscribe_mailto:
        msg["List-Unsubscribe"] = f"<mailto:{unsubscribe_mailto}?subject=unsubscribe>"
    msg.set_content(body, subtype="plain", charset="utf-8", cte="quoted-printable")   # 7-bit safe on any hop
    return msg


def smtp_send(hostspec, user, password, msg, timeout=30):
    """One message, one connection. Port 465 is implicit TLS, anything else STARTTLS
    (loopback excepted). Returns the envelope recipients refused (normally none)."""
    host, port = split_host(hostspec, 465)
    try:
        if is_loopback(host):
            conn = smtplib.SMTP(host, port, timeout=timeout)
        elif port == 465:
            conn = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            conn = smtplib.SMTP(host, port, timeout=timeout)
            conn.starttls(context=ssl.create_default_context())
        try:
            conn.login(user, password)
            refused = conn.send_message(msg)
        finally:
            try:
                conn.quit()
            except (smtplib.SMTPException, OSError):
                pass
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(f"{host} refused the login for {user} ({exc.smtp_code}); check its app password") from None
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError(f"{host} refused the recipient(s) {', '.join(exc.recipients)}") from None
    except (smtplib.SMTPException, OSError, socket.timeout) as exc:
        raise MailError(f"{host}:{port}: {type(exc).__name__}: {str(exc)[:160]}") from None
    return refused or {}


def smtp_check(hostspec, user, password, timeout=20):
    """Log in and leave: the doctor's proof that the app password works. Sends nothing."""
    host, port = split_host(hostspec, 465)
    try:
        if is_loopback(host):
            conn = smtplib.SMTP(host, port, timeout=timeout)
        elif port == 465:
            conn = smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context())
        else:
            conn = smtplib.SMTP(host, port, timeout=timeout)
            conn.starttls(context=ssl.create_default_context())
        try:
            conn.login(user, password)
        finally:
            try:
                conn.quit()
            except (smtplib.SMTPException, OSError):
                pass
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(f"{host} refused the login for {user} ({exc.smtp_code})") from None
    except (smtplib.SMTPException, OSError, socket.timeout) as exc:
        raise MailError(f"{host}:{port}: {type(exc).__name__}: {str(exc)[:160]}") from None
    return True


def _imap(hostspec, timeout):
    host, port = split_host(hostspec, 993)
    if is_loopback(host):
        return imaplib.IMAP4(host, port, timeout=timeout)
    return imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=timeout)


IMAP_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def imap_fetch_new(hostspec, user, password, last_uid=None, uidvalidity=None, since=None,
                   folder="INBOX", limit=500, timeout=30):
    """New messages by UID: -> (uidvalidity, [(uid, raw_bytes), ...]) oldest first.

    With a remembered UID (and an unchanged UIDVALIDITY) it reads everything above it;
    the first time, it reads from `since` (a date) so a mailbox full of warm-up mail is
    not read from the beginning. Read-only: nothing is marked seen or moved."""
    try:
        conn = _imap(hostspec, timeout)
    except (OSError, imaplib.IMAP4.error) as exc:
        raise MailError(f"IMAP {hostspec}: {type(exc).__name__}: {str(exc)[:160]}") from None
    try:
        try:
            conn.login(user, password)
        except imaplib.IMAP4.error:
            raise MailError(f"IMAP refused the login for {user}; check its app password") from None
        typ, _ = conn.select(folder, readonly=True)
        if typ != "OK":
            raise MailError(f"IMAP couldn't open {folder} for {user}")
        uv = None
        try:
            got = conn.response("UIDVALIDITY")[1]
            if got and got[0]:
                uv = int(got[0])
        except (ValueError, TypeError, imaplib.IMAP4.error):
            uv = None
        fresh = last_uid is not None and (uidvalidity is None or uv is None or int(uidvalidity) == uv)
        if fresh:
            typ, data = conn.uid("SEARCH", None, f"UID {int(last_uid) + 1}:*")
        else:
            d = since
            crit = f"SINCE {d.day:02d}-{IMAP_MONTHS[d.month - 1]}-{d.year}" if d else "ALL"
            typ, data = conn.uid("SEARCH", None, crit)
        if typ != "OK":
            raise MailError(f"IMAP search failed for {user}")
        uids = sorted({int(x) for x in (data[0] or b"").split() if x.isdigit()})
        if fresh:
            uids = [u for u in uids if u > int(last_uid)]   # `N:*` always returns the newest, even if old
        uids = uids[:limit]
        out = []
        for uid in uids:
            typ, parts = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
            if typ != "OK":
                continue
            raw = b""
            for p in parts or []:
                if isinstance(p, tuple) and len(p) == 2:
                    raw = p[1]
                    break
            if raw:
                out.append((uid, raw))
        return uv, out
    except (OSError, imaplib.IMAP4.error) as exc:
        raise MailError(f"IMAP {hostspec}: {type(exc).__name__}: {str(exc)[:160]}") from None
    finally:
        try:
            conn.logout()
        except (OSError, imaplib.IMAP4.error):
            pass


def imap_check(hostspec, user, password, timeout=20):
    try:
        conn = _imap(hostspec, timeout)
    except (OSError, imaplib.IMAP4.error) as exc:
        raise MailError(f"IMAP {hostspec}: {type(exc).__name__}: {str(exc)[:160]}") from None
    try:
        try:
            conn.login(user, password)
        except imaplib.IMAP4.error:
            raise MailError(f"IMAP refused the login for {user}") from None
        return True
    finally:
        try:
            conn.logout()
        except (OSError, imaplib.IMAP4.error):
            pass


# ---- reading what came back -----------------------------------------------------

MSGID_RE = re.compile(r"<[^<>\s]+>")


def ids_in(value):
    return MSGID_RE.findall(str(value or ""))


def _text_of(msg):
    """The person's words: the first text/plain part, else the HTML with tags removed."""
    plain, html = None, None
    for part in msg.walk() if msg.is_multipart() else [msg]:
        if part.is_multipart():
            continue
        ctype = part.get_content_type()
        if part.get_content_disposition() == "attachment":
            continue
        try:
            payload = part.get_payload(decode=True)
            text = payload.decode(part.get_content_charset() or "utf-8", errors="replace") if payload else ""
        except (LookupError, AttributeError):
            text = str(part.get_payload())
        if ctype == "text/plain" and plain is None:
            plain = text
        elif ctype == "text/html" and html is None:
            html = text
    if plain is not None:
        return plain.strip()
    if html is not None:
        t = re.sub(r"<br\s*/?>|</p>", "\n", html, flags=re.I)
        t = re.sub(r"<[^>]+>", "", t)
        return (t.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&nbsp;", " ")).strip()
    return ""


def _dsn(msg):
    """A delivery-status report (RFC 3464) -> {recipients, status, original_message_id},
    or None when the message isn't one. Only a permanent failure counts: `Action: failed`."""
    is_report = (msg.get_content_type() == "multipart/report"
                 and (msg.get_param("report-type") or "").lower() == "delivery-status")
    sender = (email.utils.parseaddr(msg.get("From", ""))[1] or "").lower()
    looks = is_report or sender.startswith(("mailer-daemon@", "postmaster@"))
    if not looks:
        return None
    recipients, statuses, original = [], [], None
    failed_seen = False
    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "message/delivery-status":
            blocks = part.get_payload()
            if isinstance(blocks, str):
                blocks = [HeaderParser().parsestr(b) for b in re.split(r"\n\s*\n", blocks)]
            for b in blocks or []:
                action = str(b.get("Action", "")).strip().lower()
                rcpt = str(b.get("Final-Recipient", "") or b.get("Original-Recipient", ""))
                if action:
                    if action == "failed":
                        failed_seen = True
                        addr = rcpt.split(";", 1)[-1].strip()
                        if addr:
                            recipients.append(addr.lower())
                        if b.get("Status"):
                            statuses.append(str(b.get("Status")).strip())
        elif ctype == "message/rfc822" and original is None:
            inner = part.get_payload()
            inner = inner[0] if isinstance(inner, list) and inner else inner
            if hasattr(inner, "get"):
                found = ids_in(inner.get("Message-ID"))
                original = found[0] if found else None
        elif ctype == "text/rfc822-headers" and original is None:
            payload = part.get_payload(decode=True) or b""
            hdrs = HeaderParser().parsestr(payload.decode("utf-8", errors="replace"))
            found = ids_in(hdrs.get("Message-ID"))
            original = found[0] if found else None
    if not is_report:
        # A plain-text bounce from a daemon: the recipient is named in the words.
        if not recipients:
            body = _text_of(msg)
            m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", body)
            if m:
                recipients.append(m.group(0).lower())
            if original is None:
                ids = ids_in(re.findall(r"(?im)^message-id:\s*(<[^>]+>)", body))
                original = ids[0] if ids else None
        failed_seen = failed_seen or bool(recipients)
    if not failed_seen:
        return {"recipients": [], "status": "delayed", "original_message_id": original, "failed": False}
    return {"recipients": sorted(set(recipients)), "status": ",".join(statuses) or "5.0.0",
            "original_message_id": original, "failed": True}


def parse_incoming(raw):
    """Raw bytes -> the fields `outreach` reasons with. Never raises on odd mail."""
    msg = email.message_from_bytes(raw, policy=email.policy.compat32)
    name, addr = email.utils.parseaddr(msg.get("From", ""))
    auto = (str(msg.get("Auto-Submitted", "")).lower().startswith("auto-")
            or bool(msg.get("X-Autoreply")) or bool(msg.get("X-Autorespond"))
            or str(msg.get("Precedence", "")).lower() in ("auto_reply", "auto-reply"))
    try:
        when = email.utils.parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else None
    except (TypeError, ValueError):
        when = None
    subj = msg.get("Subject", "")
    try:
        subj = str(email.header.make_header(email.header.decode_header(subj)))
    except (LookupError, ValueError, email.errors.HeaderParseError):
        subj = str(subj)
    return {
        "message_id": (ids_in(msg.get("Message-ID")) or [None])[0],
        "in_reply_to": ids_in(msg.get("In-Reply-To")),
        "references": ids_in(msg.get("References")),
        "from": (addr or "").strip(), "from_name": name,
        "subject": subj, "text": _text_of(msg),
        "date": when.isoformat() if when else None,
        "auto_reply": auto,
        "dsn": _dsn(msg),
    }

