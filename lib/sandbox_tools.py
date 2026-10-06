"""client exec — the keyed tools for a walled run (ROADMAP B85, plans/36-os-sandbox.md).

A client or demo run lives inside the relay's bwrap wall: its own workspace and
nothing else. The tools that need a platform key (site, db, img, newsletter, …)
and `git push|pull|fetch` can't work in there, so the run's copies of them are
shims (`sandbox/bin/tb`) that send the argv over the relay's broker socket. The
broker runs

    client exec --project P --role client|demo|owner --workspace WS --cwd C -- TOOL ARGV…

outside the run's sandbox, and this module is what that does:

  1. checks the request: the project and role come from the relay (argv), never
     from the workspace or the request; the workspace must be that project's;
     the tool must be in TOOLS and allowed for the role; every argv element that
     names an existing path must resolve inside the workspace;
  2. writes a key file holding only that tool's keys, under a name nobody can
     guess, for this call only;
  3. runs the tool in a *tool sandbox*: the same base the run sandbox has (/usr,
     a short list from /etc, fresh /proc /dev /tmp, an empty $HOME), plus the
     workspace rw, the toolbelt ro and the tool's own state files — and host
     networking in v1 (wrangler, Stripe, Google; plan § Residuals);
  4. for git, pushes through a toolbelt-owned bare mirror, so nothing from the
     workspace's repo config runs next to the SSH key, and only the push step
     sees the key.

Everything here treats the workspace as hostile: the run can leave any file or
symlink behind. Files are read beneath the workspace without following links
(`read_beneath`), and git only ever runs on the workspace inside a sandbox where
nothing outside the workspace exists.

Words a run reads (a refusal) say the reason and the way that works, in a normal
voice (VISION § Rules 8).

Test hooks, set only by tests (the broker never does, and nothing the run sends
reaches this process's environment): SANDBOX_TOOL_BIN (fake tools),
SANDBOX_TEST_REMOTES=1 (a local path as a push remote), SANDBOX_NOTIFY=0.
"""

import errno
import fcntl
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent              # the toolbelt
HOME = Path.home()
TOOLBELT_ENV = Path(os.environ.get("CLAUDE_TOOLS_ENV", HOME / ".config/claude-tools/env")).expanduser()
REGISTRY = TOOLBELT_ENV.parent / "sites.json"
CLIENTS_DIR = Path(os.environ.get("CLIENTS_DIR", "~/projects/clients")).expanduser()
STATE = Path(os.environ.get("CLAUDE_TOOLS_STATE", HOME / ".local/state/claude-tools")).expanduser()
MIRRORS = STATE / "mirrors"
LEDGER = Path(os.environ.get("IMG_LEDGER", STATE / "ledger.jsonl")).expanduser()
SSH_KEY = Path(os.environ.get("SANDBOX_SSH_KEY", HOME / ".ssh/id_ed25519")).expanduser()
KNOWN_HOSTS = Path(os.environ.get("SANDBOX_KNOWN_HOSTS", HOME / ".ssh/known_hosts")).expanduser()
PLAYWRIGHT = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", HOME / ".cache/ms-playwright")).expanduser()
TOOL_BIN = Path(os.environ.get("SANDBOX_TOOL_BIN", HERE / "bin")).expanduser()
BWRAP = shutil.which("bwrap") or "/usr/bin/bwrap"
GIT = "/usr/bin/git"

SANDBOX_BINDS = []   # every tool sandbox's bind list this process built (tests read it)
REFUSED = 2          # a request this module won't run (the reason is on stderr)

# ---- the manifest ---------------------------------------------------------------------------
#
# keys:     the toolbelt keys (by name) this tool's key file holds; nothing else is in it.
# state:    state it needs: "registry" (a copy of sites.json; rw for site, which writes back
#           only its own project's row), "ledger" (the cost ledger, appended), "playwright"
#           (the browsers, ro).
# roles:    which roles may call it, and for a role mapped to a tuple, only those
#           subcommands (argv[0]); None is every subcommand.
#
# GITHUB_TOKEN is in no tool's key list: git's environment would carry it (site's gh_env),
# and `site new`/`transfer` — the only users — are Taylor's from a terminal.
_ALL = None
# The client role's subcommands are what the client template and PLAYBOOK have Patch run; the
# rest of each tool (SITE_ADMIN work, platform grants, the rooms' credits, the GitHub side) is
# Taylor's from a terminal and is refused here with that reason.
SITE_CLIENT = ("publish", "ls", "doctor", "data", "mail", "handover", "stats", "counter",   # stats, counter: B127
               "domain", "address")   # B58: the owner's domain and the free address are Patch's (plan 27)
IMG_CLIENT = ("gen", "stock", "edit", "describe", "video", "styles", "info")
TOOLS = {
    "site": {"keys": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "SITE_ORG",
                      "PATCHLAMP_RELAY_SHARED_SECRET"],
             "state": ["registry"], "git": True,
             "roles": {"client": SITE_CLIENT, "owner": SITE_CLIENT, "demo": ("publish", "ls")}},
    "db": {"keys": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"], "state": ["registry"],
           "roles": {"client": _ALL, "owner": _ALL}},
    "img": {"keys": ["GEMINI_API_KEY", "PEXELS_API_KEY", "XAI_API_KEY"], "state": ["ledger"],
            "bins": ["ffmpeg", "ffprobe"],
            "roles": {"client": IMG_CLIENT, "owner": IMG_CLIENT, "demo": ("gen", "stock", "edit", "describe")}},
    "newsletter": {"keys": ["PATCHLAMP_RELAY_SHARED_SECRET"], "state": ["ledger"],
                   "roles": {"client": _ALL, "owner": _ALL}},
    "social": {"keys": ["PATCHLAMP_RELAY_SHARED_SECRET"], "state": [],
               "roles": {"client": ("post", "ls", "doctor"), "owner": ("post", "ls", "doctor")}},
    "gbp": {"keys": ["PATCHLAMP_RELAY_SHARED_SECRET"], "state": [],
            "roles": {"client": _ALL, "owner": _ALL}},
    "pay": {"keys": ["PATCHLAMP_RELAY_SHARED_SECRET", "STRIPE_KEY_PATCHLAMP", "STRIPE_TEST_KEY"], "state": [],
            "roles": {"client": _ALL, "owner": _ALL}},
    "connections": {"keys": ["PATCHLAMP_RELAY_SHARED_SECRET"], "state": [],
                    "roles": {"client": ("ls", "google", "doctor"), "owner": ("ls", "google", "doctor")}},
    "print": {"keys": ["GEMINI_API_KEY", "PEXELS_API_KEY"], "state": ["registry", "ledger", "playwright"],
              "bins": ["ffmpeg", "ffprobe"],
              "roles": {"client": _ALL, "owner": _ALL}},
    # B128: sign runs db inside its own call (same keys, the registry copy) and print's renderer.
    # A demo only lists: `new` would put any .md a stranger wrote into the workspace on the demo's
    # public site with a working sign form, and db itself has no demo role.
    "sign": {"keys": ["CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID"], "state": ["registry", "playwright"],
             "roles": {"client": _ALL, "owner": _ALL, "demo": ("ls", "doctor")}},
    "shot": {"keys": [], "state": ["playwright"],
             "roles": {"client": _ALL, "owner": _ALL, "demo": _ALL}},
    "discord": {"keys": ["DISCORD_BOT_TOKEN"], "state": [],
                "roles": {"client": ("photos",), "owner": ("photos",)}},
    "git": {"keys": [], "state": [], "git": True,
            "roles": {"client": ("push", "pull", "fetch"), "owner": ("push", "pull", "fetch"),
                      "demo": ("push", "fetch")}},
}
# Words after the subcommand that are Taylor's even when the subcommand isn't.
TAYLOR_ONLY = {"connections": {"grant", "revoke"}}
ROLES = ("client", "demo", "owner")
SHIMS = tuple(TOOLS)                       # what sandbox/bin/ links to tb
# Tools that run inside the wall itself, as real files in sandbox/bin (bin/<name> links to
# them): no key and only the workspace's files, so nothing to broker, and brokering would
# parse a stranger's file outside the wall instead (B100). Stdlib only: the wall mounts
# sandbox/bin alone, not lib/. Never in TOOLS, so the broker refuses them by name.
IN_WALL = ("doc",)

