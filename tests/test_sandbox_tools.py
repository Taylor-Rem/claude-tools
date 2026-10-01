"""B85 — the toolbelt half of the OS sandbox (plans/36-os-sandbox.md § Contract "Toolbelt").

`client exec` (lib/sandbox_tools.py) and the shim (sandbox/bin/tb), tested against a
fake broker and fake tools, so nothing here waits on the relay half or touches a live
account. Each case names the finding id it covers (private-docs/security/2026-09-30-*).

    python3 -m unittest tests.test_sandbox_tools   (from claude-tools/)

The end-to-end cases need bwrap and skip with a reason without it.
"""

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "lib"))
import sandbox_tools as ST  # noqa: E402

S = SourceFileLoader("site_mod_b85", str(ROOT / "bin" / "site")).load_module()
HAVE_BWRAP = Path(ST.BWRAP).exists()
NO_BWRAP = "bwrap isn't installed here (apt install bubblewrap)"


def git(repo, *args, env=None):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


class Base(unittest.TestCase):
    """A throwaway clients dir with acme (client), demo-service (demo) and other (another client)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(os.path.realpath(self.tmp.name))
        self.clients = self.t / "clients"
        self.state = self.t / "state"
        self.saved = {k: getattr(ST, k) for k in ("CLIENTS_DIR", "STATE", "MIRRORS", "REGISTRY", "TOOLBELT_ENV",
                                                  "LEDGER", "TOOL_BIN")}
        ST.CLIENTS_DIR = self.clients
        ST.STATE = self.state
        ST.MIRRORS = self.state / "mirrors"
        ST.LEDGER = self.state / "ledger.jsonl"
        self.cfg = self.t / "cfg"
        self.cfg.mkdir()
        ST.TOOLBELT_ENV = self.cfg / "env"
        ST.REGISTRY = self.cfg / "sites.json"
        ST.TOOLBELT_ENV.write_text("GEMINI_API_KEY=fake-gemini-value\nSTRIPE_KEY_PATCHLAMP=fake-stripe-value\n"
                                   "CLOUDFLARE_API_TOKEN=fake-cf-value\nPATCHLAMP_RELAY_SHARED_SECRET=fake-shared\n")
        os.environ["SANDBOX_NOTIFY"] = "0"
        for slug, meta in (("acme", {"role": "client"}), ("demo-service", {"role": "demo", "demo": True,
                                                                          "demo_publish": "static"}),
                           ("other", {"role": "client"})):
            ws = self.clients / slug
            (ws / "repos").mkdir(parents=True)
            (ws / "incoming").mkdir()
            (ws / ".client.json").write_text(json.dumps({"slug": slug, "name": slug.title(), **meta}))
        self.ws = self.clients / "acme"

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(ST, k, v)
        self.tmp.cleanup()

    def refused(self, *a, msg=""):
        with self.assertRaises(ST.Refused, msg=msg) as cm:
            ST.check_request(*a)
        self.assertTrue(str(cm.exception), "a refusal carries its reason (VISION § Rules 8)")
        return str(cm.exception)

    def make_repo(self, slug, name="site"):
        repo = self.clients / slug / "repos" / name
        repo.mkdir(parents=True)
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "t@t")
        git(repo, "config", "user.name", "t")
        git(repo, "remote", "add", "origin", f"git@github.com:patchlamp/{name}.git")
        (repo / "index.html").write_text("<h1>hi</h1>")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "initial")
        return repo


class RoleTable(Base):
    """sandbox-F3: the role table is what a demo may call."""

    def test_demo_cannot_call_money_or_data_tools(self):
        ws = str(self.clients / "demo-service")
        for tool, argv in (("pay", ["status"]), ("db", ["query", "SELECT 1"]), ("newsletter", ["status"]),
                           ("gbp", ["show"]), ("social", ["ls"]), ("connections", ["ls"]), ("discord", ["photos"])):
            why = self.refused("demo-service", "demo", ws, ".", tool, argv, msg=tool)
            self.assertIn(tool, why)

    def test_demo_site_is_publish_ls_status(self):
        ws = str(self.clients / "demo-service")
        ST.check_request("demo-service", "demo", ws, ".", "site", ["publish"])
        ST.check_request("demo-service", "demo", ws, ".", "site", ["ls"])
        for sub in ("new", "data", "mail", "shell", "checkout"):
            self.refused("demo-service", "demo", ws, ".", "site", [sub, "x"], msg=sub)

    def test_demo_img_no_video(self):
        ws = str(self.clients / "demo-service")
        ST.check_request("demo-service", "demo", ws, ".", "img", ["gen", "a pool"])
        self.refused("demo-service", "demo", ws, ".", "img", ["video", "a pool"])
        self.assertEqual(ST.VIDEO_CAPS["demo"]["IMG_VIDEO_MAX_SECONDS"], "0")

    def test_demo_git_push_fetch_not_pull(self):
        self.make_repo("demo-service")
        ws = str(self.clients / "demo-service")
        ST.check_request("demo-service", "demo", ws, ".", "git", ["-C", "repos/site", "push"])
        ST.check_request("demo-service", "demo", ws, ".", "git", ["-C", "repos/site", "fetch"])
        self.refused("demo-service", "demo", ws, ".", "git", ["-C", "repos/site", "pull"])

    def test_client_gets_its_tools(self):
        for tool, argv in (("pay", ["status"]), ("db", ["query", "SELECT 1"]), ("newsletter", ["status"]),
                           ("site", ["new", "x"]), ("img", ["video", "x"]), ("discord", ["photos"])):
            ST.check_request("acme", "client", str(self.ws), ".", tool, argv)
        self.refused("acme", "client", str(self.ws), ".", "discord", ["read", "#general"])
        self.refused("acme", "client", str(self.ws), ".", "leads", ["kit"])

    def test_project_and_workspace_come_from_the_relay(self):
        # relay-F3 / sandbox-F2: the workspace must be the project's, and its identity must agree
        self.refused("acme", "client", str(self.clients / "other"), ".", "img", ["gen", "x"])
        (self.ws / ".client.json").write_text(json.dumps({"slug": "other"}))
        self.refused("acme", "client", str(self.ws), ".", "img", ["gen", "x"])
        self.refused("acme", "admin", str(self.ws), ".", "img", ["gen", "x"])
        self.refused("../acme", "client", str(self.ws), ".", "img", ["gen", "x"])

    def test_identity_file_link_is_not_followed(self):
        real = self.t / "elsewhere.json"
        real.write_text(json.dumps({"slug": "acme"}))
        (self.ws / ".client.json").unlink()
        (self.ws / ".client.json").symlink_to(real)
        self.refused("acme", "client", str(self.ws), ".", "img", ["gen", "x"])

    def test_cwd_outside_falls_back_to_workspace(self):
        _, here = ST.check_request("acme", "client", str(self.ws), "../other", "img", ["gen", "x"])
        self.assertEqual(here, self.ws)

    def test_server_paths_match_site(self):
        self.assertEqual(tuple(ST.DEMO_SERVER_PATHS), tuple(S.DEMO_SERVER_PATHS))


class ArgvPaths(Base):
    """sandbox-F1 / relay-F1: an argument naming a path outside the workspace is refused."""

    def test_outside_paths_refused(self):
        envlink = self.ws / "incoming" / "keys.txt"
        envlink.symlink_to(ST.TOOLBELT_ENV)
        proclink = self.ws / "incoming" / "me.txt"
        proclink.symlink_to("/proc/self/environ")
        for argv in (["edit", str(ST.TOOLBELT_ENV), "x"], ["edit", "~/.ssh/id_ed25519"],
                     ["edit", "../other/.client.json"], ["edit", "incoming/keys.txt"],
                     ["edit", "incoming/me.txt"], ["gen", "--ref=/etc/passwd", "x"],
                     ["edit", "/proc/self/environ"], ["edit", str(self.clients / "other" / ".client.json")]):
            why = self.refused("acme", "client", str(self.ws), ".", "img", argv, msg=str(argv))
            self.assertIn("isn't in this workspace", why)

    def test_inside_paths_and_words_pass(self):
        (self.ws / "incoming" / "a.png").write_bytes(b"x")
        for argv in (["edit", "incoming/a.png", "make it brighter"], ["edit", str(self.ws / "incoming" / "a.png")],
                     ["gen", "a pool at dusk / with lights"], ["stock", "https://example.com/x.jpg"],
                     ["gen", "--out", "incoming/new.png", "a pool"]):
            ST.check_request("acme", "client", str(self.ws), ".", "img", argv)


class GitSettings(Base):
    """relay-F1 (hooks/config next to the key): a repo's git settings are checked before git runs."""

    def test_clean_clone_passes(self):
        self.make_repo("acme")
        self.assertIsNone(ST.repo_problem(self.ws, "site"))

    def test_added_settings_refused(self):
        repo = self.make_repo("acme")
        for key, val in (("core.hooksPath", "/tmp"), ("core.fsmonitor", "touch /tmp/x"),
                         ("core.sshCommand", "ssh -i x"), ("include.path", "/home/x/.gitconfig"),
                         ("filter.lfs.clean", "cat"), ("remote.origin.uploadpack", "sh"),
                         ("remote.origin.url", "file:///home/x/repo"), ("core.bare", "true")):
            git(repo, "config", key, val)
            why = ST.repo_problem(self.ws, "site")
            self.assertTrue(why, key)
            git(repo, "config", "--unset-all", key) if key != "remote.origin.url" else \
                git(repo, "config", key, "git@github.com:patchlamp/site.git")
            if key == "core.bare":
                git(repo, "config", "core.bare", "false")
        self.assertIsNone(ST.repo_problem(self.ws, "site"))

    def test_hooks_must_be_samples(self):
        repo = self.make_repo("acme")
        (repo / ".git" / "hooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n")
        self.assertIn("hook", ST.repo_problem(self.ws, "site"))

    def test_links_and_alternates_refused(self):
        repo = self.make_repo("acme")
        cfg = repo / ".git" / "config"
        real = self.t / "cfg-elsewhere"
        shutil.copy(cfg, real)
        cfg.unlink()
        cfg.symlink_to(real)
        self.assertTrue(ST.repo_problem(self.ws, "site"))
        cfg.unlink()
        shutil.copy(real, cfg)
        (repo / ".git" / "objects" / "info" / "alternates").write_text("/home/x/objects\n")
        self.assertIn("alternates", ST.repo_problem(self.ws, "site"))

    def test_refusal_wording(self):
        repo = self.make_repo("acme")
        git(repo, "config", "core.hooksPath", "/tmp")
        with self.assertRaises(ST.Refused) as cm:
            ST.check_repos(self.ws, "acme")
        self.assertEqual(str(cm.exception),
                         "repos/site's git settings were changed, so publishing is paused; Taylor's been told")


