"""chats — a file someone sent (a PDF, a sheet, a Word file) shows as a file
chip with its name, type and size, linking the archived copy; a picture is
still an <img> (ROADMAP B35).

    python3 -m unittest tests.test_chats -q   (from claude-tools/)

A throwaway relay dir: state/messages.jsonl with one exchange that came with
a photo and the doc fixtures, archived under state/media/<project>/<date>/
the way the relay writes them.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import json
import re
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHATS = ROOT / "bin" / "chats"
FX = ROOT / "tests" / "fixtures" / "doc"
PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
                    "0000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


class ChatsFilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="chats-test-")
        relay = Path(cls.tmp) / "relay"
        media = relay / "state" / "media" / "testaurant" / "2026-09-28"
        media.mkdir(parents=True)
        (media / "photo-1.png").write_bytes(PNG)
        for f in ("stock-list.xlsx", "menu.pdf", "notes.docx", "items.csv"):
            shutil.copyfile(FX / f, media / f)
        rel = [f"media/testaurant/2026-09-28/{f}" for f in
               ("photo-1.png", "stock-list.xlsx", "menu.pdf", "notes.docx", "items.csv")]
        row = {"ts": "2026-09-28T10:00:00-06:00", "sender": "telegram:1", "sender_name": "Rosa",
               "project": "testaurant", "transport": "telegram", "text": "here's our stock list",
               "reply": "Got it.", "ok": True, "run": "r1", "photos": rel}
        (relay / "state" / "messages.jsonl").write_text(json.dumps(row) + "\n")
        (relay / "config.json").write_text(json.dumps({"bot_name": "Patch", "projects": {}}))
        cls.relay = relay
        cls.media = media

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def env(self):
        e = dict(os.environ)
        e["CLIENTS_DIR"] = str(Path(self.tmp) / "clients")
        e["CHATS_OUT"] = str(Path(self.tmp) / "out")
        return e

    def test_static_page_has_file_chips(self):
        out = Path(self.tmp) / "page.html"
        r = subprocess.run([sys.executable, str(CHATS), "--relay", str(self.relay), "--out", str(out)],
                           capture_output=True, text=True, env=self.env(), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1 picture(s), 4 file(s)", r.stdout)
        page = out.read_text()
        self.assertEqual(page.count("<img "), 1, "only the photo is an <img>")
        self.assertIn("data:image/png;base64,", page)
        for name, kind in (("stock-list.xlsx", "Excel"), ("menu.pdf", "PDF"), ("notes.docx", "Word"),
                           ("items.csv", "CSV")):
            size = (self.media / name).stat().st_size
            self.assertIn(f'href="{(self.media / name).resolve().as_uri()}"', page)
            self.assertIn(f"<span class=fname>{name}</span>", page)
            want = f"{size} B" if size < 1024 else f"{size / 1024:.1f} KB"
            self.assertIn(f"<span class=fmeta>{kind} · {want}</span>", page)

    def test_ls_counts_files(self):
        r = subprocess.run([sys.executable, str(CHATS), "ls", "--relay", str(self.relay)],
                           capture_output=True, text=True, env=self.env(), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("[1 picture(s), 4 file(s)]", r.stdout)
        self.assertIn("stock-list.xlsx", r.stdout)

    def test_serve_links_and_serves_the_file(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        p = subprocess.Popen([sys.executable, str(CHATS), "serve", "--relay", str(self.relay), "--port", str(port)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=self.env())
        try:
            base = f"http://127.0.0.1:{port}/"
            for _ in range(50):
                try:
                    page = urllib.request.urlopen(base, timeout=2).read().decode()
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                self.fail("chats serve didn't come up")
            self.assertNotIn("file://", page)
            m = re.search(r'<a class=file href="(photo/\d+)"[^>]*><span class=fname>stock-list.xlsx<', page)
            self.assertTrue(m, "the xlsx chip links the server's own URL")
            resp = urllib.request.urlopen(base + m.group(1), timeout=5)
            self.assertEqual(resp.read(), (self.media / "stock-list.xlsx").read_bytes())
            self.assertIn('filename="stock-list.xlsx"', resp.headers.get("Content-Disposition", ""))
        finally:
            p.terminate()
            p.wait(timeout=10)


class ChatsConversationTitleTest(unittest.TestCase):
    """B37: a browser row shows its conversation's title (the relay's thread_title)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="chats-conv-")
        relay = Path(cls.tmp) / "relay"
        (relay / "state").mkdir(parents=True)
        base = {"sender": "web:testaurant", "sender_name": "Testaurant", "project": "testaurant",
                "transport": "web", "ok": True, "run": "r", "photos": []}
        rows = [dict(base, id=1, ts="2026-09-28T10:00:00-06:00", text="raise the burger to $14", reply="Done.",
                     thread="conv:4", thread_title="Menu prices"),
                dict(base, id=2, ts="2026-09-28T10:05:00-06:00", text="untitled one", reply="Sure.",
                     thread="conv:5"),
                dict(base, id=3, ts="2026-09-28T10:06:00-06:00", sender="sms:+1", sender_name="Rosa",
                     transport="sms", text="hi", reply="hello", thread_title="never shown")]
        (relay / "state" / "messages.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (relay / "config.json").write_text(json.dumps({"bot_name": "Patch", "projects": {}}))
        cls.relay = relay

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_chats(self, *args):
        e = dict(os.environ, CLIENTS_DIR=str(Path(self.tmp) / "clients"), CHATS_OUT=str(Path(self.tmp) / "out"))
        r = subprocess.run([sys.executable, str(CHATS), *args, "--relay", str(self.relay)],
                           capture_output=True, text=True, env=e, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_ls_shows_the_title_on_web_rows(self):
        out = self.run_chats("ls", "--transport", "web")
        self.assertIn("Testaurant → testaurant (browser · “Menu prices”)", out)
        self.assertIn("Testaurant → testaurant (browser)", out)                 # no title: just the channel
        self.assertNotIn("Rosa", out)
        self.assertNotIn("never shown", self.run_chats("ls"))                   # a text has no conversation title

    def test_page_shows_the_title(self):
        page_path = Path(self.tmp) / "conv.html"
        self.run_chats("--transport", "web", "--out", str(page_path))
        page = page_path.read_text()
        self.assertIn("browser · “Menu prices”", page)

    def test_serve_shows_the_title(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        e = dict(os.environ, CLIENTS_DIR=str(Path(self.tmp) / "clients"))
        p = subprocess.Popen([sys.executable, str(CHATS), "serve", "--relay", str(self.relay), "--port", str(port)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=e)
        try:
            for _ in range(50):
                try:
                    page = urllib.request.urlopen(f"http://127.0.0.1:{port}/body", timeout=2).read().decode()
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                self.fail("chats serve didn't come up")
            self.assertIn("browser · “Menu prices”", page)
        finally:
            p.terminate()
            p.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