# `img video` caps by role (the same numbers the relay's agents.py sets for a run today:
# a stranger on a demo makes no videos; a client's clip is about 8s at 720p). The run's
# own environment doesn't cross the broker, so the role decides here.
VIDEO_CAPS = {
    "demo": {"IMG_VIDEO_MAX_SECONDS": "0", "IMG_VIDEO_PAID_MAX_SECONDS": "0", "IMG_VIDEO_MAX_USD": "0",
             "IMG_VIDEO_MAX_RESOLUTION": "720p", "IMG_VIDEO_CREDIT_PROOF": "1"},
    "client": {"IMG_VIDEO_MAX_SECONDS": "8", "IMG_VIDEO_PAID_MAX_SECONDS": "8", "IMG_VIDEO_MAX_USD": "1.00",
               "IMG_VIDEO_MAX_RESOLUTION": "720p", "IMG_VIDEO_CREDIT_PROOF": "1"},
    "owner": {},
}
# Passed through from this process's environment when the broker sets them (the channel the
# run came from: `discord photos` and `notify` use it). Never RELAY_PROJECT: that's --project.
PASS_ENV = ("RELAY_SENDER_KEY", "RELAY_TRANSPORT", "RELAY_CHAT", "RELAY_THREAD", "TZ")

# What a tool sandbox (and the push step) sees of /etc: name lookup, TLS, users, time,
# the dynamic linker, fonts and ImageMagick's policy. Nothing else from the host's /etc.
ETC = ("resolv.conf", "hosts", "nsswitch.conf", "host.conf", "gai.conf", "services", "protocols",
       "passwd", "group", "localtime", "timezone", "ssl", "ca-certificates", "ca-certificates.conf",
       "alternatives", "ld.so.cache", "ld.so.conf", "ld.so.conf.d", "fonts", "ImageMagick-6",
       "ImageMagick-7", "mime.types")

# The server-side pieces of a Pages deploy a demo in "static" mode may not change
# (bin/site DEMO_SERVER_PATHS; tests check the two stay equal).
DEMO_SERVER_PATHS = ("functions", "_worker.js", "_routes.json", "_headers",
                     "_redirects", "wrangler.toml", "wrangler.jsonc", "wrangler.json")

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
GITHUB_URL = re.compile(r"^(?:git@github\.com:|ssh://git@github\.com/|https://github\.com/)"
                        r"([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")

# A repo's .git/config may hold only these (the shape `git clone` + `site` write); anything
# else — includes, hooksPath, fsmonitor, a filter or diff driver, an sshCommand, an
# uploadpack — is a setting someone added, and publishing pauses until Taylor looks.
GIT_KEYS = [re.compile(p) for p in (
    r"core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase|precomposeunicode|symlinks)",
    r"remote\.origin\.(url|fetch)",
    r"branch\.[A-Za-z0-9_./-]+\.(remote|merge|rebase)",
    r"user\.(name|email)",
    r"pull\.(rebase|ff)",
    r"init\.defaultbranch",
)]

# Git settings every sandboxed git call (and every tool's git in a tool sandbox) gets on top
# of the repo's — configuration from the environment wins over the repo's: no hooks, no
# fsmonitor, no signing program, no editor or pager, no submodule fetches. A filter driver
# can't be switched off this way; the relay's self-bound .git keeps the checked config in
# place (plan § Contract), and check_repos refuses one.
_GIT_FORCE = (("core.hooksPath", "/dev/null"), ("core.fsmonitor", "false"), ("submodule.recurse", "false"),
              ("fetch.recurseSubmodules", "false"), ("commit.gpgSign", "false"), ("tag.gpgSign", "false"),
              ("core.pager", "cat"), ("core.editor", "true"), ("sequence.editor", "true"),
              ("core.askPass", ""), ("credential.helper", ""),
              ("diff.external", ""), ("core.gitProxy", ""), ("push.gpgSign", "false"),
              ("gpg.program", "/bin/false"), ("gpg.ssh.program", "/bin/false"), ("gpg.x509.program", "/bin/false"),
              ("core.alternateRefsCommand", ""), ("push.recurseSubmodules", "no"), ("gc.auto", "0"),
              ("maintenance.auto", "false"), ("core.sshCommand", ""),
              ("protocol.ext.allow", "never"), ("init.templateDir", ""))
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0",
           "GIT_CONFIG_COUNT": str(len(_GIT_FORCE)),
           **{f"GIT_CONFIG_KEY_{i}": k for i, (k, _) in enumerate(_GIT_FORCE)},
           **{f"GIT_CONFIG_VALUE_{i}": v for i, (_, v) in enumerate(_GIT_FORCE)}}
# Inside a tool sandbox there is no SSH key; a tool's own `git push` says where pushes go.
NO_SSH = ("sh -c 'echo \"pushes run through the relay: the next git push (or site publish) "
          "sends this commit\" >&2; exit 1'")


class Refused(Exception):
    """A request this module won't run; str() is the sentence the run reads."""


# ---- reading the hostile workspace ------------------------------------------------------------

