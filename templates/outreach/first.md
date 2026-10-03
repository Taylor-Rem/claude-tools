# first — the day-0 note (ROADMAP B46, GROWTH § 5.3). Taylor approves this exact
# text once; `outreach send` refuses if the hash in APPROVED doesn't match.
#
# Lines starting with # are comments and are never sent. `Subject <key>:` lines are
# the subject table: the key is matched against the pick's own fault and the first
# hit wins, `default` last. Below the `---` is the letter. A line whose {placeholder}
# has no value is dropped whole, so a missing phone number leaves no empty line.
# Placeholders: {first} {business} {fault} {paying} {preview_url} {price_line} {phone}
# {booking} {address}.
# {paying} (B71) is one sentence about the platform their site's address is set up
# with, in that vendor's own published or reported price (client-leads/vendor_prices.md,
# via `leads`): "Your site's address is set up with Hibu, whose plans are reported to
# start at <Hibu's number> a month." It is about the vendor, never a guess at their bill, and it is
# empty — the sentence gone whole — when the vendor is unknown, free or unpriced.
#
# The rules this text has to keep (they are checked by `outreach doctor`):
#   four to six sentences in the letter, and exactly one link in it — the preview.
#   The booking link, the phone and the address sit in the signature, which is not
#   the pitch; that is what "one link" means for deliverability.
#   An ad identification, an opt-out, and the AI disclosure, all in plain words.
#   No price of ours that isn't on patchlamp.com/pricing; no one else's but {paying}.

Subject dead: your Google listing points at a page that doesn't load
Subject website: {business} has no website on its Google listing
Subject marketplace: your Google listing sends people to DoorDash
Subject hours: your Google listing has no hours on it
Subject booking: there's no way to book {business} online
Subject photos: your Google listing has almost no photos
Subject closed: Google says {business} is closed when it isn't
Subject default: one thing to fix on {business}'s Google listing

---
Hi {first},

I'm Taylor Remund — I build and look after small websites out of American Fork, and I go through local businesses one at a time. I looked {business} up on Google: {fault}. {paying} I've made you a page that fixes it, so you can look at it instead of imagining it: {preview_url}. If you want it kept it's {price_line} to keep it up on your own web address, with a few small changes by text each month; if you don't, I take it down and that's the end of it. Either way the page is yours to copy from.

Taylor Remund
{phone}
Fifteen minutes on the phone, if that's easier: {booking}
{address}

This is a one-time note from a local business — it is an advertisement, and nobody paid me to send it. Reply "no thanks" and you won't hear from me again.
Patch, my AI operator, found this and drafted this note; I read every one before it goes.
