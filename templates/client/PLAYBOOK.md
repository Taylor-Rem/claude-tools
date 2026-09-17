# Playbook — things a client asks for that you set up yourself

Each page here is a capability: what to *say* when the client asks, what to
*run*, and what you can do for them afterwards. If a request matches a page,
it is not Taylor's work — say "easy" and do it. If it isn't in here, it is
Taylor's work (see the workspace CLAUDE.md), and you say so.

Every sentence you say to a client from this file is also on
patchlamp.com's claims list, so keep to what it says; don't promise more.

---

## Newsletter / mailing list

**When they ask:** "can people sign up for our emails", "add a newsletter",
"a place to put your email", "a mailing list".

**What to say** (plain, two or three sentences):

> Easy. I'll put a sign-up box on the site — people type their email and
> they're on your list; each one gets a short "you're on the list" email
> with a way to leave. Then whenever you want to send something out, text
> me what it should say and I'll send it to everyone.

**What it costs them:** nothing extra — it's part of the plan. Sending an
issue counts against the usage allowance like any other change (fractions
of a cent per person).

**What to run** (from the workspace root, in this order):

1. `newsletter setup --contact <their email>` — registers the list on our
   side. Safe to re-run. The contact address is where contact/booking form
   posts go (below); if you don't know it, run it without `--contact` and
   ask them for one.
2. `newsletter form` — prints the sign-up box (HTML). Paste it into the
   site where they want it — usually the footer of **every page** (the
   template's `REPLACE-ME` sign-up line, or wherever the Sign Up button
   points). Style it with the site's own tokens; `newsletter form --css`
   prints starter CSS. Keep the hidden `website` field: it's the spam trap.
3. Look at it (`shot repos/<name>/index.html --mobile`), commit, push,
   `site publish <name>`.
4. Prove it: `curl -s <live url>` shows the form; then `newsletter status`.

Tell them where the box is and that you'll know when someone signs up.

**Afterwards, on request:**

- "how many people signed up" / "who's on the list" → `newsletter
  subscribers` (or `newsletter status` for the count). Read them the count;
  only read out addresses if they ask for them — it's their list.
- "send everyone …" → write the issue as a short markdown file in the
  workspace (plain words, their voice, no hype), then `newsletter send
  "Subject" issue.md`. It goes from *their name* `<news@patchlamp.com>`,
  replies come to their contact address, and every copy carries an
  unsubscribe link. Say how many it went to. Don't send without being asked
  to; if the wording is theirs, send it as written.
- "take me off / take X off the list" → the link in every email does it;
  if they ask you directly, say it needs the person's own click for now and
  pass the address to Taylor.

**What you can't do:** import a list from somewhere else, design HTML
templates, schedule sends, or see open/click stats. Say so plainly and
FORWARD-TO-TAYLOR if they need one of those.

---

## Contact / booking form

**When they ask:** "a contact form", "let people book us", "a way to reach
us from the site", "an RSVP".

**What to say:**

> Easy. I'll put a form on the site — name, email and a message (or
> whatever fields you want). Each one gets emailed to you the moment it's
> sent, and I keep a copy so you can ask me what came in.

**What to run:**

1. `newsletter setup --contact <their email>` if not already done — the
   same registration; the contact address is where posts are emailed.
   Without a contact address the form stores posts but nobody is told.
2. Build the form by hand on the page they want, posting to
   `https://patchlamp.com/f/<slug>/<form-name>` (`<slug>` is this
   workspace's slug; `<form-name>` is a short lowercase word like
   `contact` or `booking`): `<form action="…" method="post">`, any inputs
   you like with plain `name`s (up to 20 fields, `email` gets used as the
   reply-to), a hidden honeypot `<input name="website" tabindex="-1"
   autocomplete="off" style="position:absolute;left:-9999px">`, and a
   submit button. After a post the page reloads with `?sent=<form-name>`;
   show a thanks line from that the way the newsletter box does.
3. `shot`, commit, push, `site publish`, then test it yourself with a
   real post and `newsletter forms` to see it arrived.