class Symlinks(Base):
    """sandbox-F1 (review amendment 1): a tool with a key in hand never follows a link out."""

    def test_site_export_refuses_committed_links(self):
        for target in ("/proc/self/environ", str(ST.TOOLBELT_ENV)):
            repo = self.t / f"r{abs(hash(target))}"
            repo.mkdir()
            git(repo, "init", "-q", "-b", "main")
            git(repo, "config", "user.email", "t@t")
            git(repo, "config", "user.name", "t")
            (repo / "index.html").write_text("<h1>x</h1>")
            (repo / "leak.txt").symlink_to(target)
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", "x")
            dest = self.t / f"out{abs(hash(target))}"
            dest.mkdir()
            with self.assertRaises(SystemExit, msg=target):
                S.export_tree(repo, dest)

    def test_site_export_keeps_inside_links(self):
        repo = self.make_repo("acme")
        (repo / "home.html").symlink_to("index.html")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "alias")
        dest = self.t / "out"
        dest.mkdir()
        self.assertGreaterEqual(S.export_tree(repo, dest), 1)

    def test_client_exec_refuses_site_with_outbound_link(self):
        repo = self.make_repo("acme")
        (repo / "leak.txt").symlink_to("/proc/self/environ")
        with self.assertRaises(ST.Refused) as cm:
            ST.exec_tool("acme", "client", str(self.ws), ".", "site", ["publish"])
        self.assertIn("outside this workspace", str(cm.exception))

    def test_newsletter_send_refuses_a_link(self):
        secret = self.t / "secret.md"
        secret.write_text("fake-secret-body")
        (self.ws / "issue.md").symlink_to(secret)
        env = dict(os.environ, RELAY_SANDBOX="1", RELAY_PROJECT="acme",
                   CLAUDE_TOOLS_ENV=str(self.t / "none"))
        r = subprocess.run([str(ROOT / "bin" / "newsletter"), "send", "Hello", "issue.md"], cwd=str(self.ws),
                           env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("outside this workspace", r.stderr + r.stdout)


FAKE_TOOL = r'''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
env = Path(os.environ["CLAUDE_TOOLS_ENV"])
keys = sorted(l.split("=", 1)[0] for l in env.read_text().splitlines() if "=" in l)
print(json.dumps({
    "tool": Path(sys.argv[0]).name, "argv": sys.argv[1:], "cwd": os.getcwd(), "keys": keys,
    "project": os.environ.get("RELAY_PROJECT"), "role": os.environ.get("RELAY_ROLE"),
    "sandbox": os.environ.get("RELAY_SANDBOX"), "keyfile_name": env.name,
    "ssh": Path.home().joinpath(".ssh").exists(),
    "probes": {p: Path(p).exists() for p in (Path(".probes").read_text().split(":") if Path(".probes").exists() else []) if p},
    "other": Path(sys.argv[-1]).exists() if sys.argv[-1].startswith("/") else None,
    "video": os.environ.get("IMG_VIDEO_MAX_SECONDS"),
    "registry": json.loads((env.parent / "sites.json").read_text()) if (env.parent / "sites.json").exists() else None,
}))
'''


@unittest.skipUnless(HAVE_BWRAP, NO_BWRAP)
class ToolSandbox(Base):
    """The tool sandbox holds only that tool's keys and the workspace (sandbox-F1, relay-F1)."""

    def setUp(self):
        super().setUp()
        self.bin = self.t / "fakebin"
        self.bin.mkdir()
        for t in ST.TOOLS:
            p = self.bin / t
            p.write_text(FAKE_TOOL)
            p.chmod(0o755)
        ST.TOOL_BIN = self.bin
        ST.REGISTRY.write_text(json.dumps({"acme": {"site": {"project": "acme-site"}},
                                           "other": {"x": {"project": "other-x"}}}))

    def run_exec(self, role, tool, argv, project="acme"):
        ws = self.clients / project
        out = self.t / "out.txt"
        with open(out, "w") as f:
            saved = os.dup(1)
            os.dup2(f.fileno(), 1)
            try:
                code = ST.exec_tool(project, role, str(ws), ".", tool, argv)
            finally:
                sys.stdout.flush()
                os.dup2(saved, 1)
                os.close(saved)
        return code, json.loads(out.read_text().strip().splitlines()[-1])

    def test_only_the_tools_keys_and_nothing_outside(self):
        code, r = self.run_exec("client", "img", ["gen", str(self.clients / "acme" / "incoming")])
        self.assertEqual(code, 0)
        self.assertEqual(r["keys"], ["GEMINI_API_KEY"])               # not Stripe, not Cloudflare
        self.assertEqual(r["project"], "acme")
        self.assertEqual(r["sandbox"], "1")
        self.assertFalse(r["ssh"])
        self.assertRegex(r["keyfile_name"], r"^env-[0-9a-f]{32}$")
        self.assertEqual(r["video"], "8")

    def test_other_workspace_and_real_key_file_absent(self):
        home = Path.home()
        probes = [str(ST.TOOLBELT_ENV), str(home / ".config/claude-tools/env"), str(home / ".ssh/id_ed25519"),
                  str(self.clients / "other" / ".client.json"), str(home / "projects/sms-relay/config.json"),
                  str(home / ".claude/.credentials.json"), str(home / ".claude-relay")]
        # (the argv check would refuse a path into another workspace, so the list goes in a file)
        (self.ws / ".probes").write_text(":".join(probes))
        code, r = self.run_exec("client", "pay", ["status"])
        self.assertEqual(code, 0)
        self.assertEqual({p: False for p in probes}, r["probes"])
        self.assertEqual(r["keys"], ["PATCHLAMP_RELAY_SHARED_SECRET", "STRIPE_KEY_PATCHLAMP"])

    def test_registry_copy_is_this_projects_row_for_db(self):
        code, r = self.run_exec("client", "db", ["query", "SELECT 1"])
        self.assertEqual(r["registry"], {"acme": {"site": {"project": "acme-site"}}})

    def test_site_writes_back_only_its_own_row(self):
        tool = self.bin / "site"
        tool.write_text(FAKE_TOOL + r'''
p = env.parent / "sites.json"
reg = json.loads(p.read_text())
reg["acme"]["site"]["indexnow_key"] = "k1"
reg["other"]["x"]["project"] = "hijacked"
p.write_text(json.dumps(reg))
''')
        code, _ = self.run_exec("client", "site", ["ls"])
        reg = json.loads(ST.REGISTRY.read_text())
        self.assertEqual(reg["acme"]["site"]["indexnow_key"], "k1")
        self.assertEqual(reg["other"]["x"]["project"], "other-x")

    def test_key_file_is_gone_after_the_call(self):
        self.run_exec("client", "img", ["gen", "x"])
        root = Path(ST._call_root())
        self.assertEqual([p for p in root.iterdir() if p.name.startswith("tb-")
                          and (p / "sites.json").exists() is False and any(p.glob("env-*"))], [])


@unittest.skipUnless(HAVE_BWRAP, NO_BWRAP)
class GitThroughMirror(Base):
    """git push goes workspace -> toolbelt mirror (fsck) -> the site's repo; demo gates apply."""

    def setUp(self):
        super().setUp()
        os.environ["SANDBOX_TEST_REMOTES"] = "1"
        self.remote = self.t / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", "-b", "main", str(self.remote)], check=True)

    def tearDown(self):
        os.environ.pop("SANDBOX_TEST_REMOTES", None)
        super().tearDown()

    def setup_site(self, slug):
        repo = self.make_repo(slug)
        ST.REGISTRY.write_text(json.dumps({slug: {"site": {"project": f"{slug}-site", "remote": str(self.remote)}}}))
        return repo

    def test_push_lands_and_updates_origin_main(self):
        repo = self.setup_site("acme")
        code = ST.exec_tool("acme", "client", str(self.ws), ".", "git", ["-C", "repos/site", "push"])
        self.assertEqual(code, 0)
        head = git(repo, "rev-parse", "HEAD")
        self.assertEqual(git(self.remote, "rev-parse", "main"), head)
        self.assertEqual(git(repo, "rev-parse", "refs/remotes/origin/main"), head)

    def test_force_and_other_refs_refused(self):
        self.setup_site("acme")
        for argv in (["push", "--force"], ["push", "-f"], ["push", "origin", "+main"], ["push", "origin", "other"],
                     ["push", "--delete", "origin", "main"], ["-c", "core.sshCommand=x", "push"]):
            with self.assertRaises(ST.Refused, msg=str(argv)):
                ST.exec_tool("acme", "client", str(self.ws), "repos/site", "git", argv)

    def test_changed_git_settings_pause_the_push(self):
        repo = self.setup_site("acme")
        git(repo, "config", "core.hooksPath", str(self.t))
        with self.assertRaises(ST.Refused) as cm:
            ST.exec_tool("acme", "client", str(self.ws), ".", "git", ["-C", "repos/site", "push"])
        self.assertIn("publishing is paused", str(cm.exception))
        self.assertNotEqual(subprocess.run(["git", "-C", str(self.remote), "rev-parse", "--verify", "-q", "main"],
                                           capture_output=True).returncode, 0)

    def test_demo_push_with_functions_refused(self):
        repo = self.setup_site("demo-service")
        git(repo, "tag", "golden")
        (repo / "functions").mkdir()
        (repo / "functions" / "x.js").write_text("export default 1")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "fn")
        ws = str(self.clients / "demo-service")
        with self.assertRaises(ST.Refused) as cm:
            ST.exec_tool("demo-service", "demo", ws, ".", "git", ["-C", "repos/site", "push"])
        self.assertIn("functions", str(cm.exception))
        with self.assertRaises(ST.Refused):
            ST.exec_tool("demo-service", "demo", ws, ".", "site", ["publish", "site"])

    def test_demo_page_edit_pushes(self):
        repo = self.setup_site("demo-service")
        git(repo, "tag", "golden")
        (repo / "index.html").write_text("<h1>new</h1>")
        git(repo, "commit", "-qam", "page")
        ws = str(self.clients / "demo-service")
        self.assertEqual(ST.exec_tool("demo-service", "demo", ws, ".", "git", ["-C", "repos/site", "push"]), 0)

    def test_fetch_and_pull(self):
        repo = self.setup_site("acme")
        ST.exec_tool("acme", "client", str(self.ws), ".", "git", ["-C", "repos/site", "push"])
        other = self.t / "other-clone"
        subprocess.run(["git", "clone", "-q", str(self.remote), str(other)], check=True)
        git(other, "config", "user.email", "t@t")
        git(other, "config", "user.name", "t")
        (other / "b.html").write_text("b")
        git(other, "add", "-A")
        git(other, "commit", "-qm", "b")
        git(other, "push", "-q", "origin", "main")
        self.assertEqual(ST.exec_tool("acme", "client", str(self.ws), "repos/site", "git", ["pull"]), 0)
        self.assertTrue((repo / "b.html").exists())

    def test_push_address_is_pinned(self):
        self.setup_site("acme")
        ST.exec_tool("acme", "client", str(self.ws), ".", "git", ["-C", "repos/site", "push"])
        moved = self.t / "moved.git"
        subprocess.run(["git", "init", "--bare", "-q", str(moved)], check=True)
        ST.REGISTRY.write_text(json.dumps({"acme": {"site": {"project": "acme-site", "remote": str(moved)}}}))
        with self.assertRaises(ST.Refused):
            ST.exec_tool("acme", "client", str(self.ws), ".", "git", ["-C", "repos/site", "push"])


