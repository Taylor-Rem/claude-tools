# Research: the facts file

You are researching one small local business so that a preview website can be
built for it tomorrow. The site may say only what is true of this business and
traced to a source. Your job is the facts file, `facts.json`: what we can say,
where we read it, and how sure we are. You write nothing else (a scratch
`notes.md` is fine).

Caps for this business: **8 web searches, 10 fetches, 15 minutes.** The
boundary counts them and refuses the next one; when a cap is spent, write what
you have. A thin, honest file beats a padded one.

## What you already have

- `packet.json`: the census row, the listing summary (phone, website link,
  rating, count, type, hours, whether Google shows it as a service-area
  business), the reviews numbered by `ref`, the reach row (an Instagram
  handle, a Facebook page, an email, each with the search that found it), the
  presence (what their website link is today) and the faults we computed.
- `listing.json`: the Google listing read itself. Its `googleMapsUri` is the
  URL of every `listing` and `review` source.

## The sources, in this order

1. **The listing** (`listing.json`): its fields and its reviews.
2. **Search** (WebSearch): start with `"<name>" <city> Utah`, then the phone
   number, then `"<name>" <category>`. A result's title, snippet and URL are a
   source of kind `search` even when the page itself is a Facebook or
   Instagram page (you read the result, never the page).
3. **Their own site**, if the listing or a search result shows one that is
   really theirs (their name, their phone): kind `own_site`. A free-builder
   page they made (Wix, GoDaddy, Google Sites) counts as their own site.
4. **Directory profiles** about this business: BBB, Yelp, Nextdoor, Angi,
   HomeAdvisor, Thumbtack, Houzz, Porch, a chamber of commerce: kind
   `directory`.
5. **Utah public records for the business itself**: the entity's status and
   date (`businessregistration.utah.gov`, `secure.utah.gov`), a licence in the
   business's name (DOPL). Kind `record`, a `.gov` URL. These are often forms
   a fetch can't fill; don't spend more than two fetches trying.

**Fetching a page:** the fetch hands you a summary unless you ask for the
page's own words. Give every fetch this prompt: *"Quote verbatim, with no
rewording, every line about the services offered, the towns served, the
hours, how long they've been in business, licences, and contact details."*
Copy `words` only from what comes back in quotes. After you finish, code
re-reads every own-site, directory and record source and looks for your
`words` on the page: a source whose words aren't there is set aside, and a
`high` fact that leaned on it drops to `medium`.

**Never fetched:** facebook.com, instagram.com, fb.com, threads, messenger,
whatsapp and every other Meta host. The boundary refuses them; don't try.

**Is it them?** A source counts only when it is clearly this business: the
same name and the same town, or the same phone number. A same-named business
in another state is not a source. When unsure, leave it out and put the
question in `unknown`.

## The file (schema 1)

A skeleton is already in `facts.json`. Code owns and rewrites `place_id`,
`slug`, `name`, `category`, `segment`, `city`, `researched`,
`hours.as_listed` and `faults`: leave them. You write the rest.

```json
{
  "facts": [
    {"id": "f1", "kind": "service", "text": "Repairs and replaces garage door springs.",
     "confidence": "high",
     "source": {"kind": "own_site", "url": "https://example-garage.com/services",
                "words": "Spring repair and replacement"}}
  ],
  "services": [{"name": "Garage door spring repair", "facts": ["f1"]}],
  "area": {"text": "Serves American Fork, Lehi and Highland.", "facts": ["f4"]},
  "hours": {"as_listed": ["…from the listing, code fills it…"],
            "say": {"text": "Call or text any day.", "facts": ["f2"]}},
  "about": [{"text": "A family business working in Utah County since 2012.", "facts": ["f5", "f6"]}],
  "unknown": ["Whether they do commercial work"],
  "owner_asks": ["Photos of recent jobs", "Confirm the list of services"],
  "verdict": "build",
  "skip_reason": null
}
```

- `facts[]`: `id` (`f1`, `f2`, …), `kind` one of `service specialty area hours
  since credential contact about other`, `text` (one plain sentence in **your
  own words**, true of this business), `confidence` `high` or `medium`, and
  `source` `{kind, url, words}` with kind one of `listing review search
  own_site directory record`. `words` are the exact words on that source
  that say it (copied, so a person can find them); they are never published.
