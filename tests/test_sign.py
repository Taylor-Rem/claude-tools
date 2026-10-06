"""sign (ROADMAP B128): a document signed by link. The CLI on the fake wrangler
(db's real code, a SQLite file per database), the signing page's Function
under node with node:sqlite opening that same file as D1, and the signed PDF
through print's renderer when the browser is here. No network.

    python3 -m unittest tests.test_sign -q   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402

import importlib.machinery
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

import test_db  # noqa: E402  (its setUp makes a workspace with a site and a database)

ROOT = test_db.ROOT
SIGN = ROOT / "bin" / "sign"
COLL = ROOT / "templates" / "collections" / "signatures"

WAIVER = """# Pool Service Waiver

Juniper Flats Pool & Spa services your pool.

## What you agree to

- Keep pets inside while we work.
- Tell us about *any* damage you already know of.

By signing you agree to the **above**. <script>alert(1)</script>
"""


def load_sign():
    loader = importlib.machinery.SourceFileLoader("sign_tool", str(SIGN))
    spec = importlib.util.spec_from_loader("sign_tool", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


S = load_sign()
NODE = shutil.which("node")


def node_sqlite():
    if not NODE:
        return False
    return subprocess.run([NODE, "-e", "require('node:sqlite')"], capture_output=True).returncode == 0


def have_browser():
    if not (NODE and shutil.which("pdfinfo") and shutil.which("pdftotext")):
        return False
    r = subprocess.run([NODE, str(ROOT / "lib" / "print.mjs"), "doctor"], capture_output=True, text=True, timeout=120)
    try:
        return bool(json.loads(r.stdout.strip().splitlines()[-1]).get("browser"))
    except (ValueError, IndexError):
        return False


class DocumentTest(unittest.TestCase):
    def test_the_text_is_kept_and_hashed_the_same_way_each_time(self):
        a = S.normalise("# T\r\nline  \r\n\r\n\r\n")
        self.assertEqual(a, "# T\nline\n")
        self.assertEqual(S.digest(a), S.digest(S.normalise("# T\nline")))
        self.assertEqual(len(S.digest(a)), 64)

    def test_markdown_is_escaped_before_it_is_shown(self):
        h = S.to_html(S.normalise(WAIVER))
        self.assertIn("<h1>Pool Service Waiver</h1>", h)
        self.assertIn("<h2>What you agree to</h2>", h)
        self.assertIn("<ul><li>Keep pets inside while we work.</li>", h)
        self.assertIn("<em>any</em>", h)
        self.assertIn("<strong>above</strong>", h)
        self.assertNotIn("<script>", h)
        self.assertIn("&lt;script&gt;", h)
        self.assertEqual(S.title_of(WAIVER, Path("pool-waiver.md")), "Pool Service Waiver")
        self.assertEqual(S.title_of("no heading here", Path("pool-waiver.md")), "Pool waiver")


class SignTest(unittest.TestCase):
    setUp_db = test_db.DbTest.setUp
    tearDown = test_db.DbTest.tearDown
    row = test_db.DbTest.row
    register = test_db.DbTest.register
    make_repo = test_db.DbTest.make_repo
    db = test_db.DbTest.db
    calls = test_db.DbTest.calls

    def setUp(self):
        self.setUp_db()
        (self.repo / "wrangler.toml").write_text((self.repo / "wrangler.toml").read_text().replace(
            "[vars]\n", '[vars]\nTIMEZONE = "America/Denver"\nSITE_NAME = "Acme Pools"\n'))
        (self.ws / "waivers").mkdir()
        (self.ws / "waivers" / "pool.md").write_text(WAIVER)

    def sign(self, *args):
        return subprocess.run([sys.executable, str(SIGN), *args], env=self.env, cwd=self.ws, capture_output=True, text=True)

    def add(self, *colls):
        for c in colls:
            r = self.db("add", c)
            self.assertEqual(r.returncode, 0, r.stderr)

    def sqlite(self):
        return Path(self.env["FAKE_D1_DIR"]) / "acme-site.remote.sqlite"

    def q(self, sql):
        return json.loads(self.db("query", sql, "--json").stdout)

    def test_a_site_without_the_collection_is_told_what_to_do(self):
        r = self.sign("new", "waivers/pool.md", "--for", "Smith")
        self.assertEqual(r.returncode, 1)
        self.assertIn("db add signatures", r.stderr)

    def test_db_add_signatures_wires_the_page_and_the_admin_list(self):
        self.add("signatures")
        self.assertTrue((self.repo / "functions" / "sign" / "[token].js").exists())
        self.assertIn('import signatures from "./signatures.js";', (self.repo / "functions" / "_admin" / "collections.js").read_text())
        self.assertTrue(any(p.name.endswith("_signatures.sql") for p in (self.repo / "migrations").iterdir()))

    def test_new_puts_the_text_on_the_site_with_an_unguessable_link(self):
        self.add("signatures")
        r = self.sign("new", "waivers/pool.md", "--for", "Dana Ruiz", "--email", "dana@example.com")
        self.assertEqual(r.returncode, 0, r.stderr)
        link = r.stdout.strip().splitlines()[-1]
        self.assertRegex(link, r"^https://acme-site\.pages\.dev/sign/[A-Za-z0-9_-]{40,}$")
        self.assertIn("Send this to Dana Ruiz (dana@example.com)", r.stdout)
        row = self.q("SELECT * FROM signatures")[0]
        self.assertEqual((row["title"], row["for_name"], row["status"], row["doc_file"]),
                         ("Pool Service Waiver", "Dana Ruiz", "sent", "waivers/pool.md"))
        self.assertEqual(row["doc_sha256"], S.digest(S.normalise(WAIVER)))
        self.assertEqual(link.rsplit("/", 1)[1], row["token"])
        self.assertNotIn("<script>", row["body_html"])
        self.assertNotIn("<h1>", row["body_html"], "the title isn't shown twice")
        # two sends are two links
        self.sign("new", "waivers/pool.md", "--for", "Sam Smith")
        toks = [x["token"] for x in self.q("SELECT token FROM signatures")]
        self.assertEqual(len(set(toks)), 2)

    def test_dry_run_writes_nothing_and_outside_files_are_refused(self):
        self.add("signatures")
        r = self.sign("new", "waivers/pool.md", "--for", "Dana", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run: nothing written", r.stdout)
        self.assertEqual(self.q("SELECT COUNT(*) AS n FROM signatures")[0]["n"], 0)
        r = self.sign("new", "/etc/hostname", "--for", "Dana")
        self.assertEqual(r.returncode, 1)
        self.assertIn("outside this workspace", r.stderr)

    def test_the_book_names_the_customer_and_several_matches_are_asked_about(self):
        self.add("signatures", "customers")
        self.db("customers", "add", "Dana Ruiz", "--phone", "801-555-0134", "--email", "dana@example.com")
        self.db("customers", "add", "Sam Smith", "--phone", "801-555-0101")
        self.db("customers", "add", "Jo Smith", "--phone", "801-555-0102")
        r = self.sign("new", "waivers/pool.md", "--for", "Dana")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("in the book as #1 Dana Ruiz", r.stdout)
        row = self.q("SELECT customer_id, email, phone FROM signatures")[0]
        self.assertEqual((row["customer_id"], row["email"]), (1, "dana@example.com"))
        r = self.sign("new", "waivers/pool.md", "--for", "Smith")
        self.assertEqual(r.returncode, 3)
        self.assertIn("say which with --customer ID", r.stderr)
        r = self.sign("new", "waivers/pool.md", "--for", "Smith", "--customer", "3")
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_void_withdraws_and_a_signed_one_needs_its_word(self):
        self.add("signatures")
        self.sign("new", "waivers/pool.md", "--for", "Dana")
        r = self.sign("void", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.q("SELECT status FROM signatures")[0]["status"], "void")
        self.assertNotIn("#1", self.sign("ls").stdout)
        self.assertIn("#1 void", self.sign("ls", "--all").stdout)
        self.sign("new", "waivers/pool.md", "--for", "Sam")
        self.db("exec", "UPDATE signatures SET status = 'signed', signed_name = 'Sam Hill', signed_at = '2026-10-05T22:31:07Z' WHERE id = 2")
        r = self.sign("void", "2")
        self.assertEqual(r.returncode, 1)
        self.assertIn("--signed", r.stderr)

    # -- the page, and the whole way round -------------------------------------------

    def run_page(self, token, script_body):
        """The signing Function under node, D1 = the fake wrangler's SQLite file."""
        work = Path(self.tmp.name) / "fn"
        if not work.exists():
            shutil.copytree(self.repo / "functions", work / "functions")
        script = work / "run.mjs"
        script.write_text(r"""
import { DatabaseSync } from "node:sqlite";
import { onRequestGet, onRequestPost } from "./functions/sign/[token].js";
const sql = new DatabaseSync(process.env.D1_FILE);
const norm = (a) => a.map((x) => (x === undefined ? null : x));
const DB = { prepare(q) { const st = { args: [], bind(...a) { st.args = norm(a); return st; },
  async first() { return sql.prepare(q).get(...st.args) ?? null; },
  async all() { return { results: sql.prepare(q).all(...st.args) }; },
  async run() { const r = sql.prepare(q).run(...st.args); return { meta: { changes: Number(r.changes), last_row_id: Number(r.lastInsertRowid) } }; } }; return st; } };
const sent = [];
globalThis.fetch = async (url, init) => { sent.push({ url, body: String(init.body) }); return new Response("{}", { status: 200 }); };
const env = { DB, SITE_NAME: "Acme Pools", TIMEZONE: "America/Denver", PATCHLAMP_SLUG: "acme" };
const token = process.env.TOKEN;
const params = { token };
const at = `https://acme-site.pages.dev/sign/${token}`;
const post = (fields, headers = {}) => new Request(at, { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded", origin: "https://acme-site.pages.dev", "cf-connecting-ip": "203.0.113.9", "user-agent": "PhoneBrowser/1", ...headers }, body: new URLSearchParams(fields) });
const waits = [];
const ctx = (request) => ({ request, env, params, waitUntil: (p) => waits.push(p) });
const out = {};
""" + script_body + "\nawait Promise.all(waits);\nout.sent = sent;\nconsole.log(JSON.stringify(out));\n")
        r = subprocess.run([NODE, "--no-warnings", str(script)], capture_output=True, text=True, cwd=work,
                           env={"D1_FILE": str(self.sqlite()), "TOKEN": token, "PATH": "/usr/bin:/bin"})
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_the_page_signs_once_and_records_who_when_where_and_what(self):
        if not node_sqlite():
            self.skipTest("no node with node:sqlite")
        self.add("signatures", "customers")
        r = self.sign("new", "waivers/pool.md", "--for", "Dana Ruiz", "--email", "dana@example.com")
        token = r.stdout.strip().splitlines()[-1].rsplit("/", 1)[1]
        out = self.run_page(token, r"""
let r = await onRequestGet(ctx(new Request(at)));
let h = await r.text();
out.policy = r.headers.get("referrer-policy");
out.get = [r.status, h.includes("Pool Service Waiver"), h.includes('name="full_name"'), h.includes('name="agree"'),
  h.includes("not a notarised signature"), h.includes("&lt;script&gt;"), h.includes("<script>alert"), h.includes('name="viewport"')];
r = await onRequestPost(ctx(post({ full_name: "Dana Ruiz" })));
out.noTick = [r.status, (await r.text()).includes("Tick the box")];
r = await onRequestPost(ctx(post({ full_name: " ", agree: "yes" })));
out.noName = (await r.text()).includes("Type your full name");
r = await onRequestPost(ctx(post({ full_name: "Dana Ruiz", agree: "yes" }, { origin: "https://evil.example" })));
out.cross = r.status;
out.stillSent = sql.prepare("SELECT status FROM signatures").get().status;
r = await onRequestPost(ctx(post({ full_name: "  Dana   Ruiz ", agree: "yes" })));
out.signed = [r.status, r.headers.get("location")];
r = await onRequestPost(ctx(post({ full_name: "Someone Else", agree: "yes" })));
out.again = (await r.text()).includes("Signed by Dana Ruiz");
r = await onRequestGet(ctx(new Request(at)));
h = await r.text();
out.after = [h.includes("Signed by Dana Ruiz"), h.includes('name="full_name"')];
out.row = sql.prepare("SELECT status, signed_name, signed_at, signed_ip, signed_agent, signed_sha256, doc_sha256 FROM signatures").get();
r = await onRequestGet({ request: new Request("https://acme-site.pages.dev/sign/nope"), env, params: { token: "nope" } });
out.wrong = r.status;
""")
        self.assertEqual(out["get"], [200, True, True, True, True, True, False, True])
        self.assertEqual(out["policy"], "same-origin", "no-referrer makes the browser post Origin: null")
        self.assertEqual(out["noTick"], [200, True])
        self.assertTrue(out["noName"])
        self.assertEqual(out["cross"], 403)
        self.assertEqual(out["stillSent"], "sent", "a refused post signs nothing")
        self.assertEqual(out["signed"], [303, f"/sign/{token}"])
        self.assertTrue(out["again"], "a second post doesn't sign over the first")
        self.assertEqual(out["after"], [True, False])
        row = out["row"]
        self.assertEqual((row["status"], row["signed_name"], row["signed_ip"], row["signed_agent"]),
                         ("signed", "Dana Ruiz", "203.0.113.9", "PhoneBrowser/1"))
        self.assertRegex(row["signed_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(row["signed_sha256"], row["doc_sha256"], "node's sha256 of the text is python's")
        self.assertEqual(out["wrong"], 404)
        self.assertEqual(len(out["sent"]), 1, "the owner is told once")
        self.assertEqual(out["sent"][0]["url"], "https://patchlamp.com/f/acme/signature")
        self.assertIn("document=Pool+Service+Waiver", out["sent"][0]["body"])

        # sign show: the record as the page has it; then the PDF, filed under the customer
        r = self.sign("show", "1", "--json")
        shown = json.loads(r.stdout)
        self.assertEqual((shown["signed_name"], shown["signed_at"], shown["signed_sha256"]),
                         (row["signed_name"], row["signed_at"], row["signed_sha256"]))
        if not have_browser():
            self.skipTest("no browser/poppler here: the PDF half was not run")
        r = self.sign("show", "Dana")
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        pdf = Path(r.stdout.strip().splitlines()[-1])
        self.assertTrue(pdf.exists() and pdf.parent == self.ws / "signed", pdf)
        self.assertIn("names the signer, the time and the hash", r.stdout)
        self.assertIn("filed under #1 Dana Ruiz", r.stdout)
        self.assertIn("To: owner@acme.test", r.stdout)
        self.assertIn("To: dana@example.com", r.stdout)
        text = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True).stdout
        self.assertIn("Dana Ruiz", text)
        self.assertIn("Keep pets inside", text)
        job = self.q("SELECT what, status, source, ref, notes FROM jobs")[0]
        self.assertEqual((job["what"], job["status"], job["source"], job["ref"]),
                         ("Signed: Pool Service Waiver", "done", "sign", "sig-1"))
        got = self.q("SELECT pdf, filed_at FROM signatures")[0]
        self.assertTrue(got["pdf"].startswith("signed/") and got["filed_at"])
        # shown again: the PDF that is filed, not a second one
        r = self.sign("show", "1")
        self.assertEqual(r.stdout.strip().splitlines()[-1], str(pdf))
        self.assertEqual(len(self.q("SELECT id FROM jobs")), 1)

    def test_a_text_changed_after_sending_is_never_signed(self):
        if not node_sqlite():
            self.skipTest("no node with node:sqlite")
        self.add("signatures")
        r = self.sign("new", "waivers/pool.md", "--for", "Dana")
        token = r.stdout.strip().splitlines()[-1].rsplit("/", 1)[1]
        self.db("exec", "UPDATE signatures SET body = body || 'one more line' WHERE id = 1")
        out = self.run_page(token, r"""
const r = await onRequestPost(ctx(post({ full_name: "Dana Ruiz", agree: "yes" })));
out.r = [r.status, (await r.text()).includes("changed after it was sent")];
out.status = sql.prepare("SELECT status FROM signatures").get().status;
""")
        self.assertEqual(out["r"], [409, True])
        self.assertEqual(out["status"], "sent")
        self.assertEqual(out["sent"], [])

    def test_the_pdf_check_catches_a_missing_name(self):
        if not have_browser():
            self.skipTest("no browser/poppler")
        self.add("signatures")
        self.sign("new", "waivers/pool.md", "--for", "Dana")
        self.db("exec", "UPDATE signatures SET status = 'signed', signed_name = 'Dana Ruiz', signed_at = '2026-10-05T22:31:07Z', "
                        "signed_ip = '203.0.113.9', signed_sha256 = doc_sha256 WHERE id = 1")
        r = self.sign("pdf", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        pdf = Path(r.stdout.strip().splitlines()[-1])
        ok, lines = S.check_pdf(pdf, ["Dana Ruiz", "Mon, Oct 5, 2026, 4:31 PM MDT"])
        self.assertTrue(ok, lines)
        ok, lines = S.check_pdf(pdf, ["Somebody Else"])
        self.assertFalse(ok)

    def test_a_long_document_runs_to_more_pages_and_keeps_all_its_text(self):
        if not have_browser():
            self.skipTest("no browser/poppler")
        self.add("signatures")
        long = "# Long Release\n\n" + "\n\n".join(f"Clause {i}. " + "The customer agrees to this clause. " * 12 for i in range(1, 41))
        (self.ws / "waivers" / "long.md").write_text(long)
        self.sign("new", "waivers/long.md", "--for", "Dana")
        self.db("exec", "UPDATE signatures SET status = 'signed', signed_name = 'Dana Ruiz', signed_at = '2026-10-05T22:31:07Z', "
                        "signed_ip = '203.0.113.9', signed_sha256 = doc_sha256 WHERE id = 1")
        r = self.sign("pdf", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        pages = int(re.search(r"check: (\d+) pages", r.stdout).group(1))
        self.assertGreater(pages, 1)
        text = subprocess.run(["pdftotext", r.stdout.strip().splitlines()[-1], "-"], capture_output=True, text=True).stdout
        self.assertIn("Clause 40.", text, "nothing is cut off after page one")


if __name__ == "__main__":
    unittest.main()
