# batch-second — the day-3 touch of the batch lane (ROADMAP B90, plan 37 § 3). Same
# mailbox, same thread ("Re:" the first subject, In-Reply-To set by the sender).
# One link at most, and only on the sending domain: {see_url} is OUTREACH_LINK_BASE plus
# this business's token, and when the base isn't set the letter asks for a reply instead
# (the `[?see_url]` / `[!see_url]` lines; only one of the two is ever sent).
# The page behind {see_url} builds the preview when it is pressed (B91), so this letter
# never says one exists.
# The AI sentence (B132, plan 53): `[?ai_intro]` beside the introduction and `[?ai_foot]` as the
# body's last line; the sequence's variant turns on one of them, or neither for `none` (only inside
# the AI-line test, where the first machine answer says it instead). No other words change.
# Placeholders: {first} {business} {see_url} {price_line} {phone} {address} {thread_subject}.

# Body by Codex (marketing/copy/2026-10-05-letters.md, variant A), 2026-10-05: one thought a sentence, one ask a letter;
# the disclosure beside the intro. Flint's one change: batch-first's takedown sentence is out (nothing is built yet in this lane).

Subject default: Re: {thread_subject}

---
Hi {first},

I'm Taylor. I build and look after websites in American Fork.
[?ai_intro] Patch, my AI operator, drafted this note for my approval of the batch.

I can make a free website preview for {business} from your Google listing.
[?see_url] You can have one built here: {see_url}
[?see_url] Want to take a look?
[!see_url] Want me to make one and send it over? Just reply.
[?ai_foot] Patch, my AI operator, drafted this note for my approval of the batch.

Taylor Remund · Patchlamp
{phone}
{address}

This is an advertisement from a local business. Reply "no thanks" and you won't hear from me again.
