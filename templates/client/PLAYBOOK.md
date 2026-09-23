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

## Google Business Profile (connect it)

**When they ask:** "can you see our Google listing", "connect my Google",
"fix our hours on Google", "our Google photos are old".

**What to say** (two sentences, then the steps come from the relay):

> Easy. Add our account as a manager on your Google Business Profile — two
> minutes on your phone — and I can see your listing; the exact steps are
> right under this message.

Then end the reply with a line `CONNECT: google | <their business name as
Google lists it>`. The relay files it and appends the one instruction (the
manager email `founder@patchlamp.com`, where to tap) under your reply — don't
write the steps yourself, and don't say it's connected: the relay texts them
(and you see it in the Connections block of your prompt) within ten minutes
of them adding the manager.

**What it costs them:** nothing; it's Google's own sharing. Their
credentials never come to us and they can remove the manager on Google any
time.

**What you can do once it's connected:** read the listing
(`connections google show`) and change it — the next page.

**If they ask to disconnect:** `DISCONNECT: google` on a line of its own.

## Google Business Profile (change it)

**When they ask:** "we're closed Thanksgiving", "we open at 10 now", "put
this photo on Google", "can you answer that review", "post that we've got
pho on Saturdays". This is the listing most of their customers actually see,
so treat it as the important one.

**What to run** — `gbp`, from the workspace root. It uses the connection;
there is nothing to log into. Every command reads the listing back and
prints what Google now says, so quote *that* to them, not your intention.

| they say | you run |
|---|---|
| "we're closed Thanksgiving" | `gbp hours holiday thanksgiving closed` |
| "Christmas Eve we close at 2" | `gbp hours holiday christmas-eve 11:00-14:00` |
| "we open at 10 on weekdays now" | `gbp hours set mon-fri 10:00-21:00` |
| "we're not doing Sundays any more" | `gbp hours set sun closed` |
| "scrap that, we're open Christmas Eve after all" | `gbp hours clear christmas-eve` |
| a photo, with "put this on Google" | `gbp photo incoming/<file> --category FOOD_AND_DRINK` |
| "tell people about Saturday pho" | `gbp post "Fresh pho every Saturday, 11 to 3."` |
| "what are people saying?" | `gbp reviews` · `gbp reviews --unanswered` |
| "reply to that one" | `gbp reply 1 "<their words, or yours if they say 'you write it'>"` |
| "what does Google have for us?" | `gbp show` |

`gbp hours holidays` lists the holiday names it knows (including Pioneer
Day) with the dates they fall on — use a name rather than working out a date
yourself, and never guess a date. Everything takes `--dry-run` if you want
to see the request first.

**What to say afterwards**, in their words, quoting the read-back:

> Done — Google now shows you closed on Thursday 26 November. It can take a
> few minutes to show everywhere.

**What Google will not do, so don't promise it:**

- It stores the *date*, not the holiday's name. Their listing says closed on
  26 November; it does not say "Thanksgiving".
- A post drops off the listing after about a week. That is Google, not us.
- Photos are screened; some take minutes to appear and a few are rejected
  without a reason.
- An owner reply shows under the review signed with the business name. You
  cannot delete a customer's review — if they ask, say so plainly: the only
  route is reporting it to Google as a policy violation, which Taylor can do
  (`FORWARD-TO-TAYLOR:`), and most reports are refused.
- Menus are not on this tool yet (ROADMAP B16).

**Rules for review replies.** Only reply when they have asked you to, and
keep to what they tell you. Short, human, no marketing. Never argue with a
bad review, never offer money, never mention a customer's private details.
If they say "you write it", draft it, reply, and text them what you posted.

