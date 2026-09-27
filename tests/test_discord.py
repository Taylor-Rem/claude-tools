"""discord photos against recorded Discord responses: no network, files only in a temp dir.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

DISCORD_FIXTURES serves tests/fixtures/discord/routes.json for API calls and
tests/fixtures/discord/files/<name> for the CDN downloads.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DISCORD = HERE.parent / "bin" / "discord"
FIXTURES = HERE / "fixtures" / "discord"


class PhotosTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_discord(self, *args, env=None):
        e = dict(os.environ, DISCORD_FIXTURES=str(FIXTURES), DISCORD_BOT_TOKEN="fake",
                 CLAUDE_TOOLS_ENV=str(self.cwd / "no-env"))
        for k in ("RELAY_TRANSPORT", "RELAY_CHAT", "RELAY_THREAD"):
            e.pop(k, None)
        e.update(env or {})
        return subprocess.run([sys.executable, str(DISCORD), *args], capture_output=True, text=True,
                              env=e, cwd=self.cwd)

    def test_relay_run_lists_newest_first_into_incoming(self):
        (self.cwd / "incoming").mkdir()
        r = self.run_discord("photos", env={"RELAY_TRANSPORT": "discord", "RELAY_CHAT": "111"})
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.strip().splitlines()
        self.assertEqual(len(lines), 3, r.stdout)                  # the .txt is not a photo
        self.assertRegex(lines[0], r'^1\. Deuce, .+ ago: \(no text\)  incoming/discord/1553851259365101578-cat\.jpg$')
        self.assertIn('2. rob, ', lines[1])
        self.assertIn('"look at this goofball doing something absolutely ridiculous…"', lines[1])
        self.assertTrue(lines[1].endswith("[video: img describe it]"))
        self.assertIn("3. Kyle", lines[2])
        self.assertEqual((self.cwd / "incoming/discord/1553851259365101578-cat.jpg").read_bytes(), b"fakejpg")

    def test_n_caps_and_thread_wins(self):
        r = self.run_discord("photos", "-n", "1", "--dir", "out",
                             env={"RELAY_TRANSPORT": "discord", "RELAY_CHAT": "222", "RELAY_THREAD": "111"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.strip().splitlines()), 1)
        self.assertTrue((self.cwd / "out/1553851259365101578-cat.jpg").exists())

    def test_outside_a_relay_run_goes_to_tmp(self):
        r = self.run_discord("photos", "--channel", "333", "-n", "1")
        # 333 resolves but has no messages route: the fixture says not found
        self.assertNotEqual(r.returncode, 0)
        r = self.run_discord("photos", "-n", "1", env={"RELAY_CHAT": "111"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("/tmp/discord-photos/111/", r.stdout)
        shutil.rmtree("/tmp/discord-photos/111", ignore_errors=True)

    def test_nothing_there(self):
        r = self.run_discord("photos", env={"RELAY_TRANSPORT": "discord", "RELAY_CHAT": "222"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no photos or clips", r.stdout)

    def test_sms_run_is_told_why(self):
        r = self.run_discord("photos", env={"RELAY_TRANSPORT": "sms", "RELAY_CHAT": "+1555"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("chats --photos", r.stderr)

    def test_client_workspace_cannot_point_elsewhere(self):
        (self.cwd / ".client.json").write_text("{}")
        r = self.run_discord("photos", "--channel", "333",
                             env={"RELAY_TRANSPORT": "discord", "RELAY_CHAT": "111"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("only its own channel", r.stderr)


if __name__ == "__main__":
    unittest.main()