def open_beneath(root, rel, flags=os.O_RDONLY):
    """An fd for root/rel, walking every component with O_NOFOLLOW, so no symlink
    anywhere on the way is followed. Raises OSError (ELOOP/ENOTDIR/ENOENT) otherwise."""
    parts = [p for p in Path(rel).parts if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts) or Path(rel).is_absolute():
        raise OSError(errno.EINVAL, f"not a plain relative path: {rel}")
    fd = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for p in parts[:-1]:
            nfd = os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nfd
        return os.open(parts[-1], flags | os.O_NOFOLLOW, dir_fd=fd)
    finally:
        os.close(fd)


def read_beneath(root, rel, limit=1 << 20):
    """The bytes of root/rel if it is a regular file reached without a symlink; else None.
    This is how anything outside the wall reads NOTES.md, memory.md, .client.json or a
    repo's git config: a symlink the run left there is never followed."""
    try:
        fd = open_beneath(root, rel)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as f:
            return f.read(limit)
    finally:
        os.close(fd)


def listdir_beneath(root, rel):
    """[(name, is_regular_file)] for a directory reached without symlinks; None if it isn't one."""
    try:
        fd = open_beneath(root, rel, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return None
    try:
        out = []
        for name in os.listdir(fd):
            st = os.stat(name, dir_fd=fd, follow_symlinks=False)
            out.append((name, stat.S_ISREG(st.st_mode)))
        return out
    finally:
        os.close(fd)


def inside(path, root):
    path, root = Path(path), Path(root)
    return path == root or root in path.parents


NOT_HERE = ("{what} isn't in this workspace, so it can't be opened here; the files you can reach "
            "are under ./ (incoming/ has what people sent, repos/ the sites)")


def argv_path_problem(argv, cwd, ws):
    """None, or why an argument can't be used: every argv element (or --opt=value) that
    names an existing path must resolve inside the workspace, and one that names a path
    outside it that doesn't exist is refused too (a tool might create it)."""
    for a in argv:
        if "\x00" in a:
            return "an argument held a NUL byte"
        if a.startswith("-"):
            if "=" not in a:
                continue
            a = a.split("=", 1)[1]
        if not a or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", a):
            continue                                    # empty, or a URL: not a path
        p = Path(os.path.expanduser(a)) if a.startswith("~") else Path(a)
        if not p.is_absolute():
            p = cwd / p
        try:
            os.lstat(p)
            exists = True
        except OSError:
            exists = False
        if exists:
            real = Path(os.path.realpath(p))
            if not inside(real, ws):
                return NOT_HERE.format(what=f"{a!r}" if len(a) < 80 else "that file")
        elif a.startswith(("/", "~")) or ".." in Path(a).parts:
            if not inside(Path(os.path.normpath(p)), ws):
                return NOT_HERE.format(what=f"{a!r}" if len(a) < 80 else "that path")
    return None


def symlinks_out(tree, ws):
    """Symlinks under `tree` (relative names) whose target resolves outside the workspace."""
    bad = []
    for dirpath, dirnames, filenames in os.walk(tree, followlinks=False):
        for n in dirnames + filenames:
            p = Path(dirpath) / n
            if p.is_symlink() and not inside(Path(os.path.realpath(p)), ws):
                bad.append(str(p.relative_to(ws)))
    return bad


# ---- git settings ---------------------------------------------------------------------------

def git_config_problem(config_text):
    """None, or the first key that isn't one `git clone` and `site` write."""
    tmp = tempfile.NamedTemporaryFile("wb", delete=False, prefix="gitcfg-")
    try:
        tmp.write(config_text)
        tmp.close()
        r = subprocess.run([GIT, "config", "--file", tmp.name, "--no-includes", "--list", "-z"],
                           capture_output=True, env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
                                                     "GIT_CONFIG_NOSYSTEM": "1"})
    finally:
        os.unlink(tmp.name)
    if r.returncode != 0:
        return "it doesn't parse"
    for item in r.stdout.decode("utf-8", "replace").split("\0"):
        if not item:
            continue
        key, _, val = item.partition("\n")
        if not any(rx.fullmatch(key) for rx in GIT_KEYS):
            return f"{key} is set"
        if key == "core.bare" and val.strip().lower() not in ("false", "0", "no", "off"):
            return "core.bare is on"
        if key == "remote.origin.url" and not GITHUB_URL.match(val.strip()):
            return "the origin isn't a GitHub repository"
    return None


def repo_problem(ws, name):
    """None, or why repos/<name>'s git can't be trusted next to a key."""
    rel = f"repos/{name}/.git"
    if listdir_beneath(ws, f"repos/{name}") is None:
        return "the repo isn't a plain directory"
    entries = listdir_beneath(ws, rel)
    if entries is None:
        return ".git isn't a plain directory"
    names = {n for n, _ in entries}
    for odd in ("commondir", "config.worktree"):
        if odd in names:
            return f".git/{odd} is there"
    if read_beneath(ws, f"{rel}/objects/info/alternates") is not None:
        return "objects/info/alternates is there"
    cfg = read_beneath(ws, f"{rel}/config")
    if cfg is None:
        return ".git/config isn't a plain file"
    why = git_config_problem(cfg)
    if why:
        return why
    hooks = listdir_beneath(ws, f"{rel}/hooks")
    if hooks is None and "hooks" in names:
        return ".git/hooks isn't a plain directory"
    for n, regular in hooks or []:
        if not (regular and n.endswith(".sample")):
            return f"a hook ({n}) is installed"
    return None


def repos_of(ws):
    d = ws / "repos"
    entries = listdir_beneath(ws, "repos") if d.exists() else None
    out = []
    for n, _ in entries or []:
        if listdir_beneath(ws, f"repos/{n}/.git") is not None or os.path.lexists(d / n / ".git"):
            out.append(n)
    return sorted(out)


def check_repos(ws, project, only=None):
    """Raise Refused if any repo's git settings were changed (Taylor hears once an hour)."""
    for name in repos_of(ws):
        if only and name != only:
            continue
        why = repo_problem(ws, name)
        if why:
            tell_taylor(project, f"sandbox: {project} repos/{name} git settings look changed ({why}); "
                                 f"publishing from it is paused until you look. client doctor {project}")
            raise Refused(f"repos/{name}'s git settings were changed, so publishing is paused; Taylor's been told")


def tell_taylor(project, text):
    """One notify per project per hour; best effort, never fails the call."""
    if os.environ.get("SANDBOX_NOTIFY", "1") == "0":
        return
    try:
        mark = STATE / "sandbox" / f"notified-{project}"
        mark.parent.mkdir(parents=True, exist_ok=True)
        import time
        if mark.exists() and time.time() - mark.stat().st_mtime < 3600:
            return
        mark.write_text(text + "\n")
        notify = shutil.which("notify") or str(HERE / "bin" / "notify")
        subprocess.run([notify, text], timeout=30, capture_output=True)
    except Exception:
        pass


# ---- the sandbox ----------------------------------------------------------------------------