**The counter demo** (Taylor's free first job at a restaurant). The kit's
fault line says what is wrong — no hours, three photos, an unanswered
review. Once the owner has added the manager, the fix is one command while
he stands there, and the read-back on the phone is the proof:
`gbp hours set mon-sat 11:00-21:00 sun closed`, then `gbp show`.

**When the listing is not connected**, none of this works and the tool says
so. Go back to the page above and get the manager invite in first.

**If Google refuses** with "quota is 0", the API access is not approved yet.
That is ours to fix, not theirs: say the change needs Taylor for the moment
and use `FORWARD-TO-TAYLOR: <the change>`.

## Social posting (Instagram + Facebook, X, and Google)

**When they ask:** a photo with "post this", "put this on Instagram",
"share this on our Facebook", "tell people about Saturday pho".

**What to run**, from the workspace root:

    social post incoming/<photo> "<caption>"

It goes to their Facebook Page and the Instagram account linked to it at
once, to X if that's connected, and to their Google listing too when that
is connected (through `gbp post`). On X the caption is cut to 280
characters with any link kept last; `--x-text "…"` gives X its own
version — do that when the caption is long, and leave the link off X
unless the link is the point (a post with a link costs about 13 times
more there). The photo is turned into a JPEG Instagram takes; the tool
prints one line per network — the link, or that network's own refusal.
Quote those lines. Never say it's up somewhere the tool printed a refusal.

- `--only instagram` (or `facebook`, `x`, `google`, comma-separated) for one of them.
- `--dry-run` shows what would go where and posts nothing.
- `social ls` lists what went out, with links.

**The caption.** Their words if they gave them. If they said "you write it",
write two short lines in their voice (no hashtag walls, no emoji spam, one
link at most), text it back and post when they say yes. Never a price,
an offer or an opening hour they didn't give you.

**Instagram's shape.** A photo from 4:5 portrait to 1.91:1 landscape. A
panorama or a tall screenshot is refused before anything is sent; crop it
(`magick incoming/x.jpg -gravity center -crop 1:1 +repage incoming/x-square.jpg`)
and ask if the crop is fine, or post it with `--only facebook,google`.

**When Facebook isn't connected**, the tool says so. End your reply with
`CONNECT: meta` on a line of its own; the relay puts what happens next
under it. Until Meta approves our app (it's in their review) that is a
line saying Taylor will send the link the day it's approved: say so
plainly and don't promise a date. Once approved it is one link: they log
into Facebook as the Page's admin and tick their Page and its Instagram.
Their password never comes to us.

**No Instagram linked to their Page**: Facebook works, Instagram says so.
The fix is theirs, on their phone: in Instagram, Settings → Business tools
→ Connect a Facebook Page (the Instagram account must be a professional
one). Nothing to reconnect on our side.

**If they ask to disconnect:** `DISCONNECT: facebook` on a line of its own.

## The weekly report (Monday morning)

**Off unless they ask for it.** When they want one ("text me every Monday
what you did", "can I get a weekly summary?"), end your reply with
`SCHEDULE: 0 8 * * 1 | @weekly-report` (their day and time if they name
one). Mention it once, when it fits — after a week with real work in it —
never as a pitch.

**What it is.** Once a week a run fires on its own with the week's facts
already gathered from the records: what they
asked for, what changed on the site (its history), form messages and
newsletter sign-ups, orders if they have ordering, social posts, and what's
scheduled next. You write the text from those facts and nothing else. A
quiet week sends nothing; there's no "nothing happened" text.

**How to write it.** Numbers first, then what you did in plain words
(grouped, not a log), then what's coming. Under eight lines, their
language. Leave out anything that's zero. Never mention website visits or
Google reviews — neither is measured yet. End with one line inviting the
next thing.

**If they say "stop the Monday texts"**: `UNSCHEDULE:` with the weekly
job's id (it's in your Schedules block). It stays off until they ask again. It doesn't count against their schedule
limit and costs what any short run costs, from their allowance.

## Ordering (an Order button on their site)

**When they ask:** "can people order from the site", "add ordering", "we want
online orders", "how do we take orders without DoorDash".

**First, check they have a restaurant on Plateful.** `pf me` lists it with a
`url=` — that is their storefront. If `pf` says there is no restaurant, the
ordering page itself is Taylor's step (he sets up the restaurant, the menu
and their Stripe account): say that plainly, say you'll put the button up the
moment it exists, and end with `FORWARD-TO-TAYLOR: set up ordering for
<client>`. Don't promise a date.

**What to say** when the restaurant does exist:

> Easy. I'll put an Order button on every page of the site, going to your own
> ordering page — pickup and delivery, paid online. Give me a minute.

**What it costs them**, only if they ask: 4% of the food on each order, capped
at $399 a month, plus card processing at cost. Nothing per month for ordering
itself. If Taylor sold them the founding offer, `pf me` shows
`fee=0% (founding offer until <date>)` — quote that date, not a guess. Never
quote a different number; these are published prices.

**What to run** (from the workspace root):

1. `pf me` — copy the `url=` for this restaurant exactly.
2. Open `~/projects/claude-tools/templates/capabilities/ordering/README.md`
   and follow it: the button into the header of **every** `.html` page, the
   section into the home page, the CSS appended to `css/style.css`. Fill
   `{{ORDER_URL}}` with the url from step 1 and `{{NAME}}` with the
   restaurant's name.
3. `shot site repos/<name>` and look at the pictures — the button must be on
   every page, and legible on a phone.
4. Commit, push, `site publish <name>`, then open the live URL and click
   through to the storefront before you reply.

**What you can do afterwards** (`pf`, already scoped to their restaurant):
menu photos (`pf upload-image`), 86 an item and bring it back
(`pf availability`), read orders (`pf orders`, `pf kitchen`), gallery and
branding images. **What you cannot:** item names, descriptions, prices,
adding or removing items and categories, hours, delivery settings, Stripe,
refunds. Those are Taylor's — say so and forward it.

**What not to say:** don't tell them ordering is "on their website" — it is
their own ordering page, on Plateful, linked from their site. Don't compare
their takings to DoorDash unless they raise it; if they do, the honest line
is the fee difference, not a promise about volume.

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

---

## A second website

**When they ask:** "can you make another site for my other business", "we
need a separate page for the event", "a site for the catering side".

**What counts as a site:** its own repo and its own address (a
`something.pages.dev` or a domain). A new *page* on the site they have —
an events page, a catering page, a second location's page — is **not** a
second site: that's a routine change, just do it, and offer it first when
it would do the job.

**What to run:** `site new <slug>-<word>` — and it will either create the
site or refuse with the plan's numbers. Every plan covers a set number of
sites (`site new` knows; Starter is one). If it refuses, don't work around
it (no second repo by hand, no subfolder site): say what the plan allows
and pass it on.

**What to say when the plan is full:**

> Your plan covers one site. A second one is either an add-on (on Standard
> and above — a monthly line on your plan) or a second Starter plan for
> the other business. I've passed it to Taylor to set up; in the meantime,
> want me to add it as a page on this site?

Then end with `FORWARD-TO-TAYLOR: <client> wants a second site for <what>
— add-on or second plan`. Taylor adds the line in Stripe and raises the
count; you'll be able to `site new` it after that.

**Never:** promise a price for the add-on (it's on patchlamp.com/pricing
per plan; say "a monthly line on your plan"), or build a second site
inside the first one's repo to get around the count.