class FakeBroker(threading.Thread):
    def __init__(self, path, reply_exit=7):
        super().__init__(daemon=True)
        self.path, self.reply_exit, self.requests = path, reply_exit, []
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(path)
        self.srv.listen(4)

    def run(self):
        while True:
            try:
                c, _ = self.srv.accept()
            except OSError:
                return
            with c:
                line = c.makefile("rb").readline()
                self.requests.append(json.loads(line))
                for msg in ({"o": base64.b64encode(b"out-line\n").decode()},
                            {"e": base64.b64encode(b"err-line\n").decode()}, {"exit": self.reply_exit}):
                    c.sendall((json.dumps(msg) + "\n").encode())


class Shim(Base):
    """sandbox/bin/tb: the broker protocol, the git split, and the no-broker sentence."""

    def setUp(self):
        super().setUp()
        self.shims = ROOT / "sandbox" / "bin"
        self.sock = str(self.t / "broker.sock")
        self.broker = FakeBroker(self.sock)
        self.broker.start()
        (self.ws / "repos" / "x").mkdir()

    def tearDown(self):
        self.broker.srv.close()
        super().tearDown()

    def run_shim(self, name, args, cwd, broker=True):
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.t)}
        if broker:
            env["PATCHLAMP_BROKER"] = self.sock
        return subprocess.run([str(self.shims / name), *args], cwd=str(cwd), env=env, capture_output=True, text=True)

    def test_every_keyed_tool_is_a_link_to_tb(self):
        for t in ST.SHIMS:
            self.assertEqual(os.readlink(self.shims / t), "tb", t)

    def test_request_and_streams(self):
        r = self.run_shim("site", ["publish", "x"], self.ws / "repos" / "x")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (7, "out-line\n", "err-line\n"))
        self.assertEqual(self.broker.requests[-1], {"v": 1, "tool": "site", "argv": ["publish", "x"],
                                                     "cwd": "repos/x"})

    def test_git_push_forwarded_rest_local(self):
        r = self.run_shim("git", ["-C", "repos/x", "push"], self.ws)
        self.assertEqual(r.returncode, 7)
        self.assertEqual(self.broker.requests[-1]["argv"], ["-C", "repos/x", "push"])
        self.assertEqual(self.broker.requests[-1]["cwd"], ".")
        n = len(self.broker.requests)
        r = self.run_shim("git", ["--version"], self.ws)
        self.assertEqual(r.returncode, 0)
        self.assertIn("git version", r.stdout)
        self.assertEqual(len(self.broker.requests), n)

    def test_no_broker(self):
        r = self.run_shim("img", ["gen", "x"], self.ws, broker=False)
        self.assertEqual(r.returncode, 3)
        self.assertIn("this tool runs through the relay; it isn't available here", r.stderr)


