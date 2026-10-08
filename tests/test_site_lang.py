"""B126: a site's built-in lines in Spanish (`site new --lang es`, `site lang`, `site render`) — no network.

    python3 -m unittest discover -s tests -q   (from claude-tools/)

What's pinned: every pair in templates/sites/_lang/es.json still finds its English in a template
(a stale pair would quietly do nothing); the pass is idempotent and goes back to English exactly;
each template rendered with --lang es has no built-in English line left and says lang="es"; the
Functions still parse once translated (node --check); and a Spanish site's /admin shell is never
"behind" the toolbelt just for being Spanish.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import argparse
import contextlib
import importlib.machinery
import importlib.util
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys_path = str(ROOT / "lib")
if sys_path not in _sys.path:
    _sys.path.insert(0, sys_path)
import site_lang  # noqa: E402

SITES = ROOT / "templates" / "sites"
COLLECTIONS = ROOT / "templates" / "collections"
TYPES = sorted(d.name for d in SITES.iterdir() if d.is_dir() and not d.name.startswith("_"))


def load_site():
    loader = importlib.machinery.SourceFileLoader("site_tool_lang", str(ROOT / "bin" / "site"))
    spec = importlib.util.spec_from_loader("site_tool_lang", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class TheSet(unittest.TestCase):
    def test_no_pair_is_stale(self):
        self.assertEqual(site_lang.stale("es", [SITES, COLLECTIONS]), [])

    def test_every_template_is_covered(self):
        self.assertEqual(sorted(site_lang.load("es")["complete"]), TYPES)

    def test_pairs_are_one_to_one_and_never_feed_each_other(self):
        pairs = site_lang.load("es")["pairs"]
        spanish = [es for _, es in pairs]
        self.assertEqual(len(spanish), len(set(spanish)), "two English pieces share a Spanish one: going back is ambiguous")
        for a in spanish:                               # going back, a longer Spanish piece wins over a short one
            for b in spanish:
                if a != b and a in b:
                    en_a = next(en for en, es in pairs if es == a)
                    en_b = next(en for en, es in pairs if es == b)
                    self.assertIn(en_a, en_b, f"{b[:50]!r} holds {a[:50]!r} but its English doesn't hold {en_a[:50]!r}")
        keys = [en for en, _ in pairs]
        for es in spanish:
            for en in keys:
                self.assertNotIn(en, es, f"the Spanish {es[:40]!r} holds the English {en[:40]!r}: a second pass would change it")

    def test_review_round_wording(self):
        text = " ".join(es for _, es in site_lang.load("es")["pairs"])
        for bad in ('"el negocio")', "reclama", "antes de ${TOKEN_MINUTES}", "marcados ${", " lugares)"):
            self.assertNotIn(bad, text)

    def test_usted_on_the_customer_side(self):
        text = " ".join(es for _, es in site_lang.load("es")["pairs"])
        for tu in ("Elige ", "Escribe ", "Responde ", " tu reserva", "Pide "):
            self.assertNotIn(tu, text)


class ThePass(unittest.TestCase):
    def files(self):
        for root in (SITES, COLLECTIONS):
            for p in site_lang._files(root):
                if site_lang.LANG_DIR not in p.parents:
                    yield p

    def test_twice_is_once_and_back_is_exact(self):
        for p in self.files():
            text = p.read_text(encoding="utf-8")
            once, _ = site_lang.translate(text, "es")
            twice, n = site_lang.translate(once, "es")
            self.assertEqual((twice, n), (once, 0), p)
            back, _ = site_lang.translate(once, "es", reverse=True)
            self.assertEqual(back, text, p)

    def test_english_is_no_change(self):
        self.assertEqual(site_lang.translate("Book it", "en"), ("Book it", 0))
        self.assertEqual(site_lang.norm("es-MX"), "es")
        self.assertEqual(site_lang.norm("Spanish"), "es")
        with self.assertRaises(ValueError):
            site_lang.load("fr")

    @unittest.skipUnless(shutil.which("node"), "node isn't installed")
    def test_the_functions_still_parse_in_spanish(self):
        with tempfile.TemporaryDirectory() as td:
            for p in self.files():
                if p.suffix != ".js" or "functions" not in p.parts:
                    continue
                out = Path(td) / p.relative_to(ROOT).with_suffix(".mjs")
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(site_lang.translate(p.read_text(encoding="utf-8"), "es")[0], encoding="utf-8")
                r = subprocess.run(["node", "--check", str(out)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{p.relative_to(ROOT)}: {r.stderr[:300]}")


class Render(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = load_site()

    def render(self, kind, dest, lang="es"):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.site.cmd_render(argparse.Namespace(template=kind, dir=str(dest), lang=lang, name="Limpieza Ana",
                                                    tagline=None, no_db=False))
        return out.getvalue()

    def test_each_template_in_spanish(self):
        for kind in TYPES:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as td:
                dest = Path(td) / "s"
                self.render(kind, dest)
                self.assertEqual(site_lang.left(dest, "es"), [])
                self.assertEqual(site_lang.detect(dest), "es")
                index = (dest / "index.html").read_text()
                self.assertNotIn("{{", index)
                self.assertNotIn("site-chat.js", index)           # a folder has no project behind the bubble
                self.assertIn("Una línea corta sobre lo que hace Limpieza Ana.", index)

    def test_the_service_forms_and_thanks_lines(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "s"
            self.render("service", dest)
            index = (dest / "index.html").read_text()
            for es in ("¿Qué necesita?", "Reservar</button>", "Gracias, lo recibimos y nos pondremos en contacto con usted.",
                       "Listo, recibimos su solicitud.", "Elija un horario"):
                self.assertIn(es, index)
            manage = (dest / "functions" / "book" / "manage.js").read_text()
            self.assertIn("<h2>Cancelarla</h2>", manage)
            admin = (dest / "functions" / "admin" / "index.js").read_text()
            self.assertIn("Enviarme un enlace", admin)

    def test_english_is_the_template_as_it_is(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "s"
            self.render("service", dest, lang=None)
            self.assertEqual(site_lang.detect(dest), "en")
            self.assertIn("What do you need?", (dest / "index.html").read_text())

    def test_a_spanish_site_is_not_behind_on_the_shell(self):
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "s"
            self.render("service", dest)
            self.assertEqual(self.site.shell_drift(dest, "es"), [])
            self.assertTrue(self.site.shell_drift(dest, "en"), "compared as English, the Spanish files differ")

    def test_an_unknown_language_is_refused(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()), \
                contextlib.redirect_stdout(io.StringIO()):
            self.site.lang_arg("fr")


if __name__ == "__main__":
    unittest.main()


class SiteLangCommand(unittest.TestCase):
    """`site lang NAME es|en` on a real local repo with a bare upstream; publish is stubbed.
    The registry's `lang` is written only once the push and the publish went through, and going
    back to English removes the key instead of leaving a null."""

    def setUp(self):
        from unittest import mock
        self.site = load_site()
        self.td = tempfile.TemporaryDirectory()
        self.addCleanup(self.td.cleanup)
        root = Path(self.td.name)
        self.ws = root / "ws"
        self.repo = self.ws / "repos" / "ana-site"
        bare = root / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.site.cmd_render(argparse.Namespace(template="service", dir=str(self.repo), lang=None, name="Ana",
                                                    tagline=None, no_db=False))
        g = ["git", "-C", str(self.repo)]
        subprocess.run(g + ["init", "-q", "-b", "main"], check=True)
        subprocess.run(g + ["add", "-A"], check=True)
        subprocess.run(g + ["-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "x"], check=True)
        subprocess.run(g + ["remote", "add", "origin", str(bare)], check=True)
        subprocess.run(g + ["push", "-q", "-u", "origin", "main"], check=True, capture_output=True)
        self.reg = root / "sites.json"
        self.reg.write_text('{"ana": {"ana-site": {"host": "cloudflare", "project": "ana-site"}}}')
        self.meta = {"slug": "ana", "name": "Ana"}
        self.published = []
        for p in (mock.patch.object(self.site, "REGISTRY", self.reg),
                  mock.patch.object(self.site, "workspace", lambda: (self.ws, self.meta)),
                  mock.patch.object(self.site, "cmd_publish", lambda a: self.published.append(a.name))):
            p.start()
            self.addCleanup(p.stop)

    def run_lang(self, code, **kw):
        args = dict(name="ana-site", code=code, check=False, no_publish=False, message=None, dry_run=False)
        args.update(kw)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.site.cmd_lang(argparse.Namespace(**args))
        return out.getvalue()

    def row(self):
        import json
        return json.loads(self.reg.read_text())["ana"]["ana-site"]

    def test_es_then_back_to_en(self):
        self.run_lang("es")
        self.assertEqual(self.published, ["ana-site"])
        self.assertEqual(self.row().get("lang"), "es")
        self.assertIn("¿Qué necesita?", (self.repo / "index.html").read_text())
        self.run_lang("en")
        self.assertNotIn("lang", self.row())
        self.assertIn("What do you need?", (self.repo / "index.html").read_text())

    def test_a_failed_publish_leaves_the_registry_alone_and_the_next_run_finishes_it(self):
        def boom(a):
            raise SystemExit("publish failed")
        from unittest import mock
        with mock.patch.object(self.site, "cmd_publish", boom), self.assertRaises(SystemExit):
            self.run_lang("es")
        self.assertNotIn("lang", self.row())
        self.run_lang("es")                                   # nothing left to translate; still records once out
        self.assertEqual(self.published, ["ana-site"])
        self.assertEqual(self.row().get("lang"), "es")

    def test_no_publish_doesnt_record(self):
        out = self.run_lang("es", no_publish=True)
        self.assertIn("not pushed or published", out)
        self.assertNotIn("lang", self.row())
