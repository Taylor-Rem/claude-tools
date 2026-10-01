"""The suite stays off production and away from the real key file (tests/_offline.py).

    python3 -m unittest discover -s tests -q   (from claude-tools/)

Named test_zz_ so discovery loads it last: `test_nothing_reached_a_real_host`
then sees every request the earlier modules' tools tried to make. Run alone it
still checks its own module, and _offline prints any attempt at exit either way.

Why: until 2026-10-01 test_sandbox ran `newsletter status` in an "acme"
workspace with the real key file, so every full run sent two GETs to
patchlamp.com/internal/relay/projects/acme with the relay's real shared secret.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE.parent / "bin"


class Offline(unittest.TestCase):
    def test_every_test_module_imports_offline_before_anything_else(self):
        for p in sorted(HERE.glob("test_*.py")):
            src = p.read_text()
            at = src.find("import _offline")
            self.assertNotEqual(at, -1, f"{p.name} doesn't import _offline")
            # nothing that loads or runs a tool may come before it
            for marker in ("SourceFileLoader", "spec_from_file_location", "subprocess.", "\ndef ", "\nclass "):
                first = src.find(marker)
                self.assertTrue(first == -1 or first > at, f"{p.name}: {marker.strip()} before import _offline")

    def test_the_key_file_and_the_site_are_redirected(self):
        real = Path.home() / ".config/claude-tools/env"
        env = Path(os.environ["CLAUDE_TOOLS_ENV"])
        self.assertNotEqual(env.resolve(), real.resolve())
        self.assertIn("fake-offline-relay-secret", env.read_text())
        self.assertTrue(os.environ["PATCHLAMP_URL"].endswith(".invalid"))
        for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "ALL_PROXY"):
            self.assertEqual(os.environ[k], os.environ["CLAUDE_TOOLS_OFFLINE_PROXY"])

    def test_no_tool_reads_the_key_file_but_through_claude_tools_env(self):
        # Code that names the real path must also honour CLAUDE_TOOLS_ENV, or the redirect can't reach it.
        for p in sorted(BIN.iterdir()) + sorted((HERE.parent / "lib").glob("*.py")):
            if not p.is_file():
                continue
            try:
                src = p.read_text()
            except UnicodeDecodeError:
                continue
            code = [ln for ln in src.splitlines() if re.search(r"""["'/]\.config/claude-tools/env|"env"\)|/ "env"\b""", ln)
                    and not ln.lstrip().startswith("#")]
            for ln in code:
                if "Path(" in ln or "open(" in ln or "expanduser" in ln:
                    self.assertIn("CLAUDE_TOOLS_ENV", src, f"{p.name} reads the key file without CLAUDE_TOOLS_ENV: {ln.strip()}")

    def test_the_stub_catches_a_tool_reaching_for_patchlamp(self):
        # The offending call itself, on purpose: newsletter status in an "acme" workspace, env inherited.
        before = len(_offline.ATTEMPTS)
        with tempfile.TemporaryDirectory() as ws:
            Path(ws, ".client.json").write_text(json.dumps({"slug": "acme", "name": "Acme"}))
            env = dict(os.environ)
            env.pop("RELAY_PROJECT", None)
            r = subprocess.run([str(BIN / "newsletter"), "status"], cwd=ws, env=env,
                               capture_output=True, text=True, timeout=60)
        caught = _offline.ATTEMPTS[before:]
        del _offline.ATTEMPTS[before:]                   # ours, not a leak
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(caught, ["CONNECT patchlamp.offline.invalid:443"], r.stderr)

    def test_nothing_reached_a_real_host(self):
        self.assertEqual(_offline.ATTEMPTS, [], "a test sent a request off this machine (blocked by "
                         "tests/_offline.py); give that test its own fake server or a fake binary")


if __name__ == "__main__":
    unittest.main()
