# answer-yes — the machine's reply to a plain "yes" to the batch letter's offer (ROADMAP
# B90, plan 37 § 4: "a reply of 'yes' to the first letter builds the instant preview at
# once and answers with its address"). Sent only when `leads preview --place ID --json`
# returned a URL, so the sentence saying it was built is true; without one the reply goes
# to Taylor instead. {preview_url} is the see-link on the sending domain
# (OUTREACH_LINK_BASE + the business's token), never previews.patchlamp.com: with no link
# base the reply goes to Taylor with the preview's address. Hashed in APPROVED.
# Placeholders: {first} {business} {preview_url} {price_line} {phone} {address}.

Subject default: Re: a preview for {business}

---
Hi {first},

Here it is: {preview_url}

I built it from your Google listing alone, so it only knows what Google knows, and it stays up for 30 days. If you'd like to keep it, it's {price_line}, and changes after that are a text to Patch. Any questions, just reply.

Taylor Remund
{phone}
{address}

You wrote back to my note, so this is a reply, and it's still an advertisement for my own service. Reply "no thanks" and you won't hear from me again.
Patch, my AI operator, sent this reply in words I approved; I'm told of every one.
