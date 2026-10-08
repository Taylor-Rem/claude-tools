"""Run the engine tools offline and return what they print, for the venture goldens (ROADMAP B146).

`capture(env)` builds one hermetic world (the made-up services census, a copy of the outreach
templates, a made-up ~/projects tree for social and books, a fake patchlamp.com for front, the cloud
fixtures) and runs each named command in it with `env` laid over the top, returning
{name: stdout + stderr + exit code}, with the temp paths and the clock taken out so two runs compare.

tests/test_venture.py compares it against tests/fixtures/venture/golden/, which was written by
`python3 tests/venture_capture.py --write` on `main` before the identity moved into ventures/
(so the goldens are today's output, and the venture file has to reproduce it byte for byte).
Nothing here reaches the network: every host is a stub on 127.0.0.1 or `.invalid`.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent
BIN = TOOLS / "bin"
GOLDEN = HERE / "fixtures" / "venture" / "golden"
ANCHOR = "2026-09-28"                   # a Monday (test_leads_today's)
DATE = "2026-10-06"                     # a Tuesday: a data post (test_social_trust's)
ADDRESS = "PO Box 1234, American Fork, UT 84003"
PHONE = "801-555-0100"


def _social_world(projects):
    import test_social_trust as st
    for rel, text in (("client-leads/DATA_STORY_STATS.md", st.DATA_STORY), ("patchlamp/CLAIMS.md", st.CLAIMS),
                      ("research/b/brief.md", st.BRIEF), ("patchlamp/app/Support/Prices.php", st.PRICES),
                      ("patchlamp/BRAND.md", "# Brand\n\nPatch, a raccoon, keeps the lamp lit.\n")):
        p = projects / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    social = projects / "social"
    (social / "topics").mkdir(parents=True)
    (social / "topics" / "patchlamp.md").write_text(st.TOPICS)
    (social / "rules.md").write_text("# rules\n- a number stands on a line in a file\n")
    (social / "posted.jsonl").write_text(json.dumps({"date": "2026-10-05", "status": "posted", "kind": "text",
                                                     "caption": "Can I just text it a photo? Yes."}) + "\n")
    (projects / "marketing" / "copy").mkdir(parents=True)
    return social


class _Front(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path.endswith("/visits"):
            body = {"days": 7, "since": "2026-09-22", "totals": {"views": 42, "visitor_days": 17},
                    "by_day": [{"day": "2026-09-27", "visitors": 5, "views": 12},
                               {"day": "2026-09-28", "visitors": 12, "views": 30}],
                    "pages": [{"path": "/", "views": 30}, {"path": "/pricing", "views": 12}],
                    "referrers": [{"ref": "facebook.com", "views": 4}]}
        elif u.path.endswith("/leads"):
            body = {"leads": [{"id": 7, "at": "2026-09-28T10:15:00-06:00", "business": "Acme Plumbing",
                               "phone": "555-0199", "note": "can you fix my hours", "page": "/check"}]}
        else:
            self.send_response(404)
            self.end_headers()
            return
        raw = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def _clean(text, root, port):
    """Take out what changes between runs: the temp dir, the checkout, the stub's port, today's date."""
    import datetime as dt
    import re
    text = text.replace(str(root), "<TMP>").replace(str(TOOLS), "<TOOLS>")
    text = text.replace(f"127.0.0.1:{port}", "127.0.0.1:<PORT>")
    today = dt.date.today()
    text = re.sub(re.escape(today.isoformat()) + r"T\d\d:\d\d:\d\d(?:[.,]\d+)?(?:[+-]\d\d:\d\d)?", "<NOW>", text)
    return text.replace(today.isoformat(), "<TODAY>").replace(today.strftime("%a %-d %b"), "<TODAY>")


def capture(env=None, only=None):
    """{name: normalised output} for every command, with `env` laid over the hermetic one."""
    env = dict(env or {})
    root = Path(tempfile.mkdtemp(prefix="venture-capture-"))
    server = HTTPServer(("127.0.0.1", 0), _Front)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        import test_leads_today as tl
        db = tl.build_census(root / "census.db")
        tpl = root / "tpl"
        shutil.copytree(TOOLS / "templates" / "outreach", tpl)
        (tpl / "APPROVED").unlink(missing_ok=True)
        (tpl / "APPROVED.example").unlink(missing_ok=True)
        projects = root / "projects"
        social = _social_world(projects)
        home = root / "home"
        (home / ".local/state/claude-tools").mkdir(parents=True)
        (home / ".local/state/claude-tools/ledger.jsonl").write_text(
            json.dumps({"ts": "2026-09-10T10:00:00-06:00", "tool": "img", "usd": 0.04, "what": "gen"}) + "\n")
        (projects / "private-docs").mkdir(parents=True)
        (projects / "private-docs" / "books.jsonl").write_text(
            json.dumps({"kind": "expense", "date": "2026-09-12", "vendor": "Porkbun", "amount": 11.08,
                        "note": "a domain"}) + "\n")
        (projects / "sms-relay" / "state").mkdir(parents=True)
        cloud_fx = root / "cloud"
        cloud_fx.mkdir()
        for f in (HERE / "fixtures" / "cloud").iterdir():
            (cloud_fx / f.name).write_text(f.read_text().replace("{{HEAD}}", "0" * 40))

        base = {k: v for k, v in os.environ.items()
                if not k.startswith(("LEADS_", "OUTREACH_", "SOCIAL_", "CLOUD_", "VENTURE"))}
        base.update({
            "HOME": str(home), "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "TZ": "America/Denver",
            "CLAUDE_TOOLS_ENV": str(root / "no-env"), "PROJECTS_DIR": str(projects),
            # leads
            "LEADS_DB": str(db), "LEADS_STATE": str(root / "lstate"), "LEADS_LEDGER": str(root / "lledger.jsonl"),
            "LEADS_GROUPS_LOG": str(root / "groups.md"), "LEADS_MAIL_ADDRESS": ADDRESS, "GOOGLE_MAPS_API_KEY": "",
            "LEADS_PIPELINE": str(root / "pipeline.jsonl"), "LEADS_PREVIEWS": str(root / "previews"),
            "LEADS_NOW": ANCHOR, "LEADS_BOOKING_URL": "", "LEADS_KIT_PREVIEWS": "",
            # outreach
            "OUTREACH_TEMPLATES": str(tpl), "OUTREACH_STATE": str(root / "ostate"),
            "OUTREACH_LEDGER": str(root / "oledger.jsonl"), "OUTREACH_PROVIDER": "fake",
            "OUTREACH_FROM": "taylor@patchlampmail.example", "OUTREACH_PER_DAY": "6", "OUTREACH_AUTO": "",
            "OUTREACH_NOW": ANCHOR + "T09:00:00", "OUTREACH_LEADS_BIN": "/bin/false", "OUTREACH_NOTIFY_BIN": "/bin/true",
            "TAYLOR_TODO": str(root / "TODO.md"), "PATCHLAMP_VOICE_NUMBER": PHONE,
            # social
            "SOCIAL_DIR": str(social), "SOCIAL_PROJECTS": str(projects),
            "SOCIAL_MARKETING_DIR": str(projects / "marketing"), "SOCIAL_LEDGER": str(root / "sledger.jsonl"),
            # front
            "PATCHLAMP_URL": f"http://127.0.0.1:{server.server_port}",
            "PATCHLAMP_RELAY_SHARED_SECRET": "fake-offline-relay-secret",
            # cloud
            "CLOUD_FIXTURES": str(cloud_fx), "LARAVEL_CLOUD_TOKEN": "fake|token", "PATCHLAMP_REPO": str(root / "no-repo"),
        })
        for k in ("SOCIAL_WRITER_OPUS", "SOCIAL_WRITER_CODEX", "SOCIAL_FACTS_JUDGE", "SOCIAL_PICKER"):
            base.pop(k, None)
        base.update(env)

        cmds = [
            ("leads-help", "leads", ["--help"]),
            ("leads-today-json", "leads", ["today", "--census-only", "--json"]),
            ("leads-today", "leads", ["today", "--census-only"]),
            ("leads-kit", "leads", ["kit", "--census-only", "--for", ANCHOR]),
            ("leads-kit-remote", "leads", ["kit", "--remote", "--census-only", "--for", ANCHOR]),
            ("outreach-help", "outreach", ["--help"]),
            ("outreach-approve-dry", "outreach", ["approve", "--dry-run"]),
            ("outreach-status", "outreach", ["status"]),
            ("prep-help", "prep", ["--help"]),
            ("social-help", "social", ["--help"]),
            ("social-packet", "social", ["packet", "--date", DATE]),
            ("front", "front", []),
            ("front-doctor", "front", ["doctor"]),
            ("front-help", "front", ["--help"]),
            ("books-pl", "books", ["pl", "--month", "2026-09"]),
            ("books-help", "books", ["--help"]),
            ("cloud-help", "cloud", ["--help"]),
            ("cloud-deploys", "cloud", ["deploys", "-n", "3"]),
        ]
        out = {}
        for name, tool, args in cmds:
            if only and name not in only:
                continue
            e = dict(base)
            if tool == "leads":                 # each leads run starts from an empty pipeline: a kit holds its six
                e.update({"LEADS_STATE": str(root / name / "lstate"), "LEADS_PIPELINE": str(root / name / "p.jsonl"),
                          "LEADS_PREVIEWS": str(root / name / "previews")})
            r = subprocess.run([sys.executable, str(BIN / tool), *args], capture_output=True, text=True,
                               env=e, cwd=str(root), timeout=180, stdin=subprocess.DEVNULL)
            text = f"$ {tool} {' '.join(args)}\n--- stdout\n{r.stdout}--- stderr\n{r.stderr}--- exit {r.returncode}\n"
            if name == "social-packet":
                for ext in ("md", "json"):
                    f = social / "packets" / f"{DATE}.{ext}"
                    text += f"--- packets/{DATE}.{ext}\n" + (f.read_text() if f.exists() else "(none)\n")
            out[name] = _clean(text, root, server.server_port)
        return out
    finally:
        server.shutdown()
        server.server_close()
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    got = capture()
    if "--write" in sys.argv:
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for name, text in got.items():
            (GOLDEN / f"{name}.txt").write_text(text)
        print(f"wrote {len(got)} goldens to {GOLDEN}")
    else:
        for name, text in got.items():
            print(text)
