"""Keep the toolbelt suite off production and away from the real key file.

Every test module imports this first (`import _offline  # noqa: F401`, before it
loads any tool), and `test_offline.py` fails if one doesn't. It has to be an
import: `python3 -m unittest discover -s tests` loads each test file as a
top-level module and never runs a `tests/__init__.py`, so a module every test
imports is the one place that is sure to execute before the tools are loaded
or spawned.

On first import, for this process and every tool it spawns (they inherit
os.environ):

- CLAUDE_TOOLS_ENV points at a throwaway key file holding obviously fake values
  for the keys the tools read. Fake rather than empty on purpose: a test that
  wanders into a real call then gets as far as the network, where the next
  point catches it, instead of stopping quietly on "key missing".
- PATCHLAMP_URL points at a name that can't resolve (`.invalid`).
- HTTP(S)_PROXY / ALL_PROXY point at a recording stub on 127.0.0.1 that answers
  every request with a 403 and notes the host. urllib, requests, git and gh all
  honour these; NO_PROXY keeps localhost (the tests' own fake servers) direct.
  `test_offline` fails the run if the stub saw any host at all.

Why (2026-10-01): `test_sandbox` ran `newsletter status` in an "acme" workspace
with the real key file, and every full run sent two GETs to
patchlamp.com/internal/relay/projects/acme with the relay's real shared secret.
A test that needs a real host or key sets its own env for that one call.
"""

import atexit
import os
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

# Hosts the stub was asked for, in order: "CONNECT patchlamp.com:443" style lines.
ATTEMPTS = []
_lock = threading.Lock()

FAKE_KEYS = {
    "PATCHLAMP_RELAY_SHARED_SECRET": "fake-offline-relay-secret",
    "CLOUDFLARE_API_TOKEN": "fake-offline-cf-token",
    "CLOUDFLARE_ACCOUNT_ID": "fake-offline-cf-account",
    "GITHUB_TOKEN": "fake-offline-gh-token",
    "GOOGLE_MAPS_API_KEY": "fake-offline-maps-key",
    "PEXELS_API_KEY": "fake-offline-pexels",
    "GEMINI_API_KEY": "fake-offline-gemini",
    "DISCORD_BOT_TOKEN": "fake-offline-discord",
    "TELEGRAM_BOT_TOKEN": "fake-offline-telegram",
    "LARAVEL_CLOUD_TOKEN": "fake-offline-cloud",
    "SITE_ORG": "fake-offline-org",
}
REAL_KEY_FILE = Path.home() / ".config/claude-tools/env"


class _Stub(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            first = self.rfile.readline(4096).decode("latin-1").strip()
        except OSError:
            return
        parts = first.split()
        if len(parts) >= 2:
            target = parts[1]
            if "://" in target:                       # GET http://host/path
                target = target.split("://", 1)[1].split("/", 1)[0]
            with _lock:
                ATTEMPTS.append(f"{parts[0]} {target}")
        try:
            self.wfile.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        except OSError:
            pass


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def _install():
    if os.environ.get("CLAUDE_TOOLS_OFFLINE_PID") == str(os.getpid()):
        return
    tmp = Path(tempfile.mkdtemp(prefix="claude-tools-offline-"))
    keyfile = tmp / "env"
    keyfile.write_text("# fake keys for the test suite (tests/_offline.py)\n"
                       + "".join(f"{k}={v}\n" for k, v in FAKE_KEYS.items()))
    keyfile.chmod(0o600)
    server = _Server(("127.0.0.1", 0), _Stub)
    threading.Thread(target=server.serve_forever, daemon=True, name="offline-proxy").start()
    proxy = f"http://127.0.0.1:{server.server_address[1]}"
    os.environ.update({
        "CLAUDE_TOOLS_ENV": str(keyfile),
        "PATCHLAMP_URL": "https://patchlamp.offline.invalid",
        "CLAUDE_TOOLS_OFFLINE_PID": str(os.getpid()),
        "CLAUDE_TOOLS_OFFLINE_PROXY": proxy,
    })
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        os.environ[k] = os.environ[k.lower()] = proxy
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "localhost,127.0.0.1,::1"

    def report():
        if ATTEMPTS:
            print(f"\n_offline: tests tried to reach real hosts (blocked): {sorted(set(ATTEMPTS))}",
                  file=sys.stderr)
    atexit.register(report)


_install()
