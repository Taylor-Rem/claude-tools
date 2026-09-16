# {{NAME}} — website ({{REPO}})

This repo IS the website for {{NAME}}. There is no dashboard and no CMS: you
change the site by editing these files and pushing. Live at {{URL}}.

How to talk to the client, how texted photos arrive (`incoming/`, one level
up), and what counts as Taylor's work are all in the workspace `CLAUDE.md`
one level above this repo. This file covers only this site: what is in it,
how to change it, and how to check a change is live.

## What this site is

- Plain HTML/CSS/JS static files. **No frameworks, no build step, no npm, no
  external JS libraries.** If a change seems to need one, find the plain
  way or say it's out of scope.
- Two pages: `index.html` (home: hero, about, details) and `photos.html`
  (gallery). `404.html` is what the host shows for a missing page.
- One stylesheet, `css/style.css`. Colors and fonts are the tokens in `:root`
  at the top; change the look there, not scattered through the file.
- One script, `js/main.js` (fade-in on scroll). Motion is transform/opacity
  only, off under `prefers-reduced-motion`, and nothing is hidden with JS off.
- The header, nav, and footer are repeated in every `.html` file (no build
  step means no shared includes). When you edit them, make the same edit in
  **every page**.
- `images/` holds the photos. `_headers` and `_redirects` are read by the
  host, not served: `_headers` makes every page `no-cache` (so nobody ever
  sees a stale page) and `_redirects` holds the www → bare-domain rule.
  Leave both alone unless a page moves.
- **No trackers, no analytics, no cookie banners, no home-built forms or
  checkout.** Anything that stores visitor information is Taylor's work.
- Placeholder content is marked with `REPLACE-ME` comments. Placeholders
  must look like placeholders; never invent facts, prices, hours, or quotes.

## How to change things

- **Copy** (about text, tagline, details, hours, contact): edit the text in
  `index.html`. Ask for anything you don't have; don't guess an address or
  a phone number.
- **A new photo**: save it as a JPG in `images/` with a plain name
  (`images/storefront.jpg`), about 1200px on the long side. Texted photos are
  already converted and resized; move them from `incoming/` (one level up)
  into `images/`. In `photos.html`, copy one whole `<li>…</li>` block (there
  is a commented example), set `src` and `alt`, and remove the "Photos coming
  soon" line once the gallery has a photo. `alt` is a short plain description
  of what's in the photo; never leave it empty. To change the home-page
  photo, replace the placeholder `<svg>` in `figure.about-photo` with
  `<img src="images/…" alt="…">`.
- **A new page**: copy `photos.html`, change the title and content, and add
  it to the nav in **every** page.
- **Colors / fonts**: the `:root` tokens in `css/style.css`.
- **A link** (Instagram, a booking site, a menu on another service): add it
  to the footer list in every page, or as a `.button` in the section it
  belongs to. Linking out is always fine; embedding third-party code is not,
  except a plain `<iframe>` embed from a service the client already uses
  (a map, a player, a list-provider signup form).

## Every change goes live — deploy check

"Done" means live at {{URL}}, not edited on disk. Relay sessions run from the
client workspace one level up, so git takes the form
`git -C repos/{{REPO}} …`; never `cd` into the repo first (that is always
blocked). After any requested change, without waiting to be asked:

1. Look at your work: `shot repos/{{REPO}}/<page>.html` (add `--mobile` for
   the phone layout) renders the page from disk and saves a picture under
   `shots/`; open it with Read. For anything to do with layout or style, also
   run `shot check repos/{{REPO}}/<page>.html`. Fix what's off before you
   push. If you touched HTML, also confirm the tags you edited are balanced.
2. Commit on `main` with a short plain-English message
   (`git -C repos/{{REPO}} add -A && git -C repos/{{REPO}} commit -m "…"`).
3. Push: `git -C repos/{{REPO}} push`. The repo is the record.
4. Publish: `site publish {{REPO}}`. It sends exactly what is committed to
   the host and prints the live URL once it is serving (seconds, not
   minutes). It refuses if anything is uncommitted or unpushed — that is
   the point, not a bug: fix the git step and run it again.
5. Confirm the live site serves the change, with exactly this shape (no
   pipe, no redirect):

       curl -s {{URL}}PAGE.html

   (for the home page, `curl -s {{URL}}`). Read the output and look for the
   new content yourself. Only say it's live once you have seen it there.
   There is no cache to wait out: every page is served `no-cache`, so a
   phone that reloads sees the new page.

Undo the last change with `git -C repos/{{REPO}} revert HEAD`, push, and
publish again. Never force-push, never rewrite history. This is standing
permission from Taylor: don't ask "should I push?" for anything the client
asked for. Do stop if a change would break a rule in this file or delete
something the request didn't clearly ask to delete.

## Hosting (for Taylor)

Cloudflare Pages, one project per site, published by `site publish` from
the committed tree of this repo's `main` (direct upload; no build, no
Cloudflare-side git connection). The repo is on GitHub under `{{OWNER}}`
and stays the record; the host is a mirror of it. A custom domain is
`SITE_ADMIN=1 site domain {{REPO}} example.com` from the workspace (adds
the domain to the project, writes the www → apex rule into `_redirects`,
prints the two DNS lines for the registrar). Handing the repo to the
client at the end is `site transfer {{REPO}} <their-github-user>`.