def base_args(home=HOME, net=True):
    """bwrap's base: /usr ro, the /etc list, fresh /proc /dev /tmp, an empty $HOME.
    `net`: the tool sandbox keeps host networking in v1 (plan § Residuals)."""
    a = [BWRAP, "--unshare-all", "--die-with-parent", "--new-session", "--clearenv",
         "--ro-bind", "/usr", "/usr",
         "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib",
         "--symlink", "usr/lib64", "/lib64", "--symlink", "usr/sbin", "/sbin",
         "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/dev/shm", "--tmpfs", "/tmp",
         "--tmpfs", str(home)]
    if net:
        a.insert(2, "--share-net")
    for e in ETC:
        p = Path("/etc") / e
        if p.exists():
            a += ["--ro-bind", str(p), str(p)]
    return a


def sandbox_env(extra=None):
    env = {"PATH": f"{TOOL_BIN}:/usr/bin:/bin", "HOME": str(HOME), "LANG": "C.UTF-8",
           "RELAY_SANDBOX": "1", **GIT_ENV, "GIT_SSH_COMMAND": NO_SSH}
    for k in PASS_ENV:
        if os.environ.get(k):
            env[k] = os.environ[k]
    env.update(extra or {})
    return env


def setenv_args(env):
    a = []
    for k, v in env.items():
        a += ["--setenv", k, v]
    return a


def run_sandboxed(binds, env, argv, cwd, net=True, capture=False, timeout=None):
    cmd = base_args(net=net) + binds + setenv_args(env) + ["--chdir", str(cwd), "--", *argv]
    if capture:
        r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    r = subprocess.run(cmd, stdin=subprocess.DEVNULL, timeout=timeout)
    return r.returncode, "", ""


def toolbelt_keys(names):
    """{name: value} for the named keys from the toolbelt file. Values are only ever
    written to the per-call key file; never printed."""
    out = {}
    try:
        text = TOOLBELT_ENV.read_text()
    except OSError:
        return out
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() in names:
            out[k.strip()] = v.strip()
    return out


def registry_load():
    try:
        return json.loads(REGISTRY.read_text())
    except (OSError, ValueError):
        return {}


def registry_merge_back(project, copy_path):
    """`site` wrote its copy; take back only this project's row (under a lock)."""
    try:
        mine = json.loads(Path(copy_path).read_text()).get(project)
    except (OSError, ValueError):
        return
    lock = REGISTRY.with_suffix(".lock")
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        reg = registry_load()
        if mine is None or reg.get(project) == mine:
            return
        reg[project] = mine
        tmp = REGISTRY.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(reg, indent=2, sort_keys=True) + "\n")
        tmp.replace(REGISTRY)


# ---- git through the mirror -----------------------------------------------------------------

def sandboxed_git(ws, repo, args, binds=(), ro_ws=False):
    """git on the workspace's repo, inside a sandbox where nothing outside it exists."""
    b = ["--ro-bind" if ro_ws else "--bind", str(ws), str(ws), *binds]
    return run_sandboxed(b, sandbox_env(), [GIT, "-C", str(repo), *args], repo, net=False, capture=True)


def parse_git(argv, cwd, ws):
    """(repo_dir, verb, rest) from a forwarded `git …` argv; Refused otherwise."""
    d = cwd
    i = 0
    while i < len(argv) and argv[i].startswith("-"):
        a = argv[i]
        if a == "-C" and i + 1 < len(argv):
            d = d / argv[i + 1]
            i += 2
            continue
        if a.startswith("-C") and len(a) > 2:
            d = d / a[2:]
            i += 1
            continue
        if a in ("--no-pager", "-P"):
            i += 1
            continue
        raise Refused(f"git {a} isn't passed through here; `git -C repos/<name> push` (or pull, fetch) works")
    if i >= len(argv):
        raise Refused("only git push, pull and fetch run through the relay; the rest of git works here as usual")
    verb, rest = argv[i], argv[i + 1:]
    real = Path(os.path.realpath(d))
    if not inside(real, ws / "repos") or real == ws / "repos":
        raise Refused("git push/pull/fetch work in a site repo: `git -C repos/<name> push`")
    name = real.relative_to(ws / "repos").parts[0]
    return ws / "repos" / name, verb, rest


PUSH_FLAGS = {"-q", "--quiet", "-u", "--set-upstream", "-v", "--verbose", "--no-verify"}
FETCH_FLAGS = {"-q", "--quiet", "-v", "--verbose", "--prune", "-p", "--ff-only", "--no-rebase", "--all"}


def check_push_args(rest):
    pos = [a for a in rest if not a.startswith("-")]
    flags = [a for a in rest if a.startswith("-")]
    bad = [f for f in flags if f not in PUSH_FLAGS]
    ok_refs = ([], ["origin"], ["origin", "main"], ["origin", "HEAD"], ["origin", "HEAD:main"],
               ["origin", "main:main"])
    if bad or pos not in [list(r) for r in ok_refs]:
        raise Refused("pushes from here go to main on the site's own repo, without force: "
                      "`git -C repos/<name> push` (or `push origin main`) does that")


def check_fetch_args(rest, verb):
    pos = [a for a in rest if not a.startswith("-")]
    bad = [f for f in rest if f.startswith("-") and f not in FETCH_FLAGS]
    if bad or pos not in ([], ["origin"], ["origin", "main"]):
        raise Refused(f"`git -C repos/<name> {verb}` (or `{verb} origin main`) works from here; "
                      f"other remotes and options don't")


def push_url(project, name):
    """Where repos/<name> pushes and fetches: only the registry row for this project and repo
    (sites.json, which the run never sees a writable copy of). Never the repo's own config,
    and never trust on first use: a run can `git init repos/new` with any origin it likes,
    and the step that follows holds an account-wide SSH key. The mirror's pin stays as a
    second check."""
    entry = (registry_load().get(project) or {}).get(name)
    if entry is None:
        raise Refused(f"repos/{name} isn't one of this business's registered sites, so it can't be pushed "
                      f"or fetched from here; Taylor sets that up")
    url = entry.get("remote") or ""
    if os.environ.get("SANDBOX_TEST_REMOTES") == "1" and url.startswith("/"):
        return url
    m = GITHUB_URL.match(url)
    if not m:
        raise Refused(f"repos/{name} has no repository address on record, so it can't be pushed or fetched "
                      f"from here; Taylor sets that up")
    return f"git@github.com:{m.group(1)}/{m.group(2)}.git"


