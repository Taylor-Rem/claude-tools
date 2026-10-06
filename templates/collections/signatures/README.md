# signatures — documents a customer signs by link

**Status: ready** (ROADMAP B128). The texts it answers: "send the Smiths
the waiver", "has Smith signed?", "what's waiting to be signed?", "cancel
the Smith waiver". `bin/sign` is the whole interface; PLAYBOOK.md § Files
says how Patch uses it.

What `db add signatures` puts in the repo:

| file | what it is |
|---|---|
| `migrations/NNNN_signatures.sql` | one table: the text as sent (the only copy; no HTML is stored) and its sha256, who it's for, and once signed the typed name, the time (UTC), the IP, the browser and the sha256 at that moment |
| `functions/_lib/markdown.js` | the text as HTML, rendered on every view: the same function as `to_html` in `bin/sign`, so the page and the PDF show the same thing |
| `functions/sign/[token].js` | `/sign/<token>`: the document, a full-name box, the "I have read this and I agree to it" tick and the Sign button; phone first. GET never changes anything (link previews open it); a row whose text no longer hashes to what was sent (or signed) is shown as changed, never as the document; POST checks the same site, the name, the tick, and that the text still hashes to what was sent, then records the signature once and tells the owner through patchlamp.com's form mail (`/f/<slug>/signature`) |
| `functions/_admin/signatures.js` | `/admin/signatures`: what was sent, to whom, signed by whom and when |

After `db add signatures`: commit, push, `site publish <name>`. Then
`sign new waivers/<file>.md --for NAME` sends the first one.

**The link** is 32 random bytes (`secrets.token_urlsafe`), one per
customer per document; `sign void` withdraws it. A wrong, withdrawn or
signed link shows a plain page that says so.

**The record** is plain assent: not a notarised or witnessed signature
and not an identity check. The page says so in one line; PLAYBOOK says
when that isn't enough.

**The PDF and the copies** are made in the workspace, not on the site:
`sign pdf` renders `templates/print/signed.html` through
print's renderer from the stored text (refusing a row whose text no longer
hashes to the signature), checks it (letter pages; the name, the time and the hash
read back from the PDF's text), saves it under `signed/`, and files it
under the customer as a job "Signed: <title>" (done, that day) when the
site keeps the customer book. Emailing the PDF to the owner and the signer
needs a customer-mail path that carries a file; B118's
`POST /internal/relay/projects/{slug}/customer-mail` (relay `customers.py
send()`, on main since 2026-10-06) is the seam: text only, called by the relay
alone, so the signer's copy by email is a relay change (a `waiver` kind and a
queue it drains, as `relay/reviews.py` does). Until then `sign pdf` prints
both emails as the owner's drafts, Patch sends the owner the PDF
(SEND-FILE), and the signer's copy is the signed page itself, which they can
print or save, or the PDF the owner forwards.

**The hash** is sha256 of the text as it was sent (UTF-8, `\n` line ends,
no trailing spaces, one final newline): `sign` writes it when sending and
checks the stored copy right after, the page recomputes it on every view
and when signing and refuses if they differ, and the PDF is made only when
the stored text still gives it, and prints it. Whoever holds the record
(the owner, on `/admin` or in `db export`) can check a copy against it.

## What it isn't

A drawn signature, an e-signature service with identity checks, a
template library (the owner's own text, word for word), or a way to send
the link (the owner sends it until Patch has a number of its own, B13).
