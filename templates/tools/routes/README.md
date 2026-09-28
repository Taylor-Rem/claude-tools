# routes — a worked example of a web tool (ROADMAP B40)

**Not a collection.** This is what Patch built by text for the service demo
(clients/demo-service, Juniper Flats Pool & Spa) from *"keep my pool
routes: stops per day, done or skipped"*, kept here as the worked example
PLAYBOOK § Web tools points at. A tool for another business is built the
same way in that client's repo, in that owner's words; copy from here, don't
`db add` it.

The three parts, all in the client's repo:

- `migrations/NNNN_routes.sql` — one row per stop per day: `day` (a date on
  the site's clock), `stop` (the order), `customer`, `job`, `area`, and the
  house columns `status` (to do / done / skipped), `notes`, `created_at`,
  `updated_at`.
- `functions/_admin/routes.js` — the /admin view: today's stops first (the
  day chooser starts on today), in stop order, a one-tap **done** /
  **skipped** on each row, and the totals line "7 stops · 2 to do · 4 done ·
  1 skipped". Registered in `functions/_admin/collections.js`.
- No public Function: only the owner writes to it.

`seed.sql` is the demo's sample week (relative dates).

The texts it answers (the site's clock is Denver: `date('now', '-6 hours')`):

    "what's on today?"      db query "SELECT stop, customer, job, status FROM routes WHERE day = date('now','-6 hours') ORDER BY stop"
    "Sam's done"            db exec "UPDATE routes SET status = 'done', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ','now') WHERE day = date('now','-6 hours') AND customer = 'Sam Example'"
    "skip Quinn, gate locked"  … SET status = 'skipped', notes = 'gate locked' …
    "add Drew Friday, stop 3"  db exec "INSERT INTO routes (day, stop, customer, job) VALUES ('2026-10-02', 3, 'Drew Example', 'Weekly service')"
    "how did today go?"     db query "SELECT status, COUNT(*) AS n FROM routes WHERE day = date('now','-6 hours') GROUP BY status"

No publish for any of them: /admin/routes reads the database.
