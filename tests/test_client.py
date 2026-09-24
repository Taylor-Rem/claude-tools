"""client ls / doctor against a temp clients dir and a temp relay config.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

The tier table is the relay's own relay/tiers.py, copied beside the temp
config.json the way it sits beside the real one (skipped if the relay isn't
checked out next to the toolbelt).
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLIENT = HERE.parent / "bin" / "client"
TIERS = HERE.parent.parent / "sms-relay" / "relay" / "tiers.py"


@unittest.skipUnless(TIERS.exists(), "sms-relay not checked out beside claude-tools")
class ClientTiers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "relay").mkdir()
        shutil.copy(TIERS, root / "relay" / "tiers.py")
        self.clients = root / "clients"
        projects, senders = {}, {}
        for slug, tier in (("hostco", "hosting"), ("lightco", "light")):
            ws = self.clients / slug
            (ws / "repos").mkdir(parents=True)
            (ws / "incoming").mkdir()
            (ws / ".client.json").write_text(json.dumps({"slug": slug, "name": slug.title()}))
            projects[slug] = {"type": "client", "name": slug.title(), "agent": {"auth": f"ANTHROPIC_KEY_{slug.upper()}"},
                              "billing": {"plan": "managed", "tier": tier, "started": "2026-09-24", "payer": f"sms:+1555000{len(senders)}"}}
            senders[f"sms:+1555000{len(senders)}"] = {"name": f"Owner of {slug}", "role": "client", "projects": [slug]}
        (root / "config.json").write_text(json.dumps({"projects": projects, "senders": senders}))
        self.env = dict(os.environ, CLIENTS_DIR=str(self.clients), RELAY_CONFIG=str(root / "config.json"),
                        CLAUDE_TOOLS_ENV=str(root / "no-env"))

    def tearDown(self):
        self.tmp.cleanup()

    def run_client(self, *args):
        return subprocess.run([str(CLIENT), *args], env=self.env, capture_output=True, text=True)

    def test_ls_names_the_new_tiers(self):
        out = self.run_client("ls").stdout
        self.assertIn("on Hosting", out)
        self.assertIn("plan: Hosting $10/mo · no usage · 0 texters (texts get the hosting reply, no changes) · no schedules", out)
        self.assertIn("on Light", out)
        self.assertIn("plan: Light $50/mo · $40 usage/mo ($80 first) · 1 texter · no schedules", out)

    def test_doctor_shows_the_plan(self):
        out = self.run_client("doctor", "hostco").stdout
        self.assertIn("relay: on Hosting;", out)
        self.assertIn("plan: Hosting $10/mo", out)

    def test_new_takes_every_tier(self):
        r = self.run_client("new", "newco", "--name", "New Co", "--tier", "light", "--shared-key")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((self.clients / "newco" / ".client.json").read_text())["sites"], 1)
        r = self.run_client("new", "badco", "--name", "Bad", "--tier", "gold", "--shared-key")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("hosting, light, starter", r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()