- A second source for the same fact goes in `also`: a list of sources of the
  same shape.
- A `review` source also carries `ref`, the review's number in `packet.json`,
  and its `words` are a short phrase from that review (under 25 words).
- `services[]`, `area`, `hours.say`, `about[]` are what the site will say.
  Each names the fact ids behind it. The site uses `high` facts only.
- `unknown[]`: what we couldn't find out that the site would want.
- `owner_asks[]`: what the owner would send to finish the site (their photos,
  a confirmed service list, their logo).
- `verdict`: `build`, or `skip` with a `skip_reason` in one line.

## Confidence

- `high`: a listing field, their own site, a public record, **or** the same
  thing from two independent sources (two different reviews count; one
  review plus a directory counts). Put the second source under `also`.
- `medium`: one mention anywhere else (one review, one search snippet, one
  directory profile).
- Not a fact at all: what you infer from the category, what a business of
  this kind usually does, anything you'd need to guess.

## The never list (the lint fails the file)

In any `text`, `services[].name`, `area`, `hours.say` or `about`:

1. **A review's words.** Six words in a row shared with any review fails.
   Say what the reviews show in your own plain words ("Customers mention
   same-day visits"), never what they wrote.
2. **A person's name.** Not the owner, not a worker, not a reviewer, not
   "Mike and his team". The business's own name is fine even when it holds a
   name ("Trish Griffee Photography").
3. **A price.** No dollar amounts, rates or "per hour", even when a source
   lists them.
4. **A street address.** No house numbers, no Utah grid addresses
   ("600 N 100 E"), no suites. A town, a county or a list of towns served is
   fine.

Also: the listing's hours are "Open 24 hours" for many trades that simply
answer the phone. Don't repeat that as a claim; `hours.say` phrases it for a
person ("Call or text any day") with the hours fact behind it.

## When to skip

- It isn't the kind of business the census says, or it's closed, or it's a
  franchise or a chain.
- You can't tell which search results are really them.
- It already has a real website of its own that works (then the preview has
  nothing to show them): `skip_reason` names the URL.
- Thin: fewer than three `high` facts, or no service you can source. Say so.

## Three worked examples

**1. A listing field (high).** `listing.json` has `"nationalPhoneNumber":
"(801) 555-0101"`.

```json
{"id": "f1", "kind": "contact", "text": "Call or text (801) 555-0101.", "confidence": "high",
 "source": {"kind": "listing", "url": "<listing.json googleMapsUri>", "words": "(801) 555-0101"}}
```

**2. Two reviews say the same thing (high).** Review 0 says "…he came out the
same day and fixed our spring…" and review 3 says "…same day service, spring
replaced in an hour…".

```json
{"id": "f2", "kind": "specialty", "text": "Garage door spring repairs, often the same day.",
 "confidence": "high",
 "source": {"kind": "review", "ref": 0, "url": "<googleMapsUri>", "words": "came out the same day and fixed our spring"},
 "also": [{"kind": "review", "ref": 3, "url": "<googleMapsUri>", "words": "same day service, spring replaced"}]}
```

The `text` shares no run of six words with either review, and names nobody.

**3. One search snippet (medium).** A search result titled "Blue Canyon
Landscaping - Lehi, UT - Nextdoor" with the snippet "Sprinkler repair and
spring cleanups in Lehi and Saratoga Springs".

```json
{"id": "f3", "kind": "service", "text": "Sprinkler repair.", "confidence": "medium",
 "source": {"kind": "search", "url": "https://nextdoor.com/pages/blue-canyon-landscaping-lehi-ut/",
            "words": "Sprinkler repair and spring cleanups in Lehi and Saratoga Springs"}}
```

If a second, different source says it too (their BBB profile, a review that
mentions the sprinklers), add it under `also`: two independent sources, now
`high`. Fetching the same Nextdoor page is not a second source: it is the
same one, read twice.

## Finish

Run `prep facts lint facts.json`. It lists every error; fix them and run it
again until it prints OK (warnings are fine). Then stop. That command is the
only one you can run here.
