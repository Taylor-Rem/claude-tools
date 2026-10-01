"""cloud against hand-written Laravel Cloud responses: no network, nothing written outside a temp dir.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

CLOUD_FIXTURES serves tests/fixtures/cloud/routes.json (copied to a temp dir so a test can
re-route). Every environment object and one log row carry PLANTED, a fake secret standing in
for the production app's environment variables: no command may ever print it.
`origin/main` comes from a throwaway clone of a throwaway bare repo, through `git ls-remote`.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLOUD = HERE.parent / "bin" / "cloud"
FIXTURES = HERE / "fixtures" / "cloud"
FIXTURES_401 = HERE / "fixtures" / "cloud-401"
PLANTED = "PLANTED-SECRET-b88-never-print-me"


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")).stdout.strip()


class CloudTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        bare = root / "origin.git"
        git("init", "-q", "--bare", "-b", "main", str(bare), cwd=root)
        cls.repo = root / "patchlamp"
        git("clone", "-q", str(bare), str(cls.repo), cwd=root)
        (cls.repo / "x").write_text("x")
        git("add", "x", cwd=cls.repo)
        git("commit", "-q", "-m", "x", cwd=cls.repo)
        git("push", "-q", "origin", "HEAD:main", cwd=cls.repo)
        cls.head = git("rev-parse", "HEAD", cwd=cls.repo)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.fx = Path(tempfile.mkdtemp(dir=self.tmp.name))
        for f in FIXTURES.iterdir():
            (self.fx / f.name).write_text(f.read_text().replace("{{HEAD}}", self.head))
        self.addCleanup(shutil.rmtree, self.fx, True)

    def route(self, key, target):
        routes = json.loads((self.fx / "routes.json").read_text())
        routes[key] = target
        (self.fx / "routes.json").write_text(json.dumps(routes))

    def run_cloud(self, *args, fixtures=None, env=None):
        e = dict(os.environ, CLOUD_FIXTURES=str(fixtures or self.fx), LARAVEL_CLOUD_TOKEN="fake|token",
                 CLAUDE_TOOLS_ENV=str(Path(self.tmp.name) / "no-env"), PATCHLAMP_REPO=str(self.repo))
        for k in ("CLOUD_APP", "CLOUD_ENV"):
            e.pop(k, None)
        e.update(env or {})
        r = subprocess.run([sys.executable, str(CLOUD), *args], capture_output=True, text=True, env=e,
                           timeout=60)
        self.assertNotIn(PLANTED, r.stdout + r.stderr, f"cloud {' '.join(args)} printed the planted secret")
        self.assertNotIn("fake|token", r.stdout + r.stderr)
        return r

    # --- deploys

    def test_deploys_newest_first_with_named_fields(self):
        r = self.run_cloud("deploys", "-n", "5")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "patchlamp / production: last 5 deploys, newest first")
        self.assertIn(f"deployment.succeeded {self.head[:7]}  main", lines[1])
        self.assertIn("Merge pull request #83 from patchlamp/dev", lines[1])
        self.assertIn("(0m49s)", lines[1])
        self.assertIn("bbbbbbb", lines[2])
        self.assertIn("build.failed", lines[3])
        self.assertIn("why: Step 'Running build commands' failed", lines[4])
        self.assertNotIn("long body", r.stdout)                      # first line of a message only

    def test_deploys_follows_the_second_page(self):
        r = self.run_cloud("deploys", "-n", "7", "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        ds = json.loads(r.stdout)
        self.assertEqual([d["id"] for d in ds], ["dep-6", "dep-5", "dep-4", "dep-3", "dep-2", "dep-1", "dep-0"])
        self.assertEqual(set(ds[0]), {"id", "status", "commit_hash", "commit_message", "branch_name",
                                      "commit_author", "failure_reason", "started_at", "finished_at"})

    def test_env_by_name(self):
        r = self.run_cloud("deploys", "--env", "staging")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("patchlamp / staging", r.stdout)
        self.assertIn("deployment.failed", r.stdout)

    def test_unknown_env_names_the_ones_it_sees(self):
        r = self.run_cloud("deploys", "--env", "nope")
        self.assertEqual(r.returncode, 1)
        self.assertIn("no environment called 'nope'", r.stderr)
        self.assertIn("staging, production", r.stderr)

    # --- status

    def test_status_live_matches_origin(self):
        r = self.run_cloud("status")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"live:        {self.head[:7]}  main", r.stdout)
        self.assertIn(f"origin/main: {self.head[:7]}  the live commit  [git ls-remote origin]", r.stdout)
        self.assertIn("in flight:   nothing", r.stdout)

    def test_status_behind_origin_exits_3(self):
        # origin moves on; Cloud still runs the old commit
        (self.repo / "y").write_text("y")
        git("add", "y", cwd=self.repo)
        git("commit", "-q", "-m", "y", cwd=self.repo)
        git("push", "-q", "origin", "HEAD:main", cwd=self.repo)
        try:
            r = self.run_cloud("status", "--json")
            self.assertEqual(r.returncode, 3, r.stderr)
            d = json.loads(r.stdout)
            self.assertFalse(d["up_to_date"])
            self.assertEqual(d["live"]["commit_hash"], self.head)
            self.assertNotEqual(d["origin"]["sha"], self.head)
            self.assertNotIn("environment_variables", r.stdout)
        finally:
            git("reset", "-q", "--hard", self.head, cwd=self.repo)
            git("push", "-q", "-f", "origin", "HEAD:main", cwd=self.repo)

    def test_status_reports_a_deploy_in_flight(self):
        self.route("GET /environments/env-1/deployments", "deploys-flying.json")
        r = self.run_cloud("status")
        self.assertEqual(r.returncode, 3)
        self.assertIn(f"in flight:   build.running  {self.head[:7]}", r.stdout)

    # --- wait

    def test_wait_returns_when_the_deploy_succeeds(self):
        self.route("GET /environments/env-1/deployments",
                   ["deploys-wait-0.json", "deploys-wait-1.json", "deploys-wait-2.json"])
        r = self.run_cloud("wait", self.head[:10], "--interval", "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("build.running", r.stderr)
        self.assertIn("deployment.running", r.stderr)
        self.assertTrue(r.stdout.startswith(f"deployed: deployment.succeeded {self.head[:7]}"), r.stdout)

    def test_wait_defaults_to_origin_main_and_returns_at_once_when_done(self):
        r = self.run_cloud("wait", "--interval", "0", "--timeout", "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("deployed:", r.stdout)

    def test_wait_on_a_failed_deploy_gives_the_reason(self):
        r = self.run_cloud("wait", "abcdef0", "--env", "staging", "--interval", "0")
        self.assertEqual(r.returncode, 1)
        self.assertRegex(r.stdout, r"^FAILED: deployment.failed +abcdef0  dev ")
        self.assertIn("reason (last lines):", r.stdout)
        self.assertIn("Table 'users' already exists", r.stdout)       # from GET /deployments/{id}, not the list

    def test_wait_times_out_with_exit_2(self):
        r = self.run_cloud("wait", "1234567", "--interval", "0", "--timeout", "0")
        self.assertEqual(r.returncode, 2)
        self.assertIn("gave up after 0s on 1234567: no deploy for it yet", r.stderr)

    # --- logs

    def test_logs_by_named_fields(self):
        r = self.run_cloud("logs", "--since", "2h")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertIn("3 log lines", lines[0])
        self.assertIn("queue worker started", lines[1])                 # oldest first
        self.assertIn("Stripe\\Exception\\AuthenticationException: Stripe call failed", lines[2])
        self.assertIn("200 GET /account/login/abcd…?… 42ms", lines[3])  # no token, no signature
        for gone in ("signature", "deadbeef", "203.0.113.9", "UA-should-not-show", "api_key"):
            self.assertNotIn(gone, r.stdout)

    def test_logs_errors_only_and_clamped_window(self):
        r = self.run_cloud("logs", "--errors", "--since", "3d")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("a day of logs", r.stderr)
        self.assertIn("1 log line,", r.stdout)

    def test_logs_without_permission_says_so(self):
        r = self.run_cloud("logs", "--env", "staging")
        self.assertEqual(r.returncode, 1)
        self.assertIn("this token can't read the logs", r.stderr)

    def test_deploy_logs(self):
        r = self.run_cloud("logs", "--deploy")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("finished   Cloning application source control repository (4.1s)", r.stdout)
        self.assertIn("deploy: no log available", r.stdout)

    # --- doctor

    def test_doctor_green(self):
        r = self.run_cloud("doctor")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("[ok] token accepted", r.stdout)
        self.assertIn("[ok] resolved patchlamp / production (running)", r.stdout)
        self.assertIn("[ok] logs readable", r.stdout)
        self.assertIn(f"[ok] origin/main {self.head[:7]} via git ls-remote origin", r.stdout)
        self.assertTrue(r.stdout.rstrip().endswith("all good"))

    def test_doctor_red_on_a_bad_token(self):
        r = self.run_cloud("doctor", fixtures=FIXTURES_401)
        self.assertEqual(r.returncode, 1)
        self.assertIn("[!!] token check failed: 401 from /applications: the token was refused", r.stdout)

    def test_doctor_red_without_a_token(self):
        r = self.run_cloud("doctor", env={"LARAVEL_CLOUD_TOKEN": ""})
        self.assertEqual(r.returncode, 1)
        self.assertIn("setenv.sh LARAVEL_CLOUD_TOKEN", r.stdout)

    def test_key_file_is_parsed_with_a_pipe_in_the_token(self):
        kf = self.fx / "env"
        kf.write_text("# keys\nOTHER=1\nLARAVEL_CLOUD_TOKEN=12|abc\n")
        r = self.run_cloud("doctor", env={"LARAVEL_CLOUD_TOKEN": "", "CLAUDE_TOOLS_ENV": str(kf)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"LARAVEL_CLOUD_TOKEN set (from {kf})", r.stdout)
        self.assertNotIn("12|abc", r.stdout + r.stderr)

    def test_every_command_keeps_the_planted_secret_in(self):
        # run_cloud asserts it on each call; this sweeps the rest of the surface once more
        for args in (["deploys", "--json", "-n", "7"], ["status", "--json"], ["logs", "-n", "100"],
                     ["wait", self.head, "--json", "--timeout", "0"], ["deploys", "--env", "staging", "--json"]):
            self.run_cloud(*args)


class ReadOnlyTest(unittest.TestCase):
    """GET only, by construction: one request site, built as a GET, and no other verb in the file."""

    def setUp(self):
        self.src = CLOUD.read_text()

    def test_no_other_http_verb_anywhere(self):
        for verb in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertIsNone(re.search(rf"\b{verb}\b", self.src, re.I), f"{verb} appears in bin/cloud")
        self.assertEqual(re.findall(r"method\s*=\s*['\"](\w+)", self.src), ["GET"])

    def test_one_request_and_it_is_a_get(self):
        self.assertEqual(self.src.count("urlopen("), 1)
        self.assertEqual(self.src.count("Request("), 1)
        self.assertIn('urllib.request.Request(url, method="GET"', self.src)
        self.assertNotIn("data=", self.src.split("def _get", 1)[1].split("\ndef ", 1)[0])
        for lib in ("import requests", "http.client", "subprocess.run([\"curl", "wrangler"):
            self.assertNotIn(lib, self.src)

    def test_nothing_is_written_to_disk(self):
        for w in ("write_text(", "write_bytes(", 'open(', "json.dump("):
            self.assertNotIn(w, self.src.replace("json.dumps(", "").replace("urlopen(", ""), f"bin/cloud calls {w}")


if __name__ == "__main__":
    unittest.main()