def registry_remote_problem(ws, project, name):
    """None, or why repos/<name>'s recorded address and its config origin disagree."""
    entry = (registry_load().get(project) or {}).get(name)
    if entry is None:
        return None
    rec = entry.get("remote")
    if not rec:
        return "no repository address recorded in the registry (client remotes --write)"
    if rec.startswith("/") and os.environ.get("SANDBOX_TEST_REMOTES") == "1":
        return None
    m = GITHUB_URL.match(origin_url(ws, name) or "")
    have = f"git@github.com:{m.group(1)}/{m.group(2)}.git" if m else None
    if have != rec:
        return f"its origin ({have or 'none'}) isn't the recorded address ({rec})"
    return None


def record_remotes(project, ws, write=False):
    """[(repo, url|None, note)]: each registered repo's origin, validated, recorded into its
    registry row as `remote` when `write` and the row has none. Run outside the wall."""
    out = []
    reg = registry_load()
    rows = reg.get(project) or {}
    changed = False
    for name, row in sorted(rows.items()):
        bad = repo_problem(ws, name) if (ws / "repos" / name).is_dir() else "no repo on disk"
        m = None if bad else GITHUB_URL.match(origin_url(ws, name) or "")
        url = f"git@github.com:{m.group(1)}/{m.group(2)}.git" if m else None
        if row.get("remote"):
            out.append((name, row["remote"], "already recorded" if row["remote"] == url
                        else f"recorded; the repo's origin now says {url or 'nothing'}"))
        elif not url:
            out.append((name, None, f"nothing recorded: {bad or 'no GitHub origin in its .git/config'}"))
        else:
            if write:
                row["remote"] = url
                changed = True
            out.append((name, url, "recorded" if write else "would record"))
    if changed:
        lock = REGISTRY.with_suffix(".lock")
        with open(lock, "a") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            cur = registry_load()
            for name, url, note in out:
                if note == "recorded" and name in (cur.get(project) or {}):
                    cur[project][name].setdefault("remote", url)
            tmp = REGISTRY.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(cur, indent=2, sort_keys=True) + "\n")
            tmp.replace(REGISTRY)
    return out


def add_remote(project, ws, name, write=False):
    """(url|None, note): register repos/<name>, a repo we don't host (no Pages project; its own push
    deploys it, like James's Worker), so a walled run can push and fetch it. Its origin is validated
    as record_remotes validates a hosted one and recorded as a row of its own, {"host": "external",
    "remote": URL}; `site`, `print` and `db` act on "cloudflare" rows only, so to them it's no row.
    Run outside the wall, by Taylor or a session on his word: the address is the whole of the
    trust, so it is read once, here, and printed for a person to see."""
    if not name or "/" in name or name.startswith("."):
        return None, "give the repo's directory name under repos/"
    row = (registry_load().get(project) or {}).get(name)
    if row is not None:
        return row.get("remote"), ("already registered" if row.get("remote")
                                   else "already registered without an address; `client remotes --write` records it")
    if not (ws / "repos" / name).is_dir():
        return None, "no repo on disk"
    bad = repo_problem(ws, name)
    m = None if bad else GITHUB_URL.match(origin_url(ws, name) or "")
    if not m:
        return None, f"nothing registered: {bad or 'no GitHub origin in its .git/config'}"
    url = f"git@github.com:{m.group(1)}/{m.group(2)}.git"
    if not write:
        return url, "would register (host external: pushed and fetched, never published by `site`)"
    lock = REGISTRY.with_suffix(".lock")
    with open(lock, "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        try:    # strict here: registry_load's {} on a bad file would write every other row away
            cur = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
        except (OSError, ValueError):
            return None, f"{REGISTRY.name} couldn't be read as JSON; nothing written"
        cur.setdefault(project, {}).setdefault(name, {"host": "external", "remote": url})
        tmp = REGISTRY.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cur, indent=2, sort_keys=True) + "\n")
        if REGISTRY.exists():
            shutil.copymode(REGISTRY, tmp)
        tmp.replace(REGISTRY)
    return url, "registered"


def origin_url(ws, name):
    """remote.origin.url from repos/<name>/.git/config, read without following links."""
    cfg = read_beneath(ws, f"repos/{name}/.git/config") or b""
    tmp = tempfile.NamedTemporaryFile("wb", delete=False, prefix="gitcfg-")
    try:
        tmp.write(cfg)
        tmp.close()
        r = subprocess.run([GIT, "config", "--file", tmp.name, "--no-includes", "--get", "remote.origin.url"],
                           capture_output=True, env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent",
                                                     "GIT_CONFIG_NOSYSTEM": "1"})
    finally:
        os.unlink(tmp.name)
    return r.stdout.decode().strip()


def _canonical(m):
    return m.parent / f"{m.name[:-4]}.config"


def mirror_problem(m):
    """None, or why the mirror isn't exactly what mirror_for made: config byte-for-byte the
    canonical copy (GIT_CONFIG_* can't unset a repo's url.*.insteadOf, push.gpgSign + gpg.program
    and the rest, so the whole file is compared), hooks only samples, no alternates or commondir."""
    canon = _canonical(m)
    try:
        if not canon.is_file() or (m / "config").read_bytes() != canon.read_bytes() or (m / "config").is_symlink():
            return "its git config isn't the one the toolbelt wrote"
    except OSError:
        return "its git config can't be read"
    for odd in ("commondir", "objects/info/alternates", "config.worktree"):
        if os.path.lexists(m / odd):
            return f"{odd} is there"
    hooks = m / "hooks"
    if hooks.is_symlink():
        return "hooks is a link"
    for h in (hooks.iterdir() if hooks.is_dir() else []):
        if h.is_symlink() or not h.is_file() or not h.name.endswith(".sample"):
            return f"a hook ({h.name}) is installed"
    return None


def mirror_for(project, name, url):
    m = MIRRORS / project / f"{name}.git"
    if not (m / "HEAD").exists():
        m.mkdir(parents=True, exist_ok=True)
        subprocess.run([GIT, "init", "--bare", "-q", str(m)], check=True, capture_output=True)
        for k, v in (("patchlamp.url", url), ("transfer.fsckObjects", "true"),
                     ("fetch.fsckObjects", "true"), ("receive.fsckObjects", "true"),
                     ("core.hooksPath", "/dev/null")):
            subprocess.run([GIT, "--git-dir", str(m), "config", k, v], check=True, capture_output=True)
        # The canonical copy keyed_git compares against before the key is ever mounted; it sits
        # beside the mirror, in a directory no sandbox ever binds.
        shutil.copyfile(m / "config", _canonical(m))
    pinned = subprocess.run([GIT, "--git-dir", str(m), "config", "--get", "patchlamp.url"],
                            capture_output=True, text=True).stdout.strip()
    if pinned != url:
        raise Refused(f"repos/{name}'s push address changed since its first push, so publishing is paused; "
                      f"Taylor's been told")
    return m


