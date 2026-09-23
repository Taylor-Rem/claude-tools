"""social against a fake patchlamp.com: no network, no Meta, nothing posted.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

A local HTTP server answers the /internal/relay/... endpoints the way the
site does (patchlamp tests/Feature/SocialTest.php pins the real ones) and
records what the tool sent; a stub `gbp` on PATH stands in for Google.
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOCIAL = HERE.parent / "bin" / "social"

PAGE = {"id": 7, "project": "patchlamp", "kind": "meta", "status": "connected", "label": "Patchlamp",
        "external_id": "1397225596800626", "instagram": "patchlamp"}


class Fake(BaseHTTPRequestHandler):
    state = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        s = self.state
        s["sent"].append({"method": "GET", "path": self.path, "auth": self.headers.get("Authorization")})
        if self.path.endswith("/social"):
            return self._send(200, {"pages": s["pages"], "x": s.get("x", []), "posts": s["posts"]})
        if self.path.endswith("/connections"):
            return self._send(200, {"connections": s["google"]})
        self._send(404, {"message": "could not be found"})

    def do_POST(self):
        s = self.state
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        s["sent"].append({"method": "POST", "path": self.path, "body": body})
        if self.path.endswith("/x/grant-url"):
            return self._send(200, {"url": "https://patchlamp.com/connect/x/grant?project=patchlamp&signature=abc"})
        if self.path.endswith("/grant-url"):
            return self._send(200, {"url": "https://patchlamp.com/connect/meta/grant?project=patchlamp&signature=abc", "reviewed": False})
        if self.path.endswith("/social"):
            if not s["pages"] and not s.get("x"):
                return self._send(409, {"error": "no Facebook Page is connected on this project"})
            res = {n: {"ok": True, "id": "1", "url": f"https://{n}.example/p/1"} for n in body.get("networks", [])}
            if s.get("ig_refuses") and "instagram" in res:
                res["instagram"] = {"ok": False, "error": "(#200) not authorized (code 200)"}
            return self._send(201, {"post": {"id": 1, "status": "posted", "results": res,
                                             "image_url": "https://patchlamp.com/social/media/abc.jpg"}})
        self._send(404, {"message": "could not be found"})


class SocialTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        Fake.state = {"sent": [], "pages": [PAGE], "posts": [], "google": []}
        self.server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.photo = self.dir / "pho.png"
        subprocess.run(["magick", "-size", "1200x1200", "xc:orange", str(self.photo)], check=True)
        # a stub gbp that records its argv
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        (self.bin / "gbp").write_text("#!/bin/sh\necho \"$@\" >> \"$GBP_ARGS\"\necho 'Posted to Google.'\n")
        (self.bin / "gbp").chmod(0o755)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def run_social(self, *args, cwd=None):
        env = dict(os.environ, PATCHLAMP_URL=f"http://127.0.0.1:{self.server.server_port}",
                   PATCHLAMP_RELAY_SHARED_SECRET="shh", CLAUDE_TOOLS_ENV=str(self.dir / "no-env"),
                   SOCIAL_DIR=str(self.dir / "social"), GBP_ARGS=str(self.dir / "gbp-args"),
                   PATH=f"{self.bin}:{os.environ['PATH']}")
        return subprocess.run([sys.executable, str(SOCIAL), *args], capture_output=True, text=True, env=env,
                              cwd=cwd or self.tmp.name)

    def posted(self):
        return [x for x in Fake.state["sent"] if x["method"] == "POST" and x["path"].endswith("/social")]

    # -- the acceptance line ----------------------------------------------------------

    def test_a_photo_and_a_line_go_to_facebook_and_instagram_as_a_jpeg(self):
        r = self.run_social("post", "patchlamp", str(self.photo), "Text it. Patched.")
        self.assertEqual(r.returncode, 0, r.stderr)
        [sent] = self.posted()
        self.assertEqual(sent["path"], "/internal/relay/projects/patchlamp/social")
        self.assertEqual(sent["body"]["caption"], "Text it. Patched.")
        self.assertEqual(sent["body"]["networks"], ["facebook", "instagram"])
        self.assertTrue(base64.b64decode(sent["body"]["image"]).startswith(b"\xff\xd8\xff"))   # PNG in, JPEG out
        self.assertIn("Facebook: https://facebook.example/p/1", r.stdout)
        self.assertIn("Instagram: https://instagram.example/p/1", r.stdout)
        self.assertIn("Google: not connected — skipped", r.stdout)
        logged = [json.loads(x) for x in (self.dir / "social" / "posted.jsonl").read_text().splitlines()]
        self.assertEqual(logged[0]["brand"], "patchlamp")
        self.assertEqual(logged[0]["links"]["instagram"], "https://instagram.example/p/1")

    def test_google_goes_through_gbp_with_the_public_image(self):
        Fake.state["google"] = [{"kind": "google", "status": "connected"}]
        r = self.run_social("post", "patchlamp", str(self.photo), "Fresh pho Saturday.")
        self.assertEqual(r.returncode, 0, r.stderr)
        args = (self.dir / "gbp-args").read_text()
        self.assertIn("--project patchlamp post Fresh pho Saturday. --photo https://patchlamp.com/social/media/abc.jpg", args)
        self.assertIn("Google: Posted to Google.", r.stdout)

    def test_a_refused_network_says_why_and_the_others_still_count(self):
        Fake.state["ig_refuses"] = True
        r = self.run_social("post", "patchlamp", str(self.photo), "x")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Instagram: not posted — (#200) not authorized (code 200)", r.stdout)
        self.assertIn("Facebook: https://facebook.example/p/1", r.stdout)

    # -- B24's "post" -------------------------------------------------------------------

    def test_post_with_no_image_puts_up_the_oldest_queued_draft_and_clears_it(self):
        r = self.run_social("queue", "add", "patchlamp", str(self.photo), "Day one.", "--pillar", "proof")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1. patchlamp", self.run_social("queue").stdout)
        r = self.run_social("post", "patchlamp")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.posted()[0]["body"]["caption"], "Day one.")
        self.assertIn("no drafts queued", self.run_social("queue").stdout)
        logged = json.loads((self.dir / "social" / "posted.jsonl").read_text().splitlines()[0])
        self.assertEqual(logged["pillar"], "proof")
        self.assertNotEqual(self.run_social("post", "patchlamp").returncode, 0)

    # -- refusals -----------------------------------------------------------------------

    def test_a_client_workspace_posts_only_for_itself(self):
        ws = self.dir / "fong"
        ws.mkdir()
        (ws / ".client.json").write_text(json.dumps({"slug": "fong"}))
        r = self.run_social("post", str(self.photo), "Pho.", cwd=ws)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.posted()[0]["path"], "/internal/relay/projects/fong/social")
        r = self.run_social("--project", "patchlamp", "post", str(self.photo), "Pho.", cwd=ws)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("can't post for another project", r.stderr)
        self.assertNotEqual(self.run_social("queue", cwd=ws).returncode, 0)

    def test_an_instagram_shape_it_would_refuse_is_caught_before_sending(self):
        wide = self.dir / "wide.png"
        subprocess.run(["magick", "-size", "1400x400", "xc:blue", str(wide)], check=True)
        r = self.run_social("post", "patchlamp", str(wide), "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Instagram takes 4:5 portrait to 1.91:1", r.stderr)
        self.assertEqual(self.posted(), [])
        r = self.run_social("post", "patchlamp", str(wide), "x", "--only", "facebook")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_nothing_connected_says_how_to_connect(self):
        Fake.state["pages"] = []
        r = self.run_social("post", "patchlamp", str(self.photo), "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("social connect", r.stdout + r.stderr)
        r = self.run_social("connect", "patchlamp")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("/connect/meta/grant?project=patchlamp", r.stdout)
        self.assertIn("Meta hasn't reviewed our app yet", r.stdout)

    def test_dry_run_posts_nothing(self):
        r = self.run_social("post", "patchlamp", str(self.photo), "x", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would post", r.stdout)
        self.assertEqual(self.posted(), [])


    # -- X, the third network -------------------------------------------------------------

    def test_x_goes_with_the_others_when_connected_and_takes_its_own_text(self):
        Fake.state["x"] = [{"kind": "x", "label": "@PatchLamp", "username": "PatchLamp"}]
        r = self.run_social("post", "patchlamp", str(self.photo), "Text it. Patched.", "--x-text", "Patched.")
        self.assertEqual(r.returncode, 0, r.stderr)
        [sent] = self.posted()
        self.assertEqual(sent["body"]["networks"], ["facebook", "instagram", "x"])
        self.assertEqual(sent["body"]["x_text"], "Patched.")
        self.assertIn("X: https://x.example/p/1", r.stdout)

    def test_x_alone_and_x_not_connected(self):
        Fake.state["pages"] = []
        Fake.state["x"] = [{"kind": "x", "label": "@PatchLamp"}]
        r = self.run_social("post", "patchlamp", str(self.photo), "x", "--only", "x")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.posted()[0]["body"]["networks"], ["x"])
        Fake.state["x"] = []
        r = self.run_social("post", "patchlamp", str(self.photo), "x", "--only", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("social connect --network x", r.stderr)

    def test_connect_x_prints_its_own_link(self):
        r = self.run_social("connect", "patchlamp", "--network", "x")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("/connect/x/grant?project=patchlamp", r.stdout)
        self.assertIn("logged into X", r.stdout)


if __name__ == "__main__":
    unittest.main()
