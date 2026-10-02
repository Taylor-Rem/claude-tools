# Build: the site and the one line

You are building one small local business's preview website from what we
know about them, and the one sentence of the message Taylor will send them.
The bar: every sentence on the site is true of this business and traced to a
fact; the look is one the owner would be glad to show a customer; the only
things missing are their own photos and their yes.

You write two files, and never HTML:

- `content.json` — the site, as sections. `leads preview` renders it.
- `message.json` — the one sentence of the message that is about them.

A draft `content.json` is already here: code wrote it from the `high` facts,
with the photos already chosen and the look already set. Make it read like
this business's own site, not like a form filled in. Keep it true.

Caps: **20 minutes, 80 turns.** When you are done, stop.

## What you have

- `facts.json`: what research found. Each fact has an `id`, a `text`, a
  `confidence` and its source. **The site uses `high` facts only.** `medium`
  facts never appear on the site, not even softened.
- `listing.json`, `packet.json`: the Google listing and the brief.
- `images/`: the photos code chose (stock, never the business's own): the
  hero and up to four more, each with a `.json` beside it (its id, its alt).
- `content.draft.json`: the draft as code wrote it, to compare against.

## content.json (schema 1)

```json
{"schema": 1, "slug": "…", "template": "service", "look": "classic", "name": "Pinnacle Painting",
 "place_id": "…", "city": "Sandy", "category": "painter",
 "cta": {"text": "Call (801) 555-0101", "facts": ["listing:phone"], "href": "tel:+18015550101"},
 "images": {"hero": {"file": "images/hero.jpg", "source": "stock", "id": "pexels:123",
                     "credit": "Photo: … on Pexels", "alt": "A freshly painted kitchen"}},
 "sections": [
   {"type": "hero", "image": "hero",
    "kicker": {"text": "Painter · Sandy", "facts": ["listing:category", "listing:city"]},
    "heading": {"text": "Kitchen cabinets refinished, rooms repainted", "facts": ["f4", "f6"]},
    "sub": {"text": "…", "facts": ["…"]},
    "secondary": {"text": "Ask for a quote", "facts": []}},
   {"type": "services", "heading": {"text": "What we do", "facts": []},
    "items": [{"title": {"text": "Cabinet refinishing", "facts": ["f4"]},
               "text": {"text": "…", "facts": ["f4"]}}]}
 ],
 "generic": ["Ask for a quote", "What we do"]}
```

- **Every text is `{"text": …, "facts": [ids]}`.** A text with facts may say
  only what those facts say. The fact ids are `facts.json` ids of `high`
  facts, or these listing fields, which code reads itself: `listing:phone`,
  `listing:rating`, `listing:hours`, `listing:city`, `listing:category`,
  `listing:maps`.
- **A text with no facts** must be listed, word for word, in `generic[]`.
  Generic is for headings and button labels ("What we do", "Ask for a
  quote") and **at most three sentences** on the whole preview.
- Keep `slug`, `template`, `look`, `name`, `place_id`, `city`, `category` as
  the draft has them. The look is set by the run so that no one look takes
  over the night; don't change it.
- Sections, in the order you want them, one `hero` exactly:
  - service template: `hero, proof, services, area, about, gallery, quote,
    booking, details`. **Keep `quote` and the `booking` section** (it is
    `"claim_only": true`: the claimed site gets the calendar, the preview
    shows nothing of it). Without both the claim refuses.
  - portfolio template: `hero, proof, services, area, about, gallery,
    contact, details`.
  - `hero`: `heading` (required), `kicker`, `sub`, `secondary`, `note`,
    `image`. `proof`: `items` (short texts, an item may carry `href`).
    `services`: `heading`, `items` of `{title, text}`, `intro`. `area`:
    `heading`, `text` or `places`. `about`: `heading`, `paragraphs`, `image`.
    `gallery`: `heading`, `images` (keys of `images{}`). `quote`, `booking`,
    `contact`: `heading`, `intro`, `phone`, `links`. `details`: `heading`,
    `where`, `hours`, `phone`, `links`.

## What reads well

- The first phone screen says who they are, what they do, where, and how to
  reach them. Lead with the work, not the category ("Kitchen cabinets
  refinished in Sandy" beats "A painter in Sandy").
- Their name once on the first screen (the header already shows it).
- Hours phrased for a person: a trade Google shows "Open 24 hours" is "Call
  or text any day" (use `hours.say` from `facts.json` when it is there).
- Plain words. No filler ("quality service you can trust", "your satisfaction
  is our priority"): if a fact doesn't say it, it isn't there.
- Short. Three to five services, one or two about sentences.

## The never list (`prep check` fails the site)

1. **A review's words.** Six words in a row shared with any review. Say what
   customers mention in your own words, or leave it out.
2. **A person's name.** Not the owner, a worker or a reviewer; not a first
   name from a review; never a fact's `source.words`. The business's own
   name is fine even when it holds a name.
3. **A price**, a rate, "per hour", a dollar sign.
4. **A street address.** A town or a list of towns served is fine.
5. **Guarded words** — licensed, insured, bonded, certified, guarantee,
   warranty, award, best, #1, years, since, family-owned, free estimate —
   only in a text whose facts include a `high` `credential` or `since` fact.
6. **A `medium` fact**, or a fact id that doesn't exist.

## Photos

The photos in `images/` were chosen by code so that no other preview uses
them. If one doesn't fit the trade (it must show work, tools or places,
never a person standing in for the owner), look for another:

    img stock "painted kitchen cabinets" -n 3 --orientation landscape --width 1600 --out images/alt --json

It prints the files with their ids; put the one you choose into `images{}`
with `"source": "stock"`, its `"id": "pexels:<id>"`, its credit and an alt
that says what the photo shows. Stock only; nothing generated.

## The message line (`message.json`)

Taylor's message to them is fixed text (`prep message` shows it). You write
the one sentence that shows we looked at *them*: from `high` facts, at most
140 characters, no price, no guarded word, no exclamation mark, no name. It
comes right after "So I built you one." and before the link, so it says what
you put on the page and why, in words they'd use ("so that's the first thing
on the page"), never how the site works.

```json
{"specific": {"text": "Your reviews keep mentioning the cabinet work, so I put that first.", "facts": ["f4"]}}
```

## The commands (the only ones you can run here)

    leads preview --from content.json --out site          # render the site into site/
    shot site/index.html --mobile --out shots/phone.png     # look at the first phone screen
    shot site/index.html --mobile --full --out shots/phone-full.png
    shot site/index.html --out shots/desktop.png
    prep check                                              # the gates, as code will run them
    prep message                                            # the message, filled, and its lint

**One plain command at a time.** No `&&`, no `;`, no pipes, no redirects, no
`$(…)`, and no `cd` — you are already in this directory. A chained command is
refused whole, so run them one after another.

Open a screenshot with Read to look at it. Render, look, fix, until `prep
check` prints OK and the site reads well on the phone. Then stop.

If a fix list arrives later (from `prep check` or from the judge), fix
`content.json` and `message.json`, render, look, run `prep check` again, stop.
