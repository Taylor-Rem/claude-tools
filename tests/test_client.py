"""client ls / doctor against a temp clients dir and a temp relay config.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

The tier table is the relay's own relay/tiers.py, copied beside the temp
config.json the way it sits beside the real one (skipped if the relay isn't
checked out next to the toolbelt). RELAY_TIERS points it at another copy,
e.g. a relay worktree's, to check a tier change before it merges.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLIENT = HERE.parent / "bin" / "client"
TIERS = Path(os.environ.get("RELAY_TIERS") or HERE.parent.parent / "sms-relay" / "relay" / "tiers.py")


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
        self.assertIn("plan: Hosting $20/mo · $10 usage/mo ($20 first) · 1 texter · no schedules", out)
        self.assertIn("on Light", out)
        self.assertIn("plan: Light $50/mo · $40 usage/mo ($80 first) · 1 texter · no schedules", out)

    def test_doctor_shows_the_plan(self):
        out = self.run_client("doctor", "hostco").stdout
        self.assertIn("relay: on Hosting;", out)
        self.assertIn("plan: Hosting $20/mo", out)

    def test_doctor_counts_doc_inside_the_wall(self):
        out = self.run_client("doctor", "hostco").stdout
        self.assertIn("12 shims in sandbox/bin", out)
        self.assertIn("1 tool runs inside the wall (doc:", out)
        self.assertNotIn("FAIL sandbox/bin", out)

    def test_new_takes_every_tier(self):
        r = self.run_client("new", "newco", "--name", "New Co", "--tier", "light", "--shared-key")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((self.clients / "newco" / ".client.json").read_text())["sites"], 1)
        r = self.run_client("new", "badco", "--name", "Bad", "--tier", "gold", "--shared-key")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("hosting, light, starter", r.stderr + r.stdout)

    def test_new_keeps_the_template_they_picked(self):
        r = self.run_client("new", "poolco", "--name", "Pool Co", "--template", "service", "--shared-key")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("template: service", r.stdout)
        meta = lambda: json.loads((self.clients / "poolco" / ".client.json").read_text())
        self.assertEqual(meta()["template"], "service")
        self.run_client("new", "poolco", "--restamp", "--shared-key")
        self.assertEqual(meta()["template"], "service", "a restamp keeps it")
        r = self.run_client("new", "oddco", "--name", "Odd", "--template", "marketplace", "--shared-key")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not a kind of site", r.stderr)


class ClientAllowlist(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clients = Path(self.tmp.name) / "clients"
        self.env = dict(os.environ, CLIENTS_DIR=str(self.clients), RELAY_CONFIG=str(Path(self.tmp.name) / "none.json"),
                        CLAUDE_TOOLS_ENV=str(Path(self.tmp.name) / "no-env"))

    def tearDown(self):
        self.tmp.cleanup()

    def run_client(self, *args):
        return subprocess.run([str(CLIENT), *args], env=self.env, capture_output=True, text=True)

    def test_workspace_allows_the_documented_publish_shape(self):
        """2026-09-30: Patch's `git -C repos/x push -q` was refused. The rendered
        allowlist carries every `git -C repos/*` form CLAUDE.md shows, and reset stays denied."""
        r = self.run_client("new", "permco", "--name", "Perm Co", "--shared-key")
        self.assertEqual(r.returncode, 0, r.stderr)
        ws = self.clients / "permco"
        perms = json.loads((ws / ".claude" / "settings.json").read_text())["permissions"]
        for verb in ("status*", "log*", "diff*", "show*", "add *", "commit *", "push", "push origin main",
                     "push -q", "pull", "revert HEAD*", "checkout -- *", "rev-parse*", "fetch*"):
            self.assertIn(f"Bash(git -C repos/* {verb})", perms["allow"])
        self.assertIn("Bash(git -C repos/* reset --hard*)", perms["deny"])
        md = (ws / "CLAUDE.md").read_text()
        for step in ('`git -C repos/<name> commit -am "', "`git -C repos/<name> push`", "`site publish <name>`",
                     "`git -C repos/<name> revert HEAD --no-edit`"):
            self.assertIn(step, md)


class PatchBuilt(unittest.TestCase):
    """A repo registered only for its push address (`client remotes --add`, host "external") isn't
    one of our sites, so the doctor doesn't ask it for the template's CLAUDE.md."""

    def test_external_row_is_not_patch_built(self):
        import importlib.machinery, importlib.util  # noqa: E401
        loader = importlib.machinery.SourceFileLoader("client_tool", str(CLIENT))
        mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("client_tool", loader))
        loader.exec_module(mod)
        with tempfile.TemporaryDirectory() as tmp:
            mod.SITES = Path(tmp) / "sites.json"
            mod.SITES.write_text(json.dumps({"acme": {
                "site": {"host": "cloudflare", "project": "acme-site"},
                "app": {"host": "external", "remote": "git@github.com:someone/app.git"}}}))
            self.assertTrue(mod.patch_built("acme", "site"))
            self.assertFalse(mod.patch_built("acme", "app"))
            self.assertFalse(mod.patch_built("other", "site"))


if __name__ == "__main__":
    unittest.main()