def keyed_git(mirror, args, url):
    """The one step that sees the SSH key: git on the toolbelt's own mirror, nothing
    from the workspace mounted."""
    why = mirror_problem(mirror)
    if why:
        project, name = mirror.parent.name, mirror.name[:-4]
        tell_taylor(project, f"sandbox: the toolbelt mirror for {project}/{name} was changed ({why}); "
                             f"pushes from it are paused. Look at {mirror} before deleting it.")
        raise Refused(f"repos/{name}'s publishing copy was changed ({why}), so publishing is paused; "
                      f"Taylor's been told")
    home = HOME
    binds = ["--bind", str(mirror), str(mirror)]
    env = sandbox_env({"GIT_SSH_COMMAND": "/usr/bin/ssh -F /dev/null -o BatchMode=yes -o IdentitiesOnly=yes "
                                          f"-o StrictHostKeyChecking=yes -i {home}/.ssh/key "
                                          f"-o UserKnownHostsFile={home}/.ssh/known_hosts"})
    if url.startswith("/"):                                  # tests only (SANDBOX_TEST_REMOTES)
        binds += ["--bind", url, url]
    else:
        binds += ["--ro-bind", str(SSH_KEY), f"{home}/.ssh/key",
                  "--ro-bind", str(KNOWN_HOSTS), f"{home}/.ssh/known_hosts"]
    return run_sandboxed(binds, env, [GIT, "--git-dir", str(mirror), *args], "/", net=True,
                         capture=True, timeout=300)


def git_push(ws, project, repo, role, quiet=False):
    """Workspace HEAD -> the mirror (fsck'd) -> main on the site's repo; then the workspace's
    origin/main, so `site publish`'s "unpushed" check passes. Returns the sha pushed."""
    name = repo.name
    if role == "demo":
        why = demo_push_problem(ws, repo)
        if why:
            raise Refused(why)
    url = push_url(project, name)
    why = registry_remote_problem(ws, project, name)
    if why:
        raise Refused(f"repos/{name}'s address changed ({why}), so publishing is paused; Taylor's been told")
    lock = MIRRORS / project / f"{name}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        m = mirror_for(project, name, url)
        code, out, err = run_sandboxed(["--ro-bind", str(ws), str(ws), "--bind", str(m), str(m)], sandbox_env(),
                                       [GIT, "--git-dir", str(m), "-c", "transfer.fsckObjects=true",
                                        "fetch", "-q", "--no-tags", str(repo), "+HEAD:refs/ws/head"],
                                       "/", net=False, capture=True)
        if code != 0:
            raise Refused(f"repos/{name} couldn't be read for the push: {(err or out).strip()[-300:]}")
        sha = subprocess.run([GIT, "--git-dir", str(m), "rev-parse", "refs/ws/head"],
                             capture_output=True, text=True).stdout.strip()
        code, out, err = keyed_git(m, ["push", "-q", url, "refs/ws/head:refs/heads/main"], url)
        if code != 0:
            tail = (err or out).strip().splitlines()[-3:]
            hint = (" The site's repo has commits this copy doesn't; `git -C repos/%s pull` first." % name
                    if any("rejected" in t or "fetch first" in t or "non-fast-forward" in t for t in tail) else "")
            raise Refused(f"the push didn't go through: {' '.join(tail)}{hint}")
        subprocess.run([GIT, "--git-dir", str(m), "update-ref", "refs/heads/main", sha], capture_output=True)
    sandboxed_git(ws, repo, ["update-ref", "refs/remotes/origin/main", sha])
    if not quiet:
        print(f"pushed {sha[:7]} to main", flush=True)
    return sha