**Afterwards:** "did anyone fill in the form" → `newsletter forms` (or
`--form booking`). Read them what came in.

**What you can't do:** file uploads, payments, a calendar, anything that
needs a login. Say so and FORWARD-TO-TAYLOR.

---

## Custom domain

**When they ask:** "can the site be at ourband.com", "we bought a domain".

**What to say:**

> Yes. Point the domain at the site — two settings at wherever you bought
> it — and it's live with a secure certificate within the hour. I'll send
> you the exact two lines to enter (or Taylor can do it with you).

**What to run:** nothing yourself — attaching the domain is one of the few
Taylor steps: `FORWARD-TO-TAYLOR: <client> wants <domain> on
<repo>` and tell the client Taylor will send the two DNS lines. (Taylor
runs `SITE_ADMIN=1 site domain <repo> <domain>`, which prints them.)

---

## Day one: they already have a website

**When it applies:** the workspace has a `live_url` and **no repo under
`repos/`** — the client signed up with a site that isn't ours to edit (a
Wix / Squarespace / GoDaddy page, an old hand-built one, whatever). Nothing
you can do there. Your job on day one is to rebuild it as a site we *can*
change by text, show them, and let them decide when to switch over.

**What to say** (first message after they verify, before they ask):

> Hi — I've had a look at your current site. I'm going to rebuild it so I
> can change it for you by text; you'll get a link to look at the new
> version, your current site stays exactly as it is, and nothing moves
> until you say so. If there's anything on the old site that's out of date,
> tell me now and I'll fix it in the new one.

**Which plan:** On **Standard**, the rebuild is what the first month's
usage is for. On **Starter** the rebuild isn't offered — Starter is the
template filled in by text — so instead: `site new`, fill the template with
what's on their old site (their words, their photos), and say so plainly:
"I've set up a fresh site from our template with your details; a full
rebuild of the old one is a Standard job."

**What to run:**

1. **Make the site:** `site new <slug>-site` (repo from the template,
   Pages project, first publish, the `pages.dev` URL into the workspace).
2. **Read the old site.** `shot text <live_url> --selector main` for each
   page's words; `shot <live_url> --full` and `--mobile` to see the layout,
   colours and what matters to them; `shot html <live_url> --selector 'a'`
   to find the pages (menu, about, contact, photos, shows…). Their
   **wording stays their wording** — copy it, fix nothing but typos and
   dates they tell you about. Photos: `shot html <live_url> --selector
   'img'` lists them; download what's theirs into `repos/<name>/images/`
   (`img` can fetch and resize a URL); anything you can't get, ask for.
3. **Rebuild it page by page in the template.** One page of theirs → one
   page of ours (`index.html` for home; copy `photos.html` as the pattern
   for a new page, add it to the nav on every page). Keep the template's
   look unless the old site has a clear identity (colours, a logo) — then
   carry that across with the site's own tokens in `css/style.css`. Don't
   invent content: an empty section is better than a made-up one.
4. **Check it:** `shot check repos/<name>`, then `shot repos/<name>
   --mobile` and Read the picture. Every link works, every image has alt
   text, nothing says REPLACE-ME.
5. **Publish it:** commit, push, `site publish <name>`. Send the preview:

   > Your new site is at <pages.dev URL> — have a look on your phone. Your
   > current site hasn't changed. Tell me anything that's wrong and I'll
   > fix it; when you're happy, say the word and I'll move your domain over.

   Attach a picture: `SEND-FILE: shots/<file>.png | the new home page on a phone`.
6. **When they say go:** the domain is Taylor's step (see *Custom domain*):
   `FORWARD-TO-TAYLOR: <client> is happy with <pages.dev URL>; move
   <their domain> over`. Tell them Taylor will send the two lines, or do it
   with them, and that the old site keeps serving until those change.

**Afterwards:** it's an ordinary site: edits by text, `site publish`, done.
The old site is theirs to switch off once the domain has moved.
