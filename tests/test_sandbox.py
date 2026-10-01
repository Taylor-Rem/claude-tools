"""B80 — the client/demo sandbox boundary.

Proves, from code, that the PreToolUse hook denies each known bypass (named by
its finding id in private-docs/security/2026-09-30-{sandbox,relay}.md), that the
tenant-identity cross-check refuses a mismatched RELAY_PROJECT, and that the
demo publish gate refuses server-side changes.

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


class Hook(unittest.TestCase):
    """Each case asserts the hook's decision in code, the way prep's hook is tested."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(os.path.realpath(self.tmp.name))
        (self.root / "repos" / "site").mkdir(parents=True)
        (self.root / "incoming").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def decide(self, tool, ti):
        return C.hook_decide({"tool_name": tool, "tool_input": ti}, self.root)

    def deny(self, tool, ti, msg):
        allow, why = self.decide(tool, ti)
        self.assertFalse(allow, f"{msg}: expected deny for {tool} {ti}")
        self.assertTrue(why, "a denial must carry a reason (VISION Rules 8)")

    def ok(self, tool, ti, msg):
        allow, why = self.decide(tool, ti)
        self.assertTrue(allow, f"{msg}: expected allow for {tool} {ti} (why={why})")

    # (i) sandbox-F1 / relay-F1 — a file-opening tool with an input path outside
    #     the workspace, including a glued scheme:/path form.
    def test_f1_glued_scheme_path_denied(self):
        self.deny("Bash", {"command": "magick text:/etc/passwd incoming/x.png"}, "sandbox-F1")
        self.deny("Bash", {"command": "magick label:@/home/tweenson/.config/env repos/site/x.png"}, "sandbox-F1")
        self.deny("Bash", {"command": "identify /home/tweenson/.ssh/id_rsa"}, "sandbox-F1")

    # (ii) relay-F1 — a bare Grep/Glob outside cwd.
    def test_f1_bare_grep_glob_outside_denied(self):
        self.deny("Grep", {"pattern": "KEY", "path": "/home/tweenson/.config"}, "relay-F1")
        self.deny("Glob", {"pattern": "../../*.env"}, "relay-F1")
        self.deny("Bash", {"command": "grep -r token /home/tweenson/.config"}, "relay-F1")

    # (iii) sandbox-F2 / relay-F3 — Write/Edit to .client.json and .claude/**.
    def test_f2_identity_files_unwritable(self):
        self.deny("Write", {"file_path": "./.client.json", "content": "{}"}, "sandbox-F2")
        self.deny("Edit", {"file_path": str(self.root / ".client.json")}, "sandbox-F2")
        self.deny("Write", {"file_path": "./.claude/settings.json", "content": "{}"}, "relay-F3")
        self.deny("Edit", {"file_path": str(self.root / ".claude" / "x.json")}, "relay-F3")

    def test_shell_metacharacters_denied(self):
        for cmd in ("git -C repos/site add . && git -C repos/site commit -m x",
                    "cat repos/site/index.html | head",
                    "echo $(cat /etc/passwd)",
                    "grep x repos/site > /tmp/out"):
            self.deny("Bash", {"command": cmd}, "chain/redirect/substitution")

    def test_unknown_command_denied(self):
        self.deny("Bash", {"command": "cat /home/tweenson/.config/claude-tools/env"}, "cat not a tool")
        self.deny("Bash", {"command": "nc evil.example 1234"}, "nc not a tool")

    def test_normal_client_work_allowed(self):
        for cmd in ("git -C repos/site status",
                    "git -C repos/site commit -m Footer: new hours",
                    "git -C repos/site push",
                    "shot https://foo.pages.dev/",
                    "shot repos/site/index.html --mobile",
                    "grep -n pool repos/site/index.html",
                    "ls incoming",
                    "db query SELECT * FROM records",
                    "img gen a photo of a pool",
                    "TZ=America/Denver date -d 2026-09-29"):
            self.ok("Bash", {"command": cmd}, "ordinary client work")
        self.ok("Read", {"file_path": "repos/site/index.html"}, "read own repo")
        self.ok("Edit", {"file_path": str(self.root / "repos" / "site" / "index.html")}, "edit own repo")
        self.ok("Grep", {"pattern": "pool", "path": "repos/site"}, "grep own repo")

    def test_git_dash_C_outside_denied(self):
        self.deny("Bash", {"command": "git -C /home/tweenson/.ssh log"}, "git -C escape")
        self.deny("Bash", {"command": "git -C../../other log"}, "git -C escape")

    def test_curl_local_file_denied(self):
        self.deny("Bash", {"command": "curl -s file:///etc/passwd"}, "curl file scheme")
        self.ok("Bash", {"command": "curl -s https://foo.pages.dev/"}, "curl own url")

    def test_hook_subprocess_exit_codes(self):
        """The stamped entry: stdin event in, exit 0 allow / 2 deny."""
        def run(event):
            r = subprocess.run([str(CLIENT), "hook", "--dir", str(self.root)],
                               input=json.dumps(event), capture_output=True, text=True)
            return r.returncode
        self.assertEqual(run({"tool_name": "Bash", "tool_input": {"command": "git -C repos/site status"}}), 0)
        self.assertEqual(run({"tool_name": "Bash", "tool_input": {"command": "magick text:/etc/passwd incoming/x.png"}}), 2)
        self.assertEqual(run({"tool_name": "Write", "tool_input": {"file_path": "./.client.json"}}), 2)


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

    def tearDown(self):
        self.tmp.cleanup()

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

    def test_hook_and_denies_stamped(self):
        self.assertEqual(self.new("acme").returncode, 0)
        s = self.settings("acme")
        cmd = s["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn("hook", cmd)
        self.assertIn("client", cmd)
        for d in ("Edit(./.client.json)", "Write(./.client.json)", "Edit(./.claude/**)", "Write(./.claude/**)"):
            self.assertIn(d, s["permissions"]["deny"])

    def test_demo_allowlist_trimmed(self):
        self.assertEqual(self.new("demo-service").returncode, 0)
        meta = json.loads((self.clients / "demo-service" / ".client.json").read_text())
        self.assertTrue(meta["demo"])
        self.assertEqual(meta["demo_publish"], "static")
        allow = self.settings("demo-service")["permissions"]["allow"]
        for t in C.DEMO_DROP_TOOLS:
            self.assertFalse(any(r.startswith(f"Bash({t} ") for r in allow), f"demo still grants {t}")
        self.assertNotIn("Bash(site *)", allow)
        self.assertIn("Bash(site publish*)", allow)


if __name__ == "__main__":
    unittest.main()