def git_fetch(ws, project, repo, pull=False):
    name = repo.name
    url = push_url(project, name)
    why = registry_remote_problem(ws, project, name)
    if why:
        raise Refused(f"repos/{name}'s address changed ({why}), so publishing is paused; Taylor's been told")
    lock = MIRRORS / project / f"{name}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a") as lf:
        fcntl.flock(lf, fcntl.LOCK_EX)
        m = mirror_for(project, name, url)
        code, out, err = keyed_git(m, ["fetch", "-q", "--no-tags", url, "+refs/heads/*:refs/heads/*"], url)
        if code != 0:
            raise Refused(f"the fetch didn't go through: {(err or out).strip()[-300:]}")
        code, out, err = sandboxed_git(ws, repo, ["fetch", "-q", "--no-tags", str(m),
                                                  "+refs/heads/*:refs/remotes/origin/*"],
                                       binds=["--ro-bind", str(m), str(m)])
    if code != 0:
        raise Refused(f"the fetch didn't land in repos/{name}: {(err or out).strip()[-300:]}")
    if not pull:
        print("fetched origin", flush=True)
        return
    _, branch, _ = sandboxed_git(ws, repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    branch = branch.strip() or "main"
    code, out, err = sandboxed_git(ws, repo, ["merge", "--ff-only", "-q", f"refs/remotes/origin/{branch}"])
    if code != 0:
        raise Refused(f"this copy and the site's repo have both moved; `git -C repos/{name} merge origin/{branch}` "
                      f"joins them here, then push")
    print(f"pulled origin/{branch}", flush=True)


def demo_push_problem(ws, repo):
    """None if a demo may push/publish this repo; else the reason (sandbox-F3)."""
    meta = workspace_meta(ws)
    mode = meta.get("demo_publish", "static")
    if mode not in ("static", "off"):
        mode = "off"
    if mode == "off":
        return ("this is a demo site, so changes go live only on its nightly reset. Your edit is "
                "saved in the repo; the reset is what puts it on the web.")
    golden = demo_golden(meta.get("slug") or ws.name)
    if not golden:
        return ("this demo has no golden copy on record, so nothing publishes until its nightly reset "
                "(Taylor's `demo golden` makes one)")
    code, _, _ = sandboxed_git(ws, repo, ["cat-file", "-e", f"{golden}^{{commit}}"], ro_ws=True)
    if code != 0:
        return ("this demo's golden copy on record isn't in its repo, so nothing publishes until its "
                "nightly reset")
    # Against the sha bin/demo recorded outside the workspace, never the repo's `golden` ref,
    # which the run can move (sandbox-F3).
    _, out, _ = sandboxed_git(ws, repo, ["diff", "--name-only", golden, "HEAD"], ro_ws=True)
    hits = sorted({c for c in out.splitlines()
                   if any(c == p or c.startswith(p + "/") for p in DEMO_SERVER_PATHS)})
    if hits:
        return ("this demo can put page edits live, but not changes to how its site runs "
                f"({', '.join(hits[:6])}). Those stay until the nightly reset.")
    return None


DEMO_STATE = Path(os.environ.get("DEMO_STATE", STATE / "demo.json")).expanduser()


def demo_golden(slug):
    """The golden commit `demo golden` recorded for this demo, outside the workspace, or None.
    (testaurant's block is the file's top level; the others are under "demos".)"""
    try:
        data = json.loads(DEMO_STATE.read_text())
    except (OSError, ValueError):
        return None
    block = data if slug == "testaurant" else (data.get("demos") or {}).get(slug) or {}
    g = block.get("golden") or ""
    return g if re.fullmatch(r"[0-9a-f]{40}", g) else None


def ahead_of_origin(ws, repo):
    code, out, _ = sandboxed_git(ws, repo, ["rev-list", "--count", "refs/remotes/origin/main..HEAD"], ro_ws=True)
    if code != 0:
        code2, _, _ = sandboxed_git(ws, repo, ["rev-parse", "--verify", "--quiet", "refs/remotes/origin/main"], ro_ws=True)
        return code2 != 0          # no origin/main yet: everything is ahead
    return out.strip() not in ("", "0")


# ---- the request ----------------------------------------------------------------------------

def workspace_meta(ws):
    raw = read_beneath(ws, ".client.json")
    try:
        return json.loads(raw) if raw else {}
    except ValueError:
        return {}


def check_request(project, role, workspace, cwd, tool, argv):
    """(ws, cwd) resolved, or Refused. Pure checks; nothing runs."""
    if not SLUG.match(project or ""):
        raise Refused("this run has no project the relay recognises")
    if role not in ROLES:
        raise Refused("this run has no role the relay recognises")
    ws = Path(os.path.realpath(workspace))
    if ws != Path(os.path.realpath(CLIENTS_DIR / project)):
        raise Refused("this workspace isn't the run's project")
    if workspace_meta(ws).get("slug") != project:
        raise Refused("this workspace's identity doesn't match the run's project; Taylor's been told")
    here = Path(os.path.realpath(ws / (cwd or ".")))
    if not inside(here, ws):
        here = ws
    spec = TOOLS.get(tool)
    if not spec:
        raise Refused(f"{tool} isn't one of the tools that run through the relay")
    if role not in spec["roles"]:
        if role == "demo":
            raise Refused(f"`{tool}` isn't part of what a demo does (it acts on a real business's "
                          f"accounts); on a demo, edits to the site and images are what's on offer")
        raise Refused(f"`{tool}` isn't available to this run")
    allowed = spec["roles"][role]
    if tool == "git":
        _, verb, _ = parse_git(argv, here, ws)
        sub = verb
    else:
        sub = next((a for a in argv if not a.startswith("-")), "")
    if tool in TAYLOR_ONLY and TAYLOR_ONLY[tool] & set(argv):
        raise Refused(f"that part of `{tool}` is Taylor's, from his terminal; `{tool} ls` shows what's "
                      f"connected for this business")
    if allowed is not None and sub and sub not in allowed:
        if role == "demo":
            raise Refused(f"on a demo, `{tool}` does {', '.join(allowed)}; `{tool} {sub}` acts on more "
                          f"than the demo site, so it isn't available here")
        raise Refused(f"`{tool} {sub}` is Taylor's, from his terminal, so it isn't available from here; "
                      f"here `{tool}` does {', '.join(allowed)}")
    if tool != "git":
        why = argv_path_problem(argv, here, ws)
        if why:
            raise Refused(why)
    return ws, here


def publish_target(ws, cwd, argv):
    """The repo `site publish [name]` would publish, or None."""
    pos = [a for a in argv if not a.startswith("-")]
    if not pos or pos[0] != "publish":
        return None
    if len(pos) > 1:
        return ws / "repos" / pos[1]
    real = cwd
    if inside(real, ws / "repos") and real != ws / "repos":
        return ws / "repos" / real.relative_to(ws / "repos").parts[0]
    repos = repos_of(ws)
    return ws / "repos" / repos[0] if len(repos) == 1 else None


def exec_tool(project, role, workspace, cwd, tool, argv):
    """Run one brokered call. Returns the exit code; output goes to this process's
    stdout/stderr (the broker streams both back)."""
    ws, here = check_request(project, role, workspace, cwd, tool, argv)
    spec = TOOLS[tool]

    if tool == "git":
        repo, verb, rest = parse_git(argv, here, ws)
        check_repos(ws, project, only=repo.name)
        if verb == "push":
            check_push_args(rest)
            git_push(ws, project, repo, role, quiet="-q" in rest or "--quiet" in rest)
        else:
            check_fetch_args(rest, verb)
            git_fetch(ws, project, repo, pull=(verb == "pull"))
        return 0

    if spec.get("git"):
        check_repos(ws, project)
    if tool in ("site", "print"):
        for r in repos_of(ws):
            bad = symlinks_out(ws / "repos" / r, ws)
            if bad:
                raise Refused(f"repos/{r} has a link to a file outside this workspace ({bad[0]}), and "
                              f"{tool} won't follow it there; remove the link (git rm) and try again")

    target = publish_target(ws, here, argv) if tool == "site" else None
    if target is not None and target.is_dir():
        if role == "demo":
            why = demo_push_problem(ws, target)
            if why:
                raise Refused(why)
        if ahead_of_origin(ws, target):
            git_push(ws, project, target, role, quiet=True)

    pushed, stage_root = {}, None
    call = Path(tempfile.mkdtemp(prefix="tb-", dir=_call_root()))
    try:
        cfgdir = HOME / ".config" / "claude-tools"
        keyname = f"env-{secrets.token_hex(16)}"
        keys = toolbelt_keys(spec["keys"])
        fd = os.open(call / keyname, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("".join(f"{k}={v}\n" for k, v in keys.items()))
        binds = ["--ro-bind", str(HERE), str(HERE)]
        nm = HERE / "node_modules"
        if nm.is_symlink() and nm.resolve().is_dir():          # a worktree's link to the main checkout's
            binds += ["--ro-bind", str(nm.resolve()), str(nm.resolve())]
        if not inside(TOOL_BIN, HERE):
            binds += ["--ro-bind", str(TOOL_BIN), str(TOOL_BIN)]
        binds += ["--bind", str(ws), str(ws)]
        if "registry" in spec["state"]:
            reg = registry_load()
            reg = {project: reg[project]} if project in reg else {}     # this business's rows only
            (call / "sites.json").write_text(json.dumps(reg, indent=2, sort_keys=True) + "\n")
        styles = cfgdir / "img-styles.json"
        if tool in ("img", "print") and styles.is_file():
            shutil.copy(styles, call / "img-styles.json")
        binds += ["--bind", str(call), str(cfgdir)]
        env = {"CLAUDE_TOOLS_ENV": str(cfgdir / keyname), "RELAY_PROJECT": project, "RELAY_ROLE": role,
               "IMG_OUT_ROOT": str(ws / "generated" / "img")}
        if "ledger" in spec["state"]:
            LEDGER.parent.mkdir(parents=True, exist_ok=True)
            LEDGER.touch(exist_ok=True)
            binds += ["--bind", str(LEDGER), str(LEDGER)]
            env["IMG_LEDGER"] = str(LEDGER)
        if tool in ("img", "print"):
            env.update(VIDEO_CAPS[role])
        if tool == "site" and DEMO_STATE.is_file():            # the demo publish gate's golden record, ro
            binds += ["--ro-bind", str(DEMO_STATE), str(DEMO_STATE)]
            env["DEMO_STATE"] = str(DEMO_STATE)
        if "playwright" in spec["state"] and PLAYWRIGHT.is_dir():
            binds += ["--ro-bind", str(PLAYWRIGHT), str(PLAYWRIGHT)]
            env["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT)
        tbin = []
        for b in spec.get("bins", []):
            # A binary outside /usr (ffmpeg is a static build in ~/.local/bin here) is bound
            # read-only at /opt/patchlamp/tbin/<name>, named in the manifest (review amendment 2).
            found = shutil.which(b, path=os.environ.get("PATH", "") + f":{HOME}/.local/bin")
            if found and not found.startswith("/usr/"):
                binds += ["--ro-bind", os.path.realpath(found), f"/opt/patchlamp/tbin/{b}"]
                tbin.append(b)
        senv = sandbox_env(env)
        if tbin:
            senv["PATH"] = senv["PATH"] + ":/opt/patchlamp/tbin"
        if tool == "site":
            binds, senv, pushed, stage_root = site_mirrors(ws, project, binds, senv)
        SANDBOX_BINDS.append(list(binds))
        code, _, _ = run_sandboxed(binds, senv, [str(TOOL_BIN / tool), *argv], here)
        if tool == "site" and (call / "sites.json").exists():
            registry_merge_back(project, call / "sites.json")
    finally:
        shutil.rmtree(call, ignore_errors=True)

    try:
        _carry_staged(pushed)
    finally:
        if stage_root:
            shutil.rmtree(stage_root, ignore_errors=True)
    return code


def _carry_staged(pushed):
    for name, (m, url, stage, before) in pushed.items():   # site's own commits (IndexNow key, site mail, …)
        try:
            after = _rev(stage, "refs/heads/main")
            if not after or after == before:
                continue
            # staging (written by the tool) -> the mirror, fsck'd, in the no-key, no-network
            # sandbox with staging read-only; then the keyed push from the mirror as always.
            c, out, err = run_sandboxed(["--ro-bind", str(stage), str(stage), "--bind", str(m), str(m)],
                                        sandbox_env(), [GIT, "--git-dir", str(m), "-c", "transfer.fsckObjects=true",
                                                        "fetch", "-q", "--no-tags", str(stage),
                                                        "+refs/heads/main:refs/ws/site"], "/", net=False, capture=True)
            if c != 0:
                raise Refused(f"its new commit couldn't be checked ({(err or out).strip()[-200:]})")
            c, out, err = keyed_git(m, ["push", "-q", url, "refs/ws/site:refs/heads/main"], url)
            if c != 0:
                raise Refused(f"{(err or out).strip().splitlines()[-1:] or ['?']}")
            sha = _rev(m, "refs/ws/site")
            subprocess.run([GIT, "--git-dir", str(m), "update-ref", "refs/heads/main", sha], capture_output=True)
        except Refused as e:
            print(f"note: repos/{name}'s new commit is saved, but didn't reach its repository yet ({e}); "
                  f"the next `git push` sends it", file=sys.stderr)


def _rev(mirror, ref):
    r = subprocess.run([GIT, "--git-dir", str(mirror), "rev-parse", "--verify", "-q", ref],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def site_mirrors(ws, project, binds, env):
    """`site` commits and pushes by itself (the IndexNow key file, `site mail`'s links, `site data`'s
    wrangler.toml). Inside the tool sandbox there's no key, and the real mirror (the repo the key is
    used on) is never mounted there. Each registered repo gets a fresh per-call staging bare repo,
    seeded from the mirror by toolbelt code (a local fetch: objects are copied, not hard-linked or
    shared by alternates, so nothing the tool does to staging reaches the mirror), and the repo's
    push address is rewritten to it (pushInsteadOf). Afterwards exec_tool fetches what landed into
    the mirror with fsck in the no-key sandbox and pushes from there. Repos without a registry address
    get nothing: their pushes fail with the NO_SSH sentence. Returns (binds, env, pushed, stage_root)."""
    pushed = {}
    extra = []
    stage_root = None
    for name in repos_of(ws):
        try:
            url = push_url(project, name)
            if registry_remote_problem(ws, project, name) or repo_problem(ws, name):
                continue
            m = mirror_for(project, name, url)
        except Refused:
            continue
        if mirror_problem(m):
            continue
        if stage_root is None:
            stage_root = Path(tempfile.mkdtemp(prefix="stage-", dir=_call_root()))
        stage = stage_root / f"{name}.git"
        subprocess.run([GIT, "init", "--bare", "-q", str(stage)], check=True, capture_output=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1"})
        subprocess.run([GIT, "--git-dir", str(stage), "fetch", "-q", "--no-tags", str(m),
                        "+refs/heads/*:refs/heads/*"], capture_output=True,
                       env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1"})
        binds = binds + ["--bind", str(stage), str(stage)]
        for u in {url, origin_url(ws, name)} - {""}:
            extra.append((f"url.{stage}.pushInsteadOf", u))
        pushed[name] = (m, url, stage, _rev(stage, "refs/heads/main"))
    if extra:
        n = int(env.get("GIT_CONFIG_COUNT", "0"))
        env = dict(env)
        for i, (k, v) in enumerate(extra, start=n):
            env[f"GIT_CONFIG_KEY_{i}"] = k
            env[f"GIT_CONFIG_VALUE_{i}"] = v
        env["GIT_CONFIG_COUNT"] = str(n + len(extra))
    return binds, env, pushed, stage_root


def _call_root():
    base = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "claude-tools-calls"
    base.mkdir(mode=0o700, parents=True, exist_ok=True)
    return str(base)


def main_exec(a):
    """`client exec` entry point (argparse namespace from bin/client)."""
    argv = list(a.argv or [])
    if argv and argv[0] == "--":
        argv = argv[1:]
    if not argv:
        print("client exec: no tool given", file=sys.stderr)
        return REFUSED
    if not Path(BWRAP).exists():
        print("this tool can't start right now: the sandbox (bwrap) isn't installed. Taylor's been told.",
              file=sys.stderr)
        tell_taylor(a.project or "unknown", "sandbox: bwrap is missing, so no keyed tool can run. install.sh checks it.")
        return REFUSED
    tool, rest = argv[0], argv[1:]
    try:
        return exec_tool(a.project, a.role, a.workspace, a.cwd, tool, rest)
    except Refused as e:
        print(str(e), file=sys.stderr)
        return REFUSED
