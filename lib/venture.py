"""The venture: which business the engine tools are working for (ROADMAP B146, plan 55 § 5.12).

`leads`, `outreach`, `prep`, `social`, `front`, `books` and `cloud` know no product. Everything they
say about the business behind them (its name, its site, who a letter is from and the town he writes
from, the sending domains, the preview host, the census, the claims file, the env names that point at
the site, the Stripe key, the Cloud app, the social brand) comes from one file:

    ventures/<name>/venture.toml          (beside bin/ and lib/ in the toolbelt)

    from venture import venture
    V = venture()                 # VENTURE in env, else the name in ventures/DEFAULT
    V.name, V.sender.from_name, V.outreach.domains, V.paths.claims, V.fill("text with {v:site_host}")

Which venture: `--venture NAME` on the command line (taken out of sys.argv by `from_argv()` before the
tool parses its own arguments, and put in VENTURE so a tool it runs inherits it), else VENTURE in env,
else ventures/DEFAULT. VENTURES_DIR points at another directory of ventures (tests).

Every field in FIELDS is required and typed; a missing, extra or mistyped field is a VentureError that
names the file and the field, and it exits the tool with that sentence (VentureError is a SystemExit)
rather than letting a tool put a wrong or empty name in front of a stranger.

Not a framework (plan 55 § 5.12): one file, one reader, no plugins. tests/test_portable.py takes its
needles from these values and fails when one appears in an engine file.
"""

import importlib.util
import os
import re
import sys
import tomllib
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent

# dotted field -> type. `list[str]` and `list[float]` are checked element by element.
FIELDS = {
    "name": str, "slug": str, "tenant": str, "prices_module": str, "legal_name": str, "brand_line": str, "mascot": str, "site": str, "site_host": str,
    "sender.first_name": str, "sender.from_name": str, "sender.reply_email": str, "sender.town": str,
    "sender.state": str, "sender.state_name": str, "sender.home": "list[float]",
    "sender.postal_address_env": str, "sender.phone_env": str, "sender.demo_number_env": str,
    "sender.sample_address": str, "sender.sample_phone": str, "sender.demo_number": str,
    "outreach.domains": "list[str]", "outreach.link_example": str, "outreach.campaign": str,
    "previews.host": str, "previews.project": str, "previews.claim_start": str, "previews.badge": str,
    "previews.tools_url": str, "previews.templates_url": str,
    "addresses.zone": str,
    "paths.census": str, "paths.claims": str, "paths.brand": str, "paths.prices": str, "paths.repo": str,
    "paths.portrait": str, "paths.topics": str,
    "env.site_url": str, "env.relay_secret": str, "env.repo": str,
    "money.stripe_key": str, "money.legal_stripe_key": str,
    "cloud.app": str,
    "social.brand": str, "social.handle": str,
}


class VentureError(SystemExit):
    """A venture that can't be read. A SystemExit, so an uncaught one ends the tool with its sentence."""

    def __init__(self, msg):
        super().__init__(f"venture: {msg}")
        self.msg = msg


class Section:
    """Attribute access over one table of the file (V.sender.town)."""

    def __init__(self, data):
        for k, v in data.items():
            setattr(self, k, Section(v) if isinstance(v, dict) else v)

    def __repr__(self):
        return f"Section({vars(self)!r})"


