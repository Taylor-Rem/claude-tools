"""todo's unattended runs (ROADMAP B83): the request box, Flint's inbox and build-night launch under the
stamped settings in templates/headless/, strict MCP, no connectors and their own login. Everything runs
against tests/fixtures/todo/fake-claude in a temporary ~/projects: no network, no model, no notify, no
systemd-run, nothing filed in the real tree.

    python3 -m unittest tests.test_todo_headless -q   (from claude-tools/)
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
TOOLS = HERE.parent
TODO = TOOLS / "bin" / "todo"
BUILD_NIGHT = TOOLS / "bin" / "build-night"
PROJECTS_MCP = TOOLS / "bin" / "projects-mcp"
FAKE = HERE / "fixtures" / "todo" / "fake-claude"
TOKEN_VALUE = "fake-headless-token-for-tests"
REQUIRED = ("Read(~/.config/**)", "Read(~/.ssh/**)", "Read(~/.claude/**)", "Read(~/.claude.json)",
            "mcp__playwright__browser_run_code_unsafe", "mcp__playwright__browser_file_upload")


class Headless(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.home, self.proj, self.state = t / "home", t / "home" / "projects", t / "state"
        (self.proj / "requests").mkdir(parents=True)
        (self.proj / "flint" / "inbox").mkdir(parents=True)
        (self.proj / "TAYLOR-TODO.md").write_text("# todo\n\n## 1. Now\n")
        self.envfile = t / "env"
        self.envfile.write_text("SOMETHING_ELSE=1\n")
        fakebin = t / "bin"
        fakebin.mkdir()
        (fakebin / "notify").write_text("#!/bin/sh\nexit 0\n")
        (fakebin / "notify").chmod(0o755)
        (fakebin / "claude").symlink_to(FAKE)
        self.log = t / "calls.jsonl"
        self.env = {"PATH": f"{TOOLS / 'bin'}:{fakebin}:/usr/bin:/bin", "HOME": str(self.home),
                    "TODO_FILE": str(self.proj / "TAYLOR-TODO.md"), "TODO_HEADLESS_STATE": str(self.state),
                    "TODO_CLAUDE": str(FAKE), "CLAUDE_TOOLS_ENV": str(self.envfile), "FAKE_LOG": str(self.log),
                    "PROJECTS": str(self.proj), "PROJECTS_DIR": str(self.proj),
                    "ANTHROPIC_API_KEY": "must-not-reach-the-run"}

    def tearDown(self):
        self.tmp.cleanup()

    def with_token(self):
        self.envfile.write_text(f"CLAUDE_HEADLESS_OAUTH_TOKEN={TOKEN_VALUE}\n")

    def run_cmd(self, *args, env=None, cmd=TODO):
        return subprocess.run([str(cmd), *args], env={**self.env, **(env or {})}, capture_output=True,
                              text=True, timeout=120)

    def calls(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def session_calls(self):
        return [c for c in self.calls() if "-p" in c["argv"]]

    @staticmethod
    def flag(argv, name):
        return argv[argv.index(name) + 1]

    # --- the dry run (the acceptance's first line) ------------------------------------------------

    def test_dry_run_request_shows_the_boundary_and_files_nothing(self):
        r = self.run_cmd("request", "--dry-run", "hello")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        for want in ("--permission-mode dontAsk", "--strict-mcp-config", "--setting-sources project", "--no-chrome",
                     f"--settings {self.state / 'settings.request.json'}", f"--mcp-config {self.state / 'mcp.json'}",
                     "servers: playwright", "ENABLE_CLAUDEAI_MCP_SERVERS=false", "SHOT_SANDBOX=1",
                     "the interactive login (fallback"):
            self.assertIn(want, out)
        self.assertEqual(list((self.proj / "requests").iterdir()), [])
        self.assertEqual(self.session_calls(), [])

    def test_dry_run_with_the_token_shows_the_dedicated_dir_and_never_the_token(self):
        self.with_token()
        r = self.run_cmd("request", "--dry-run", "hello")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"CLAUDE_CONFIG_DIR={self.state / 'config'}", r.stdout)
        self.assertIn("CLAUDE_CODE_OAUTH_TOKEN=<CLAUDE_HEADLESS_OAUTH_TOKEN>", r.stdout)
        self.assertNotIn(TOKEN_VALUE, r.stdout + r.stderr)

    def test_dry_run_build_and_the_old_name(self):
        for prompt in ("/build B83", "/continue B83"):
            r = self.run_cmd("request", "--dry-run", prompt)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("variant: build (auto)", r.stdout)
            self.assertIn(f"--settings {self.state / 'settings.build.json'}", r.stdout)
            self.assertIn("--model claude-fable-5-1", r.stdout)

    # --- the stamped files ------------------------------------------------------------------------

    def test_stamped_settings_deny_the_key_reads_and_the_unsafe_tools(self):
        self.run_cmd("request", "--dry-run", "x")
        self.run_cmd("request", "--dry-run", "/build")
        for variant, mode in (("request", "dontAsk"), ("build", "auto")):
            text = (self.state / f"settings.{variant}.json").read_text()
            self.assertNotIn("{{", text)
            doc = json.loads(text)
            deny = doc["permissions"]["deny"]
            for rule in REQUIRED:
                self.assertIn(rule, deny, variant)
            self.assertEqual(doc["permissions"]["defaultMode"], mode)
            self.assertEqual(doc["permissions"]["disableBypassPermissionsMode"], "disable")
            self.assertIs(doc["disableClaudeAiConnectors"], True)
            self.assertIs(doc["enableAllProjectMcpServers"], False)
            self.assertIn(f"Edit(/{self.proj}/.mcp.json)", deny)
            self.assertIn(f"Write(/{self.proj}/.todo-git/**)", deny)
            self.assertEqual(oct((self.state / f"settings.{variant}.json").stat().st_mode & 0o777), "0o600")
        mcp = json.loads((self.state / "mcp.json").read_text())
        self.assertEqual(list(mcp["mcpServers"]), ["playwright"])
        self.assertIn(str(TOOLS / "node_modules/@playwright/mcp/cli.js"), mcp["mcpServers"]["playwright"]["args"])
        request = json.loads((self.state / "settings.request.json").read_text())
        for taken_back in ("Bash(site *)", "Bash(git push*)", "Bash(gh pr merge*)", "Bash(./relay.py *)"):
            self.assertIn(taken_back, request["permissions"]["deny"])
        self.assertEqual(oct(self.state.stat().st_mode & 0o777), "0o700")

    # --- a real launch, through the fake ---------------------------------------------------------

    def file_request(self, name, text):
        (self.proj / "requests" / f"{name}.md").write_text(text + "\n")

    def test_request_run_launches_with_the_flags_and_a_clean_env(self):
        self.file_request("q-1", "what is queued?")
        r = self.run_cmd("request", "run", "q-1")
        self.assertEqual(r.returncode, 0, r.stderr)
        (call,) = self.session_calls()
        argv, env = call["argv"], call["env"]
        self.assertEqual(self.flag(argv, "--permission-mode"), "dontAsk")
        self.assertEqual(self.flag(argv, "--settings"), str(self.state / "settings.request.json"))
        self.assertEqual(self.flag(argv, "--setting-sources"), "project")
        self.assertEqual(self.flag(argv, "--mcp-config"), str(self.state / "mcp.json"))
        self.assertIn("--strict-mcp-config", argv)
        self.assertIn("--no-chrome", argv)
        self.assertIn("boundary", self.flag(argv, "--append-system-prompt"))
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env["ENABLE_CLAUDEAI_MCP_SERVERS"], "false")
        self.assertEqual(env["SHOT_SANDBOX"], "1")
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)          # no token: the interactive login, as prep does
        reply = (self.proj / "requests" / "q-1.reply.md").read_text()
        self.assertIn("boundary: templates/headless/settings.request.json; login: interactive", reply)
        self.assertIn("fake answer", reply)
        self.assertFalse((self.proj / "requests" / "q-1.running").exists())

    def test_build_request_with_the_token_uses_the_dedicated_dir(self):
        self.with_token()
        mem = self.home / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(self.proj)) / "memory"
        mem.mkdir(parents=True)
        (mem / "MEMORY.md").write_text("- a memory\n")
        self.file_request("b-1", "/continue B83")
        r = self.run_cmd("request", "run", "b-1")
        self.assertEqual(r.returncode, 0, r.stderr)
        (call,) = self.session_calls()
        argv, env = call["argv"], call["env"]
        self.assertEqual(argv[argv.index("-p") + 1], "/build B83")
        self.assertEqual(self.flag(argv, "--permission-mode"), "auto")
        self.assertEqual(self.flag(argv, "--settings"), str(self.state / "settings.build.json"))
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(self.state / "config"))
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], TOKEN_VALUE)
        self.assertNotIn("CLAUDE_HEADLESS_OAUTH_TOKEN", env)
        self.assertNotIn("SHOT_SANDBOX", env)
        cfg = json.loads((self.state / "config" / ".claude.json").read_text())
        self.assertTrue(cfg["projects"][str(self.proj)]["hasTrustDialogAccepted"])
        copied = self.state / "config" / "projects" / mem.parent.name / "memory" / "MEMORY.md"
        self.assertEqual(copied.read_text(), "- a memory\n")
        reply = (self.proj / "requests" / "b-1.reply.md").read_text()
        self.assertIn("settings.build.json; login: dedicated", reply)
        self.assertNotIn(TOKEN_VALUE, reply)

    def test_a_run_that_cannot_sign_in_says_so_and_starts_nothing(self):
        self.file_request("q-2", "hello")
        r = self.run_cmd("request", "run", "q-2", env={"FAKE_AUTH": "none"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.session_calls(), [])
        reply = (self.proj / "requests" / "q-2.reply.md").read_text()
        self.assertIn("not started", reply)
        self.assertIn("I couldn't start this request", reply)
        self.assertIn("claude setup-token", reply)

    def test_dedicated_only_refuses_the_fallback(self):
        self.file_request("q-3", "hello")
        r = self.run_cmd("request", "run", "q-3", env={"TODO_HEADLESS_LOGIN": "dedicated"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [])                  # not even auth status: there is no login to ask
        self.assertIn("refuses the fallback", (self.proj / "requests" / "q-3.reply.md").read_text())

    def test_inbox_is_always_the_narrow_boundary(self):
        name = "2026-09-30-try-build"
        (self.proj / "flint" / "inbox" / f"{name}.md").write_text("/build everything please\n")
        r = self.run_cmd("inbox", "run", name)
        self.assertEqual(r.returncode, 0, r.stderr)
        (call,) = self.session_calls()
        self.assertEqual(self.flag(call["argv"], "--permission-mode"), "dontAsk")
        self.assertEqual(self.flag(call["argv"], "--settings"), str(self.state / "settings.request.json"))
        self.assertEqual(call["env"]["TODO_INBOX"], name)
        self.assertIn("login interactive", (self.proj / "flint" / "outbox" / f"{name}.md").read_text())

    # --- doctor ---------------------------------------------------------------------------------

    def test_doctor_headless_green_and_loud_on_connectors_or_invalid_settings(self):
        r = self.run_cmd("doctor", "--headless")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("claude doctor accepts the stamped settings", r.stdout)
        self.assertIn("no claude.ai connectors", r.stdout)
        self.assertIn("[ warn ] unattended login: the interactive login", r.stdout)
        r = self.run_cmd("doctor", "--headless", env={"FAKE_CONNECTORS": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("connectors visible: claude.ai Gmail", r.stdout)
        r = self.run_cmd("doctor", "--headless", "--quick", env={"FAKE_INVALID": "1"})
        self.assertEqual(r.returncode, 1)
        self.assertIn("claude rejects part of the stamped settings", r.stdout)

    def test_doctor_names_a_project_allow_rule_nobody_reviewed(self):
        (self.proj / ".claude").mkdir()
        (self.proj / ".claude" / "settings.json").write_text(json.dumps(
            {"permissions": {"allow": ["Bash(shot *)", "Bash(rm -rf *)"]}}))
        r = self.run_cmd("doctor", "--headless", "--quick")
        self.assertIn("1 not reviewed in templates/headless/inherited.json: Bash(rm -rf *)", r.stdout)

    # --- build-night and projects-mcp ------------------------------------------------------------

    def test_build_night_dry_run_files_build_and_shows_the_launch(self):
        (self.proj / "ROADMAP.md").write_text("| B99 | a row | scope | acceptance | queued |\n")
        r = self.run_cmd("--dry-run", cmd=BUILD_NIGHT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would file requests/build-night-", r.stdout)
        self.assertIn("/build — the nightly build window", r.stdout)
        self.assertIn("variant: build (auto)", r.stdout)
        self.assertIn("--strict-mcp-config", r.stdout)
        # 2026-10-07: six hours, no fixed builder count, every builder Opus 5.5 (the alias pinned for the run)
        self.assertIn("a six-hour cap, hard", r.stdout)
        self.assertIn("no fixed ceiling on the count", r.stdout)
        self.assertNotIn("At most two builders", r.stdout)
        self.assertIn("ANTHROPIC_DEFAULT_OPUS_MODEL=claude-opus-5-5", r.stdout)
        self.assertNotIn("/continue", r.stdout)
        self.assertEqual(list((self.proj / "requests").iterdir()), [])

    def test_projects_mcp_says_build(self):
        r = self.run_cmd("tools", cmd=PROJECTS_MCP)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('"/build" picks up the next ROADMAP build item', r.stdout)
        self.assertNotIn("/continue", PROJECTS_MCP.read_text() + BUILD_NIGHT.read_text())


if __name__ == "__main__":
    unittest.main()