class Stamp(Base):
    """The stamp: role + demo_publish, and nothing read or written through a link (O_NOFOLLOW)."""

    def stamp(self, slug, *extra):
        env = dict(os.environ, CLIENTS_DIR=str(self.clients), RELAY_CONFIG=str(self.t / "none.json"),
                   CLAUDE_TOOLS_ENV=str(self.t / "no-env"))
        return subprocess.run([str(ROOT / "bin" / "client"), "new", slug, "--name", slug.title(),
                               "--shared-key", *extra], env=env, capture_output=True, text=True)

    def test_role_fields(self):
        self.assertEqual(self.stamp("fresh").returncode, 0)
        meta = json.loads((self.clients / "fresh" / ".client.json").read_text())
        self.assertEqual(meta["role"], "client")
        self.assertNotIn("demo_publish", meta)
        self.assertEqual(self.stamp("demo-new").returncode, 0)
        meta = json.loads((self.clients / "demo-new" / ".client.json").read_text())
        self.assertEqual((meta["role"], meta["demo_publish"]), ("demo", "static"))

    def test_notes_link_not_folded_and_playbook_link_not_written_through(self):
        self.assertEqual(self.stamp("fresh").returncode, 0)
        ws = self.clients / "fresh"
        secret = self.t / "secret.txt"
        secret.write_text("fake-SECRET-marker")
        (ws / "NOTES.md").symlink_to(secret)
        (ws / "PLAYBOOK.md").unlink()
        (ws / "PLAYBOOK.md").symlink_to(secret)
        r = self.stamp("fresh", "--restamp")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("fake-SECRET-marker", (ws / "CLAUDE.md").read_text())
        self.assertEqual(secret.read_text(), "fake-SECRET-marker")
        self.assertFalse((ws / "PLAYBOOK.md").is_symlink())

    def test_template_tells_patch_about_the_wall(self):
        self.assertEqual(self.stamp("fresh").returncode, 0)
        md = (self.clients / "fresh" / "CLAUDE.md").read_text()
        self.assertIn("## The sandbox", md)
        self.assertIn("RELAY_SANDBOX=1", md)
        for shout in ("CRITICAL", "NEVER", "MUST"):
            self.assertNotIn(shout, md.split("## The sandbox")[1].split("\n## ")[0])


if __name__ == "__main__":
    unittest.main()