class Venture(Section):
    def __init__(self, name, path, data):
        super().__init__(data)
        self.venture_name, self.path = name, path

    def get(self, dotted):
        """`sender.town`, or `outreach.domains.0` for an item of a list."""
        obj = self
        for part in dotted.split("."):
            obj = obj[int(part)] if part.isdigit() else getattr(obj, part)
        return obj

    FILTERS = {"upper": str.upper, "lower": str.lower, "name": lambda x: x.rsplit("/", 1)[-1],   # a path's file name
               # an address as an env name's tail, the way outreach names a mailbox's password
               "envname": lambda x: re.sub(r"[^A-Za-z0-9]", "_", x).upper()}

    def fill(self, text):
        """`{v:sender.town}` in a text -> the venture's value; `{v:outreach.domains.0|envname}` passes it
        through one of FILTERS. Only `{v:…}` is touched, so a string that goes through str.format()
        afterwards keeps its own braces."""
        def one(m):
            value = str(self.get(m.group(1)))
            return self.FILTERS[m.group(2)](value) if m.group(2) else value
        return re.sub(r"\{v:([a-z0-9_.]+)(?:\|([a-z]+))?\}", one, text)

    def prices(self):
        """The venture's prices module (`prices_module`, a .py beside venture.toml; today's is a symlink to
        lib/prices.py): HOSTING_PRICE, LIGHT_PRICE, STARTER_PRICE, PRICE_LINE, PRICES_LINE and letter_sha()."""
        if getattr(self, "_prices", None) is None:
            path = self.path.parent / self.prices_module
            spec = importlib.util.spec_from_file_location(f"venture_prices_{self.venture_name.replace('-', '_')}", path)
            if spec is None or not path.exists():
                raise VentureError(f"{self.path}: prices_module {self.prices_module!r} isn't a file beside it")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self._prices = mod
        return self._prices

    def price_needles(self):
        """Every dollar amount the prices module says ("$7", "$1,500"), for tests/test_portable.py."""
        mod = self.prices()
        out = set()
        for k, v in vars(mod).items():
            if isinstance(v, str) and not k.startswith("_"):
                out |= set(re.findall(r"\$\d[\d,]*\d|\$\d", v))
        return sorted(out)

    def needles(self):
        """The literals that say which business this is, for tests/test_portable.py: the name and slug, the
        legal name, every host and domain, the reply address, the from-name, the town, the demo line's
        number, the census file's name. Lower case; the test matches them case-insensitively."""
        hosts = [self.site_host, self.previews.host, self.addresses.zone, *self.outreach.domains,
                 self.sender.reply_email]
        out = [self.name, self.slug, self.legal_name, *hosts, self.sender.from_name, self.sender.town,
               self.sender.demo_number, Path(self.paths.census).name]
        return sorted({x.lower() for x in out if x})


def ventures_dir():
    return Path(os.environ.get("VENTURES_DIR") or TOOLS / "ventures")


def default_name():
    f = ventures_dir() / "DEFAULT"
    try:
        return f.read_text().strip()
    except OSError:
        raise VentureError(f"VENTURE is not set and {f} doesn't exist; set VENTURE or write the name in that file")


def _check(data, path):
    flat = {}

    def walk(d, prefix=""):
        for k, v in d.items():
            key = prefix + k
            if isinstance(v, dict):
                walk(v, key + ".")
            else:
                flat[key] = v
    walk(data)
    missing = [k for k in FIELDS if k not in flat]
    if missing:
        raise VentureError(f"{path} is missing {', '.join(missing)}")
    extra = [k for k in flat if k not in FIELDS]
    if extra:
        raise VentureError(f"{path} has field(s) lib/venture.py doesn't know: {', '.join(extra)}")
    for k, t in FIELDS.items():
        v = flat[k]
        if t == "list[str]":
            ok = isinstance(v, list) and all(isinstance(x, str) for x in v)
        elif t == "list[float]":
            ok = isinstance(v, list) and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)
        else:
            ok = isinstance(v, t)
        if not ok:
            raise VentureError(f"{path}: {k} should be {t if isinstance(t, str) else t.__name__}, "
                               f"not {type(v).__name__}")


_cache = {}


def load(path, name=None):
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text())
    except OSError as e:
        raise VentureError(f"can't read {path}: {e.strerror or e}")
    except tomllib.TOMLDecodeError as e:
        raise VentureError(f"{path} isn't valid TOML: {e}")
    _check(data, path)
    return Venture(name or path.parent.name, path, data)


def venture(name=None):
    """The venture named, else VENTURE in env, else ventures/DEFAULT. Read once per name per process."""
    name = (name or os.environ.get("VENTURE") or "").strip() or default_name()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name):
        raise VentureError(f"{name!r} isn't a venture name (lower case letters, digits, - and _)")
    path = ventures_dir() / name / "venture.toml"
    key = str(path)
    if key not in _cache:
        if not path.exists():
            raise VentureError(f"no venture named {name!r}: {path} doesn't exist")
        _cache[key] = load(path, name)
    return _cache[key]


def from_argv(argv=None):
    """Take `--venture NAME` / `--venture=NAME` out of argv (sys.argv by default) and put NAME in VENTURE,
    so the tool's own parser never sees it and anything it runs inherits it. Returns the venture."""
    argv = sys.argv if argv is None else argv
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--venture":
            if i + 1 >= len(argv):
                raise VentureError("--venture needs a name")
            os.environ["VENTURE"] = argv[i + 1]
            del argv[i:i + 2]
            continue
        if a.startswith("--venture="):
            os.environ["VENTURE"] = a.split("=", 1)[1]
            del argv[i]
            continue
        if a == "--":
            break
        i += 1
    return venture()
