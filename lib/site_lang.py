"""
lib/site_lang.py — a site's built-in strings in another language (ROADMAP B126,
~/projects/plans/49-the-customer-side.md § Changes 9).

The English template files under templates/sites/ and templates/collections/ stay the only
source. templates/sites/_lang/<code>.json holds pairs: an exact piece of an English file (with
enough markup around it that a short word never lands inside code) and what replaces it. A site
made with `site new --lang es`, or switched with `site lang NAME es`, has every pair applied to
its .html and .js files; the /admin shell and the collections' Functions get the same pass when
they are copied in (`site data`, `site shell`, and `site lang` again after a `db add`).

Why pairs and not a second copy of each template: a fix to an English file reaches the Spanish
sites the next time the pass runs, and a pair whose English is gone is visible (stale()) instead
of a Spanish file quietly drifting from its English one.

    codes()                       languages there is a set for, besides English
    load(code)                    the set: {"lang", "complete": [template, ...], "pairs": [[en, other], ...]}
    translate(text, code, reverse=False) -> (text, n)
                                  every pair applied, longest English first (so a long sentence wins
                                  over a short piece of it); reverse=True goes back to English
    apply(root, code, files=None, reverse=False, dry=False) -> {relpath: n}
                                  the pass over a folder (or only `files`, paths relative to root)
    stale(code, roots)            pairs whose English is in none of the template files
    left(root, code)              pairs whose English is still in a site that should be in `code`
    detect(root)                  the language its index.html says (<html lang="es">), else "en"

No network, no keys. Imported by bin/site; `leads preview` can use the same files.
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
LANG_DIR = HERE / "templates" / "sites" / "_lang"
EXTS = (".html", ".js")
SKIP = {".git", "node_modules", ".wrangler", "shots"}
NAMES = {"en": "English", "es": "Spanish"}


def codes():
    return sorted(p.stem for p in LANG_DIR.glob("*.json")) if LANG_DIR.is_dir() else []


def norm(code):
    c = str(code or "").strip().lower().replace("_", "-").split("-")[0]
    return {"spanish": "es", "espanol": "es", "español": "es", "english": "en"}.get(c, c)


def load(code):
    code = norm(code)
    path = LANG_DIR / f"{code}.json"
    if not path.exists():
        raise ValueError(f"no {code!r} set (have: {', '.join(['en'] + codes())})")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["pairs"] = [list(p) for p in data.get("pairs") or [] if len(p) == 2 and p[0] and p[0] != p[1]]
    return data


def _ordered(pairs, reverse):
    side = 1 if reverse else 0
    return sorted(((p[side], p[1 - side]) for p in pairs), key=lambda kv: -len(kv[0]))


def translate(text, code, reverse=False, _pairs=None):
    if norm(code) == "en":
        return text, 0
    n = 0
    for a, b in _pairs if _pairs is not None else _ordered(load(code)["pairs"], reverse):
        if a in text:
            n += text.count(a)
            text = text.replace(a, b)
    return text, n


def _files(root, files=None):
    root = Path(root)
    if files is not None:
        return [root / f for f in files if Path(f).suffix in EXTS and (root / f).is_file()]
    return [p for p in sorted(root.rglob("*")) if p.is_file() and p.suffix in EXTS
            and not (SKIP & set(p.relative_to(root).parts))]


def apply(root, code, files=None, reverse=False, dry=False):
    """Apply the set to root's .html and .js files; {relative path: replacements} for those changed."""
    if norm(code) == "en":
        return {}
    pairs = _ordered(load(code)["pairs"], reverse)
    out = {}
    for p in _files(root, files):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new, n = translate(text, code, reverse, _pairs=pairs)
        if n:
            out[str(p.relative_to(root))] = n
            if not dry:
                p.write_text(new, encoding="utf-8")
    return out


def stale(code, roots):
    """The pairs whose English no template file holds any more (the template changed under them)."""
    texts = []
    for r in roots:
        for p in _files(r):
            if LANG_DIR in p.parents:
                continue
            try:
                texts.append(p.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, OSError):
                pass
    return [en for en, _ in load(code)["pairs"] if not any(en in t for t in texts)]


def left(root, code):
    """[(relpath, english)] still in a site that should be all `code`: what a pass would still change."""
    out = []
    pairs = load(code)["pairs"]
    for p in _files(root):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        out += [(str(p.relative_to(root)), en) for en, _ in pairs if en in text]
    return out


HTML_LANG = re.compile(r"<html[^>]*\blang=\"([A-Za-z-]+)\"", re.IGNORECASE)


def detect(root):
    p = Path(root) / "index.html"
    try:
        m = HTML_LANG.search(p.read_text(encoding="utf-8", errors="replace")[:2000])
    except OSError:
        return "en"
    return norm(m.group(1)) if m else "en"
