"""Bookings that finish the job, the site half (ROADMAP B119): the customer's
mails through patchlamp.com (signed), the manage link, the owner's changes on
/admin/bookings, the calendar feed, the customer book — the collection's own
Functions under node, with node:sqlite standing in for D1 and fetch caught.
And `db bookings` (setup, feed, upgrade) on the fake wrangler. No network.

    python3 -m unittest tests.test_bookings_customer -q   (from claude-tools/)
"""

import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent))
import _offline  # noqa: F401,E402

import hashlib
import hmac
import json
import shutil
import subprocess
import unittest
import urllib.parse
from pathlib import Path

import test_db  # noqa: E402

ROOT = test_db.ROOT
COLL = ROOT / "templates" / "collections"
KEY = "k" * 64


def node_ok():
    node = shutil.which("node")
    if not node:
        return None
    probe = subprocess.run([node, "-e", "require('node:sqlite')"], capture_output=True, text=True)
    return node if probe.returncode == 0 else None


SCRIPT = r"""
import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";
import { onRequestPost as book } from "./functions/api/bookings.js";
import { onRequestGet as feed } from "./functions/api/bookings.ics.js";
import { onRequestGet as manageGet, onRequestPost as managePost } from "./functions/book/manage.js";
import { onRequestGet as adminGet, onRequestPost as adminPost } from "./functions/admin/bookings/[id].js";
import { manageToken, readManageToken, utcStamp, manageExpiry } from "./functions/_lib/bookings.js";
import { localNow } from "./functions/_lib/core.js";

const WITH_BOOK = process.argv[2] === "book";
const sql = new DatabaseSync(":memory:");
sql.exec(readFileSync("bookings.sql", "utf8"));
if (WITH_BOOK) sql.exec(readFileSync("customers.sql", "utf8"));
const norm = (a) => a.map((x) => (x === undefined ? null : x));
const DB = { prepare(q) { const st = { args: [], bind(...a) { st.args = norm(a); return st; },
  async first() { return sql.prepare(q).get(...st.args) ?? null; },
  async all() { return { results: sql.prepare(q).all(...st.args) }; },
  async run() { const r = sql.prepare(q).run(...st.args); return { meta: { changes: Number(r.changes), last_row_id: Number(r.lastInsertRowid) } }; } }; return st; } };
const posts = [];
globalThis.fetch = async (url, init) => { posts.push({ url, body: init.body, headers: init.headers }); return new Response("{}", { status: 200 }); };
const KEYED = process.argv[3] !== "nokey";
const env = { DB, TIMEZONE: "America/Denver", PATCHLAMP_SLUG: "demo-service", PATCHLAMP_URL: "https://patchlamp.test",
  SITE_NAME: "Clearwater Pools", SESSION_SECRET: "s", ...(KEYED ? { BOOKING_KEY: process.argv[4], BOOKINGS_FEED_KEY: "feedkey123" } : {}) };
const pending = [];
const waitUntil = (p) => pending.push(p);
const settle = async () => { await Promise.all(pending.splice(0)); };
const ORIGIN = "https://demo-service.pages.dev";
const form = (path, o, extra = {}) => new Request(ORIGIN + path, { method: "POST",
  headers: { "content-type": "application/x-www-form-urlencoded", origin: ORIGIN, accept: "application/json", ...extra }, body: new URLSearchParams(o) });
const day = (n, hm) => localNow(env, n).slice(0, 10) + "T" + hm;
sql.prepare("INSERT INTO booking_slots (starts_at, minutes, capacity, label) VALUES (?, 60, 1, 'Spa check')").run(day(3, "09:00"));  // 1
sql.prepare("INSERT INTO booking_slots (starts_at, minutes, capacity) VALUES (?, 90, 1)").run(day(4, "13:00"));                   // 2
sql.prepare("INSERT INTO booking_slots (starts_at, minutes, capacity) VALUES (?, 60, 1)").run(day(5, "10:00"));                   // 3
const out = {};

// 1. a booking on the site
let r = await book({ request: form("/api/bookings", { slot: "1", name: "Dana Ruiz", email: "Dana@Example.com", phone: "(801) 555-0134", notes: "gate 12" }), env, waitUntil });
await settle();
out.booked = [r.status, await r.json()];
out.posts = posts.slice();
if (WITH_BOOK) out.book1 = [sql.prepare("SELECT name, phone, email, last_seen, source FROM customers").all(), sql.prepare("SELECT what, date, status, source, ref FROM jobs").all()];
// a second booking by the same person (other phone spelling) is the same customer, a second job
r = await book({ request: form("/api/bookings", { slot: "3", name: "Dana", phone: "801.555.0134" }), env, waitUntil });
await settle();
if (WITH_BOOK) out.book2 = [sql.prepare("SELECT COUNT(*) AS n FROM customers").get().n, sql.prepare("SELECT COUNT(*) AS n FROM jobs").get().n];

const t = await manageToken(env, 1, day(3, "09:00"));
out.token = [t, await readManageToken(env, t), await readManageToken(env, t && t.replace(/.$/, (c) => (c === "0" ? "1" : "0"))),
  await readManageToken(env, "1.1000000000.0123456789abcdef0123456789abcdef"), await readManageToken(env, "nonsense")];

// 2. the customer opens the link: the time, the other open times, two buttons; a bad link is a plain page
const getManage = async (tok) => { const res = await manageGet({ request: new Request(`${ORIGIN}/book/manage?t=${tok}`), env }); return [res.status, await res.text()]; };
out.manage = await getManage(t);
out.manageBad = await getManage("1.1790000000.ffffffffffffffffffffffffffffffff");
out.manageNone = await getManage("");

// 3. the owner confirms on /admin/bookings/1
posts.length = 0;
const admin = (o) => ({ request: form("/admin/bookings/1", o), env, params: { id: "1" }, data: { session: { email: "o@x" } }, waitUntil });
r = await adminPost(admin({ status: "confirmed" }));
await settle();
out.confirm = [r.status, sql.prepare("SELECT status FROM bookings WHERE id = 1").get().status, posts.slice()];
r = await adminGet({ request: new Request(`${ORIGIN}/admin/bookings/1`), env, params: { id: "1" }, data: { session: {} } });
out.adminPage = await r.text();
// saving notes alone (no status change) mails nobody
posts.length = 0;
await adminPost(admin({ owner_notes: "bring the spa kit" }));
await settle();
out.notesOnly = posts.length;

// 4. the customer moves it by the link (POST), then the slot they left is open again
posts.length = 0;
r = await managePost({ request: form("/book/manage", { t, action: "move", slot: "2" }, { accept: "text/html" }), env, waitUntil });
await settle();
out.moved = [r.status, (await r.text()).includes("Moved."), sql.prepare("SELECT slot_id, starts_at, status FROM bookings WHERE id = 1").get(), posts.slice()];
if (WITH_BOOK) out.jobAfterMove = sql.prepare("SELECT date FROM jobs WHERE ref = '1'").get();
// moving to a full slot (3 is Dana's second booking) is refused, nothing changes
r = await managePost({ request: form("/book/manage", { t, action: "move", slot: "3" }), env, waitUntil });
out.full = [(await r.text()).includes("just taken"), sql.prepare("SELECT slot_id FROM bookings WHERE id = 1").get().slot_id];
// from another site: refused
r = await managePost({ request: new Request(ORIGIN + "/book/manage", { method: "POST", headers: { origin: "https://evil.example", "content-type": "application/x-www-form-urlencoded" }, body: new URLSearchParams({ t, action: "cancel" }) }), env, waitUntil });
out.foreign = [(await r.text()).includes("another site"), sql.prepare("SELECT status FROM bookings WHERE id = 1").get().status];

// 5. the calendar feed
const ics = async (k) => { const res = await feed({ request: new Request(`${ORIGIN}/api/bookings.ics?key=${k}`), env }); return [res.status, res.headers.get("content-type"), await res.text()]; };
out.feed = await ics("feedkey123");
out.feedBad = await ics("wrong");
out.feedNone = await ics("");

// 6. the owner moves it on /admin, then the customer cancels by the link
posts.length = 0;
await adminPost(admin({ action: "move", slot: "1" }));
await settle();
out.ownerMove = [sql.prepare("SELECT slot_id FROM bookings WHERE id = 1").get().slot_id, posts.slice()];
posts.length = 0;
r = await managePost({ request: form("/book/manage", { t, action: "cancel" }), env, waitUntil });
await settle();
out.cancelled = [(await r.text()).includes("Cancelled."), sql.prepare("SELECT status FROM bookings WHERE id = 1").get().status, posts.slice()];
if (WITH_BOOK) out.jobAfterCancel = sql.prepare("SELECT status FROM jobs WHERE ref = '1'").get();
out.afterCancel = (await getManage(t))[1].includes("can&#39;t be changed here") || (await getManage(t))[1].includes("can't be changed here");
out.feedAfter = (await ics("feedkey123"))[2].includes("BEGIN:VEVENT");
// the owner marks the second booking done: the job is done and last_seen moves
await adminPost({ ...admin({ status: "done" }), params: { id: "2" }, request: form("/admin/bookings/2", { status: "done" }) });
if (WITH_BOOK) out.done = [sql.prepare("SELECT status, date FROM jobs WHERE ref = '2'").get(), sql.prepare("SELECT last_seen FROM customers").get()];

out.utc = [utcStamp("2026-10-06T09:00"), utcStamp("2026-12-01T09:00"), utcStamp("2026-03-08T03:00"), utcStamp("2026-10-06T09:00", "America/New_York")];
out.expiry = [manageExpiry("2026-10-10T09:00", Date.parse("2026-10-01T00:00Z") / 1000), manageExpiry("2027-12-01T09:00", Date.parse("2026-10-01T00:00Z") / 1000)];
out.day3 = day(3, "09:00");
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(node_ok(), "needs node with node:sqlite")
class BookingFunctionsTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        shutil.copytree(test_db.TEMPLATE / "functions", self.work / "functions")
        shutil.copytree(COLL / "bookings" / "functions", self.work / "functions", dirs_exist_ok=True)
        (self.work / "functions" / "_admin" / "collections.js").write_text(
            'import bookings from "./bookings.js";\nimport slots from "./slots.js";\nexport default { bookings, slots };\n')
        (self.work / "bookings.sql").write_text((COLL / "bookings" / "migrations" / "0001_bookings.sql").read_text())
        (self.work / "customers.sql").write_text((COLL / "customers" / "migrations" / "0001_customers.sql").read_text())
        (self.work / "run.mjs").write_text(SCRIPT)

    def tearDown(self):
        self.tmp.cleanup()

    def run_js(self, *args):
        r = subprocess.run([node_ok(), "--no-warnings", "run.mjs", *args], capture_output=True, text=True, cwd=self.work)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    @staticmethod
    def fields(post):
        return dict(urllib.parse.parse_qsl(post["body"]))

    def assertSigned(self, post):
        sig = post["headers"].get("x-booking-signature")
        self.assertEqual(sig, hmac.new(KEY.encode(), post["body"].encode(), hashlib.sha256).hexdigest(),
                         "the HMAC patchlamp.com checks (App\\Support\\BookingSignature) is of the exact body")

    def test_the_whole_life_of_a_booking(self):
        out = self.run_js("book", "key", KEY)
        self.assertEqual(out["booked"][0], 200)
        first = out["posts"][0]
        self.assertEqual(first["url"], "https://patchlamp.test/f/demo-service/booking")
        self.assertSigned(first)
        f = self.fields(first)
        self.assertEqual((f["kind"], f["by"], f["ref"], f["email"], f["notes"]), ("requested", "owner", "1", "Dana@Example.com", "gate 12"))
        self.assertTrue(f["manage"].startswith("https://demo-service.pages.dev/book/manage?t=1."), f["manage"])
        self.assertEqual(first["headers"]["origin"], "https://demo-service.pages.dev")

        # (d) the customer book: one customer, a booking isn't a visit, one job per booking
        customers, jobs = out["book1"]
        self.assertEqual(customers, [{"name": "Dana Ruiz", "phone": "801-555-0134", "email": "dana@example.com", "last_seen": None, "source": "booking"}])
        self.assertEqual(jobs, [{"what": "Spa check", "date": out["day3"][:10], "status": "booked", "source": "booking", "ref": "1"}])
        self.assertEqual(out["book2"], [1, 2], "the same phone, spelt differently, is the same customer")

        token, ok, tampered, expired, junk = out["token"]
        self.assertEqual((ok, tampered, expired, junk), (1, None, None, None))

        status, page = out["manage"]
        self.assertEqual(status, 200)
        for s in ("Your booking", "Spa check", "Move my booking", "Cancel my booking", "requested — not confirmed yet", "noindex"):
            self.assertIn(s, page)
        self.assertNotIn('value="3"', page, "a full slot isn't offered")
        for status, page in (out["manageBad"], out["manageNone"]):
            self.assertEqual(status, 200)
            self.assertIn("This link isn&#39;t right, or it has run out.", page)

        # (a) the owner confirms: the customer is mailed "confirmed", with the link
        status, row_status, posts = out["confirm"]
        self.assertEqual((status, row_status), (303, "confirmed"))
        self.assertEqual(len(posts), 1)
        self.assertSigned(posts[0])
        f = self.fields(posts[0])
        self.assertEqual((f["kind"], f["by"]), ("confirmed", "owner"))
        self.assertIn("/book/manage?t=", f["manage"])
        self.assertNotIn("notes", f, "the customer's notes only go with the owner's first copy")
        self.assertIn("Move to another time", out["adminPage"])
        self.assertIn("Confirming or cancelling emails Dana@Example.com", out["adminPage"])
        self.assertEqual(out["notesOnly"], 0)

        # (b) the customer moves it by the link: the row, the owner mailed, the job's date
        status, said, row, posts = out["moved"]
        self.assertTrue(said)
        self.assertEqual((row["slot_id"], row["status"]), (2, "confirmed"))
        f = self.fields(posts[0])
        self.assertEqual((f["kind"], f["by"], f["name"]), ("moved", "customer", "Dana Ruiz"))
        self.assertIn("was", f)
        self.assertEqual(out["jobAfterMove"]["date"], row["starts_at"][:10])
        self.assertEqual(out["full"], [True, 2])
        self.assertEqual(out["foreign"], [True, "confirmed"])

        # (c) the feed: the confirmed booking, in UTC, with the details; a wrong key is a 404
        status, ctype, ics = out["feed"]
        self.assertEqual((status, ctype), (200, "text/calendar; charset=utf-8"))
        self.assertIn("BEGIN:VCALENDAR\r\n", ics)
        self.assertIn("UID:booking-1@demo-service.pages.dev", ics)
        self.assertIn("SUMMARY:Dana Ruiz", ics)
        self.assertRegex(ics, r"DTSTART:\d{8}T\d{6}Z\r\n")
        self.assertIn(r"Phone: (801) 555-0134\nEmail: Dana@Example.com", ics.replace("\r\n ", ""))
        self.assertNotIn("Dana\r\n", ics, "Dana's second booking is only requested, not on the calendar")
        self.assertTrue(all(len(line.encode()) <= 75 for line in ics.split("\r\n")), "folded at 75 octets")
        self.assertEqual(out["feedBad"][0], 404)
        self.assertEqual(out["feedNone"][0], 404)
        self.assertNotIn("Dana", out["feedBad"][2])

        slot, posts = out["ownerMove"]
        self.assertEqual(slot, 1)
        self.assertEqual((self.fields(posts[0])["kind"], self.fields(posts[0])["by"]), ("moved", "owner"))

        said, st, posts = out["cancelled"]
        self.assertEqual((said, st), (True, "cancelled"))
        f = self.fields(posts[0])
        self.assertEqual((f["kind"], f["by"]), ("cancelled", "customer"))
        self.assertNotIn("manage", f, "no link to a booking that's gone")
        self.assertEqual(out["jobAfterCancel"]["status"], "cancelled")
        self.assertTrue(out["afterCancel"])
        self.assertFalse(out["feedAfter"], "a cancelled booking drops out of the feed")
        job, cust = out["done"]
        self.assertEqual(job["status"], "done")
        self.assertEqual(cust["last_seen"], job["date"], "done moves last_seen to the booking's day")

        self.assertEqual(out["utc"], ["20261006T150000Z", "20261201T160000Z", "20260308T090000Z", "20261006T130000Z"])
        start = int(__import__("datetime").datetime(2026, 10, 10, 9, tzinfo=__import__("datetime").timezone.utc).timestamp())
        base = int(__import__("datetime").datetime(2026, 10, 1, tzinfo=__import__("datetime").timezone.utc).timestamp())
        self.assertEqual(out["expiry"], [start + 2 * 86400, base + 120 * 86400])

    def test_without_the_key_or_the_book_a_booking_still_lands_and_the_owner_is_mailed(self):
        out = self.run_js("nobook", "nokey")
        self.assertEqual(out["booked"][0], 200)
        f = self.fields(out["posts"][0])
        self.assertEqual(sorted(f), ["email", "name", "notes", "phone", "time"], "today's unsigned owner copy, nothing more")
        self.assertNotIn("x-booking-signature", out["posts"][0]["headers"])
        self.assertEqual(out["confirm"][2], [], "no key: the owner's changes mail nobody")
        self.assertEqual(out["manage"][0], 200)
        self.assertIn("This link isn&#39;t right", out["manage"][1], "no key: no manage links at all")
        self.assertEqual(out["feed"][0], 404, "no feed key: no feed")

    def test_the_bookings_copy_of_the_customer_lib_is_the_books_own(self):
        self.assertEqual((COLL / "bookings" / "functions" / "_lib" / "customers.js").read_bytes(),
                         (COLL / "customers" / "functions" / "_lib" / "customers.js").read_bytes(),
                         "bookings ships customers.js so a site without the book still builds; keep the two the same")


class DbBookingsTest(unittest.TestCase):
    """`db bookings` on the fake wrangler: the keys, the feed address, the upgrade of an older site."""
    setUp = test_db.DbTest.setUp
    tearDown = test_db.DbTest.tearDown
    row = test_db.DbTest.row
    register = test_db.DbTest.register
    make_repo = test_db.DbTest.make_repo
    db = test_db.DbTest.db

    def secret(self):
        (self.root / "env").write_text("PATCHLAMP_RELAY_SHARED_SECRET=shh\n")

    def test_without_bookings_it_says_add_them_first(self):
        r = self.db("bookings", "setup")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("db add bookings", r.stderr)

    def test_setup_keeps_the_feed_key_in_the_registry_and_never_prints_a_key(self):
        self.assertEqual(self.db("add", "bookings").returncode, 0)
        r = self.db("bookings", "setup")
        self.assertNotEqual(r.returncode, 0, "no relay secret: says so")
        self.assertIn("PATCHLAMP_RELAY_SHARED_SECRET", r.stderr)
        self.secret()
        r = self.db("bookings", "setup", "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("bookings_feed_key", (self.root / "sites.json").read_text(), "a dry run keeps nothing")
        r = self.db("bookings", "setup")
        self.assertEqual(r.returncode, 0, r.stderr)
        key = json.loads((self.root / "sites.json").read_text())["acme"]["acme-site"]["bookings_feed_key"]
        derived = hmac.new(b"shh", b"booking-mail:acme", hashlib.sha256).hexdigest()
        self.assertNotIn(key, r.stdout)
        self.assertNotIn(derived, r.stdout)
        self.assertIn("BOOKINGS_FEED_KEY, BOOKING_KEY", r.stdout)
        self.assertIn("site publish acme-site", r.stdout)
        # the feed address carries the key; a second setup keeps the same one
        r = self.db("bookings", "feed", "--json")
        out = json.loads(r.stdout)
        self.assertEqual(out["url"], f"https://acme-site.pages.dev/api/bookings.ics?key={key}")
        self.assertTrue(out["webcal"].startswith("webcal://acme-site.pages.dev/"))
        self.assertFalse(out["new_key"])
        self.db("bookings", "setup")
        self.assertEqual(json.loads((self.root / "sites.json").read_text())["acme"]["acme-site"]["bookings_feed_key"], key)
        r = self.db("bookings", "feed")
        for s in ("Google Calendar", "Add Subscribed Calendar", "Subscribe from web", "Keep this address to yourself"):
            self.assertIn(s, r.stdout)
        r = self.db("bookings", "feed", "--new", "--json")
        self.assertNotEqual(json.loads(r.stdout)["url"], out["url"])
        st = json.loads(self.db("bookings", "status", "--json").stdout)
        self.assertEqual((st["files_behind"], st["feed_key_in_registry"]), ([], True))

    def test_upgrade_brings_an_older_bookings_site_up_and_leaves_its_views_and_book(self):
        self.assertEqual(self.db("add", "bookings").returncode, 0)
        fn = self.repo / "functions"
        # the site as the old template left it: no manage page, no feed, the old api and thanks line
        (fn / "api" / "bookings.js").write_text("// old\n")
        for gone in ("api/bookings.ics.js", "book/manage.js", "admin/bookings/[id].js", "_lib/bookings.js", "_lib/customers.js"):
            (fn / gone).unlink()
        (fn / "_admin" / "bookings.js").write_text("// the owner calls them Appointments\n")
        (self.repo / "index.html").write_text("<p>Booked — we've got you down and we'll confirm by email or phone.</p>")
        st = json.loads(self.db("bookings", "status", "--json").stdout)
        self.assertEqual(len(st["files_behind"]), 6)
        doc = self.db("doctor").stdout
        self.assertIn("bookings: Functions 6 file(s) behind (db bookings upgrade)", doc)
        self.assertIn("bookings: calendar feed not set up", doc)
        r = self.db("bookings", "upgrade", "--dry-run")
        self.assertIn("dry run", r.stdout)
        self.assertFalse((fn / "book" / "manage.js").exists())
        r = self.db("bookings", "upgrade")
        self.assertEqual(r.returncode, 0, r.stderr)
        for f in ("api/bookings.js", "api/bookings.ics.js", "book/manage.js", "admin/bookings/[id].js", "_lib/bookings.js", "_lib/customers.js"):
            self.assertEqual((fn / f).read_bytes(), (COLL / "bookings" / "functions" / f).read_bytes(), f)
        self.assertEqual((fn / "_admin" / "bookings.js").read_text(), "// the owner calls them Appointments\n", "the view is the site's")
        self.assertIn("a link to move or cancel it", (self.repo / "index.html").read_text())
        self.assertIn("nothing to do" if False else "already", self.db("bookings", "upgrade").stdout)
        # a site with the customer book keeps the book's own customers.js
        (fn / "_lib" / "customers.js").write_text("// the book's newer copy\n")
        self.assertEqual(json.loads(self.db("bookings", "status", "--json").stdout)["files_behind"], [])


if __name__ == "__main__":
    unittest.main()
