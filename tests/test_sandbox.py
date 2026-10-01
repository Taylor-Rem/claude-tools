"""B80 — the client/demo sandbox boundary.

The parts of B80 that carry into B85 (plans/36-os-sandbox.md, decision 6): the
tenant-identity cross-check refuses a mismatched RELAY_PROJECT, the demo
publish gate refuses server-side changes, and the stamp denies edits to the
workspace's identity and settings. The B80 PreToolUse hook is gone: behind the
OS sandbox it added nothing and refused pipes and chains.

    python3 -m unittest tests.test_sandbox   (from claude-tools/)
"""

import json
import os
import subprocess
import tempfile
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = HERE.parent / "bin"
CLIENT = BIN / "client"
C = SourceFileLoader("client_mod", str(CLIENT)).load_module()
S = SourceFileLoader("site_mod", str(BIN / "site")).load_module()


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


class Tenant(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        (self.ws / ".client.json").write_text(json.dumps({"slug": "acme", "name": "Acme"}))

    def tearDown(self):
        self.tmp.cleanup()

    # a subcommand of each tool that reads the workspace identity
    TOOLS = {"newsletter": "status", "pay": "status", "gbp": "show", "connections": "ls"}

    def run_tool(self, tool, env):
        return subprocess.run([str(BIN / tool), self.TOOLS[tool]], cwd=str(self.ws),
                              env=dict(os.environ, **env), capture_output=True, text=True)

    def test_mismatch_refused(self):
        for tool in self.TOOLS:
            r = self.run_tool(tool, {"RELAY_PROJECT": "other-client"})
            self.assertNotEqual(r.returncode, 0, tool)
            self.assertIn("acme", r.stderr + r.stdout, tool)
            self.assertIn("other-client", r.stderr + r.stdout, tool)

    def test_match_passes_identity_check(self):
        # match proceeds past the identity check (then fails on "not registered",
        # which proves the cross-check didn't fire).
        r = self.run_tool("newsletter", {"RELAY_PROJECT": "acme"})
        self.assertNotIn("Refusing to touch another client", r.stderr + r.stdout)

    def test_no_relay_project_passes(self):
        env = dict(os.environ)
        env.pop("RELAY_PROJECT", None)
        r = subprocess.run([str(BIN / "newsletter"), "status"], cwd=str(self.ws),
                           env=env, capture_output=True, text=True)
        self.assertNotIn("Refusing to touch another client", r.stderr + r.stdout)


class DemoGate(unittest.TestCase):
    """sandbox-F3 — a demo may publish page edits but not server-side code."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Path(self.tmp.name)
        self.repo = self.ws / "repos" / "demo-site"
        self.repo.mkdir(parents=True)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@t")
        git(self.repo, "config", "user.name", "t")
        (self.repo / "index.html").write_text("<h1>demo</h1>")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "initial")
        git(self.repo, "tag", "golden")
        self.meta = {"slug": "demo-service", "demo": True, "demo_publish": "static"}
        S.DRY = False
        # B85: the gate compares against the golden sha bin/demo recorded outside the workspace
        import sandbox_tools
        self.st = sandbox_tools
        self.saved_state = sandbox_tools.DEMO_STATE
        sandbox_tools.DEMO_STATE = self.ws / "demo.json"
        head = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "HEAD"], capture_output=True,
                              text=True).stdout.strip()
        sandbox_tools.DEMO_STATE.write_text(json.dumps({"demos": {"demo-service": {"golden": head}}}))

    def tearDown(self):
        self.st.DEMO_STATE = self.saved_state
        self.tmp.cleanup()

    def test_moving_the_golden_ref_changes_nothing(self):
        (self.repo / "functions").mkdir()
        (self.repo / "functions" / "evil.js").write_text("export default 1")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "add fn")
        git(self.repo, "tag", "-f", "golden", "HEAD")
        why = S.demo_publish_block(self.meta, self.repo)
        self.assertTrue(why and "functions" in why)

    def test_no_golden_record_refuses(self):
        self.st.DEMO_STATE.write_text("{}")
        self.assertIn("no golden copy on record", S.demo_publish_block(self.meta, self.repo))

    def test_page_edit_static_allowed(self):
        (self.repo / "index.html").write_text("<h1>new</h1>")
        git(self.repo, "commit", "-qam", "page edit")
        self.assertIsNone(S.demo_publish_block(self.meta, self.repo))

    def test_functions_change_static_refused(self):
        (self.repo / "functions").mkdir()
        (self.repo / "functions" / "evil.js").write_text("export default 1")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "add fn")
        why = S.demo_publish_block(self.meta, self.repo)
        self.assertTrue(why and "functions" in why)

    def test_off_mode_refuses_all(self):
        why = S.demo_publish_block(dict(self.meta, demo_publish="off"), self.repo)
        self.assertTrue(why)


class Stamp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clients = Path(self.tmp.name) / "clients"
        self.env = dict(os.environ, CLIENTS_DIR=str(self.clients),
                        RELAY_CONFIG=str(Path(self.tmp.name) / "none.json"),
                        CLAUDE_TOOLS_ENV=str(Path(self.tmp.name) / "no-env"))

    def tearDown(self):
        self.tmp.cleanup()

    def new(self, slug):
        return subprocess.run([str(CLIENT), "new", slug, "--name", slug.title(), "--shared-key"],
                              env=self.env, capture_output=True, text=True)

    def settings(self, slug):
        return json.loads((self.clients / slug / ".claude" / "settings.json").read_text())

    def test_identity_denies_stamped(self):
        self.assertEqual(self.new("acme").returncode, 0)
        s = self.settings("acme")
        self.assertNotIn("hooks", s, "the B80 PreToolUse hook is gone (B85: the wall is the OS sandbox)")
        for d in ("Edit(./.client.json)", "Write(./.client.json)", "Edit(./.claude/**)", "Write(./.claude/**)"):
            self.assertIn(d, s["permissions"]["deny"])

    def test_demo_stamp_fields(self):
        # B85: the demo's narrower tools are the broker's role table (lib/sandbox_tools.py,
        # tests/test_sandbox_tools.py), not a trimmed allowlist; the stamp carries role + demo_publish.
        self.assertEqual(self.new("demo-service").returncode, 0)
        meta = json.loads((self.clients / "demo-service" / ".client.json").read_text())
        self.assertTrue(meta["demo"])
        self.assertEqual(meta["role"], "demo")
        self.assertEqual(meta["demo_publish"], "static")


if __name__ == "__main__":
    unittest.main()
