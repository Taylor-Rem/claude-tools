# {{NAME}} — website

The website for {{NAME}}. Plain HTML/CSS/JS with no build step: every file
here is served exactly as it is, by Cloudflare Pages, at {{URL}}.

To preview it on your own machine, run `python3 -m http.server` in this
folder and open http://localhost:8000. To change anything, see `CLAUDE.md`:
the site is meant to be maintained by asking Claude in plain English.

## If the site has a database

`site data` (claude-tools) gives a site its own Cloudflare D1 database and
an owner's page at `/admin`. Then `wrangler.toml` binds the database as
`DB`, `migrations/` holds the tables, and `functions/` is the server side
(Cloudflare Pages Functions, plain JavaScript, no build). Pages runs a
Function only for a path that has a file in `functions/` (`/admin/*`,
`/api/*`); every other page is served as a static file.

How it's deployed: `site publish` takes the committed tree and lays it out
the way `wrangler pages deploy` wants — the static files in one folder,
`functions/` and `wrangler.toml` beside it (never uploaded as pages) — so
the binding in `wrangler.toml` is what the live site gets, from git, on
every publish. The owner's sign-in secret (`SESSION_SECRET`) and address
(`ADMIN_EMAIL`) are Pages secrets on the project, never in this repo. The
sign-in link is emailed through patchlamp.com's form endpoint, so the site
holds no mail key. Anyone taking the site over keeps working with plain
`wrangler`: `wrangler pages dev` here for a local copy (secrets in
`.dev.vars`), `wrangler d1 migrations apply DB --remote` for the tables
(the same `d1_migrations` record `db migrate` keeps).
