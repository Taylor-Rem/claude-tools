# batch-second — the day-3 touch of the batch lane (ROADMAP B90, plan 37 § 3). Same
# mailbox, same thread ("Re:" the first subject, In-Reply-To set by the sender).
# One link at most, and only on the sending domain: {see_url} is OUTREACH_LINK_BASE plus
# this business's token, and when the base isn't set the letter asks for a reply instead
# (the `[?see_url]` / `[!see_url]` lines; only one of the two is ever sent).
# The page behind {see_url} builds the preview when it is pressed (B91), so this letter
# never says one exists.
# Placeholders: {first} {business} {see_url} {price_line} {phone} {address} {thread_subject}.

Subject default: Re: {thread_subject}

---
Hi {first},

Following up on my note from a few days ago about {business}.
[?see_url] If you'd like to see a site for {business} built from your Google listing, this page makes a free preview of one in a couple of minutes: {see_url}
[!see_url] If you'd like to see a free preview of a site for {business}, built from your Google listing, just reply and I'll send it.
If you'd want it kept, it's {price_line} to keep it up on your own web address, with a few small changes by text each month; if not, no hard feelings.

Taylor Remund
{phone}
{address}

This is an advertisement from a local business. Reply "no thanks" and you won't hear from me again.
Patch, my AI operator, found this and drafted it; I approve each batch.
