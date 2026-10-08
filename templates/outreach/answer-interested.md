# answer-interested — arm B of the close experiment (ROADMAP B137, plan 55 § 5.4 and § 5.6, experiment E3:
# "Taylor's call vs Patch's link", read on paid per 100 interested). When OUTREACH_LINK_BASE is set, this file
# is approved, LEADS_BOOKING_URL and the postal address are set, an *interested*, *call me* or named-time reply
# to a batch letter is dealt arm A (Taylor's brief, as before) or arm B by a stable hash of the business's
# place id. Arm B gets this one reply, from the thread's mailbox, signed by Patch and never by Taylor; then
# the machine stops, and the lead's next message goes to Taylor with the brief whichever arm it was.
# Placeholders: {first} {business} {thread_subject}; {preview_url} the see-link on the sending domain
# (OUTREACH_LINK_BASE + the business's token, as answer-yes); {start_url} the preview's claim link
# (`leads preview --place --json`'s claim_url: the venture's claim_start filled with the business, the same
# link the preview's "Claim it" opens), else the venture's claim_start; {windows} the three call windows
# (OUTREACH_CALL_WINDOWS, else the venture's sender.call_windows); {booking_url} LEADS_BOOKING_URL;
# {price_line} {phone} {address}. The trial isn't live (CLAIMS: 0 trial days), so it never says "free week".
# Body by the B133 passes (marketing/copy/2026-10-08-answer-interested.picked.json: Codex and an Opus
# writer, a code check, a blind judge; Opus picked, Flint's one edit "included on that plan"). Installed
# verbatim; it needs Taylor's `outreach approve --template answer-interested`, like any edit here.

Subject default: Re: {thread_subject}

---
Hi {first},

I'm Patch, Taylor's AI operator, answering for him. Taylor is the person on the hook for your site; I'm who you text to change it.

Here's the preview for {business}: {preview_url}

It's built from your Google listing alone, so it only knows what Google knows, and it stays up for 30 days.

Taylor can call if you'd like to talk first: {windows}. Book one here: {booking_url}

No call needed to keep it: claim it at {start_url}. On your own web address it's {price_line}. A few small changes by text each month are included on that plan; bigger ones need a bigger plan.

Patch, Taylor's AI operator · Patchlamp
{phone}
{address}

You wrote back to Taylor's note, so this is a reply, and it's still an advertisement for his service. Reply "no thanks" and you won't hear from us again.
