"""doc — reading the files people send (PDF, CSV, TXT, xlsx/xls, docx) and
writing one back (ROADMAP B35, sms-relay plan 17).

    python3 -m unittest tests.test_doc -q   (from claude-tools/)

The fixtures under tests/fixtures/doc/ are the ones Flint sends live too:
stock-list.xlsx (Inventory, Prices, Suppliers; a formula's cached value and a
date in Inventory), menu.pdf, notes.docx, items.csv. Every Excel/Word case
runs twice: through LibreOffice when it's installed, and with
DOC_NO_LIBREOFFICE=1 through the stdlib readers — the two must agree.
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402  first, before any tool loads: the suite stays off production (tests/_offline.py)

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "bin" / "doc"
FX = ROOT / "tests" / "fixtures" / "doc"
HAVE_LO = bool(shutil.which("libreoffice") or shutil.which("soffice"))
HAVE_PDFTOTEXT = bool(shutil.which("pdftotext"))


def run(*args, stdin=None, fallback=False, cwd=None):
    env = dict(os.environ)
    env.pop("DOC_NO_LIBREOFFICE", None)
    if fallback:
        env["DOC_NO_LIBREOFFICE"] = "1"
    return subprocess.run([sys.executable, str(DOC), *map(str, args)], input=stdin, capture_output=True,
                          text=True, env=env, cwd=cwd, timeout=180)


INVENTORY_ROW = "Chicken thighs (lb),Protein,18,40,22,2026-09-26"   # E2 is =MAX(0,D2-C2), F2 a date


class DocTextTest(unittest.TestCase):
    def check_xlsx(self, fallback):
        r = run("text", FX / "stock-list.xlsx", fallback=fallback)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        for sheet in ("## Inventory", "## Prices", "## Suppliers"):
            self.assertIn(sheet, out)
        self.assertLess(out.index("## Inventory"), out.index("## Prices"))
        self.assertLess(out.index("## Prices"), out.index("## Suppliers"))
        self.assertIn(INVENTORY_ROW, out, "the formula's cached value and the date")
        self.assertIn("Burrito bowl,12.75,\"rice, beans, choice of meat\"", out)
        self.assertIn('Wasatch Meats,Dana Ortiz,801-555-0142,"Tue, Fri"', out)
        return out

    def test_xlsx_every_sheet_fallback(self):
        self.check_xlsx(fallback=True)

    @unittest.skipUnless(HAVE_LO, "libreoffice not installed")
    def test_xlsx_every_sheet_libreoffice_and_fallback_agree(self):
        self.assertEqual(self.check_xlsx(fallback=False), self.check_xlsx(fallback=True))

    def test_one_sheet(self):
        for fb in (True, False) if HAVE_LO else (True,):
            r = run("text", FX / "stock-list.xlsx", "--sheet", "prices", fallback=fb)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.startswith("## Prices\n"))
            self.assertNotIn("Inventory", r.stdout)
        r = run("text", FX / "stock-list.xlsx", "--sheet", "Nope", fallback=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("Inventory, Prices, Suppliers", r.stderr)

    def test_cap(self):
        r = run("text", FX / "stock-list.xlsx", "--max-rows", "5", fallback=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len([ln for ln in lines if ln and not ln.startswith(("## ", "… "))]), 5)
        self.assertIn("… 6 more rows (--max-rows to see more)", lines)
        self.assertIn("… 11 more rows (--max-rows to see more)", lines, "Prices is named, its rows cut")
        self.assertIn("## Suppliers", lines)
        r = run("text", FX / "items.csv", "--max-rows", "3")
        self.assertEqual(r.stdout.splitlines()[-1], "… 6 more rows (--max-rows to see more)")
        self.assertEqual(len(r.stdout.splitlines()), 4)

    def test_default_cap_is_2000(self):
        with tempfile.TemporaryDirectory() as tmp:
            big = Path(tmp) / "big.csv"
            big.write_text("n\n" + "".join(f"{i}\n" for i in range(2500)))
            out = run("text", big).stdout.splitlines()
            self.assertEqual(len(out), 2001)
            self.assertEqual(out[-1], "… 501 more rows (--max-rows to see more)")

    @unittest.skipUnless(HAVE_PDFTOTEXT, "pdftotext not installed")
    def test_pdf(self):
        r = run("text", FX / "menu.pdf")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Casa Wasatch Taqueria", r.stdout)
        self.assertRegex(r.stdout, r"Burrito bowl \.+ \$12\.75")
        self.assertNotIn("\n\n\n", r.stdout, "runs of blank lines are one")

    @unittest.skipUnless(HAVE_PDFTOTEXT, "pdftotext not installed")
    def test_pdf_without_text_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            blank = Path(tmp) / "scan.pdf"
            blank.write_bytes(blank_pdf())
            r = run("text", blank)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(len(r.stderr.strip().splitlines()), 1)
            self.assertIn("no text layer", r.stderr)

    def test_docx(self):
        for fb in (True, False) if HAVE_LO else (True,):
            r = run("text", FX / "notes.docx", fallback=fb)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(r.stdout.startswith("Website changes for October"), r.stdout[:80])
            self.assertIn("Take the tamales off the menu page", r.stdout)
            self.assertIn("Thanks, Rosa", r.stdout)
        self.assertIn("- Raise the burrito bowl", run("text", FX / "notes.docx", fallback=True).stdout)

    def test_csv_and_txt_pass_through(self):
        r = run("text", FX / "items.csv")
        self.assertEqual(r.stdout, (FX / "items.csv").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "list.txt"
            old.write_bytes("Jalape\xf1o poppers, 6.00\r\n".encode("cp1252"))
            self.assertEqual(run("text", old).stdout, "Jalapeño poppers, 6.00\n")
            bom = Path(tmp) / "bom.csv"
            bom.write_bytes("﻿a,b\n1,2\n".encode("utf-8"))
            self.assertEqual(run("text", bom).stdout, "a,b\n1,2\n")

    def test_refuses_other_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "deck.pages"
            f.write_text("x")
            r = run("text", f)
            self.assertEqual(r.returncode, 2)
            self.assertEqual(len(r.stderr.strip().splitlines()), 1)
            self.assertIn("PDF, CSV, TXT, Excel (.xlsx, .xls) and Word (.docx)", r.stderr)
            r = run("text", Path(tmp) / "missing.pdf")
            self.assertEqual(r.returncode, 1)

    def test_sniffs_a_file_without_its_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "attachment.bin"
            shutil.copyfile(FX / "stock-list.xlsx", f)
            r = run("text", f, fallback=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("## Suppliers", r.stdout)

    @unittest.skipUnless(HAVE_LO, "libreoffice not installed")
    def test_xls_through_libreoffice(self):
        with tempfile.TemporaryDirectory() as tmp:
            prof = Path(tmp) / "prof"
            subprocess.run([shutil.which("libreoffice") or shutil.which("soffice"),
                            f"-env:UserInstallation={prof.as_uri()}", "--headless", "--convert-to", "xls",
                            "--outdir", tmp, str(FX / "stock-list.xlsx")], capture_output=True, timeout=120)
            xls = Path(tmp) / "stock-list.xls"
            self.assertTrue(xls.is_file())
            r = run("text", xls)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("## Suppliers", r.stdout)
            self.assertIn(INVENTORY_ROW, r.stdout)
            r = run("text", xls, fallback=True)
            self.assertEqual(r.returncode, 1)
            self.assertIn("needs LibreOffice", r.stderr)

    @unittest.skipUnless(HAVE_LO, "libreoffice not installed")
    def test_concurrent_runs_do_not_fight(self):
        results = []

        def one():
            results.append(run("text", FX / "stock-list.xlsx"))
        threads = [threading.Thread(target=one) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for r in results:
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn(INVENTORY_ROW, r.stdout)
            self.assertNotIn("fallback", r.stderr)


class DocSheetsTest(unittest.TestCase):
    def test_sheets(self):
        for fb in (True, False) if HAVE_LO else (True,):
            r = run("sheets", FX / "stock-list.xlsx", fallback=fb)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual([ln.split() for ln in r.stdout.splitlines()],
                             [["Inventory", "11", "rows"], ["Prices", "11", "rows"], ["Suppliers", "6", "rows"]])

    def test_not_a_spreadsheet(self):
        r = run("sheets", FX / "items.csv")
        self.assertEqual(r.returncode, 0)
        self.assertIn("not a spreadsheet", r.stdout)


class DocWriteTest(unittest.TestCase):
    ROWS = "Item,Price,ZIP,Note\nChips & salsa,4.50,08401,\"mild, <house>\"\nHorchata,3.75,84003,\n"

    def test_write_xlsx_and_read_it_back(self):
        for fb in (True, False) if HAVE_LO else (True,):
            with tempfile.TemporaryDirectory() as tmp:
                r = run("write", "exports/audit.xlsx", "--sheet", "Audit", stdin=self.ROWS, fallback=fb, cwd=tmp)
                self.assertEqual(r.returncode, 0, r.stderr)
                out = Path(tmp) / "exports" / "audit.xlsx"
                self.assertEqual(r.stdout.splitlines()[-1], str(out.resolve()), "the path is last, for SEND-FILE")
                self.assertIn("3 rows, 4 columns", r.stdout)
                with zipfile.ZipFile(out) as z:
                    self.assertIn("xl/worksheets/sheet1.xml", z.namelist())
                for readfb in (True, False) if HAVE_LO else (True,):
                    back = run("text", out, fallback=readfb)
                    self.assertEqual(back.returncode, 0, back.stderr)
                    self.assertEqual(back.stdout,
                                     "## Audit\nItem,Price,ZIP,Note\nChips & salsa,4.5,08401,\"mild, <house>\"\n"
                                     "Horchata,3.75,84003\n", f"read back with fallback={readfb}")

    def test_write_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run("write", "out.csv", stdin=self.ROWS, cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(run("text", Path(tmp) / "out.csv").stdout,
                             "Item,Price,ZIP,Note\nChips & salsa,4.50,08401,\"mild, <house>\"\nHorchata,3.75,84003\n")

    def test_write_from_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "rows.csv").write_text(self.ROWS)
            r = run("write", "exports/audit.xlsx", "--from", "rows.csv", cwd=tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("Horchata,3.75,84003", run("text", Path(tmp) / "exports" / "audit.xlsx", fallback=True).stdout)
            self.assertEqual(run("write", "x.csv", "--from", "nope.csv", cwd=tmp).returncode, 1)

    def test_write_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run("write", "a.csv", stdin=self.ROWS, cwd=tmp).returncode, 0)
            r = run("write", "a.csv", stdin=self.ROWS, cwd=tmp)
            self.assertEqual(r.returncode, 1)
            self.assertIn("--force", r.stderr)
            self.assertEqual(run("write", "a.csv", "--force", stdin=self.ROWS, cwd=tmp).returncode, 0)
            self.assertEqual(run("write", "a.pdf", stdin=self.ROWS, cwd=tmp).returncode, 2)
            self.assertEqual(run("write", "b.csv", stdin="", cwd=tmp).returncode, 1)


class DocDoctorTest(unittest.TestCase):
    def test_doctor(self):
        for fb in (False, True):
            r = run("doctor", fallback=fb)
            self.assertIn("round trip", r.stdout)
            self.assertNotIn("FAIL round trip", r.stdout)
            if HAVE_PDFTOTEXT and shutil.which("doc") and Path(shutil.which("doc")).resolve() == DOC:
                self.assertEqual(r.returncode, 0, r.stdout)


def blank_pdf():
    """A one-page PDF with nothing on it: what a scan looks like to pdftotext."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


if __name__ == "__main__":
    unittest.main()
