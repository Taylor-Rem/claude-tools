# signatures — documents a customer signs by link

**Status: ready** (ROADMAP B128). The texts it answers: "send the Smiths
the waiver", "has Smith signed?", "what's waiting to be signed?", "cancel
the Smith waiver". `bin/sign` is the whole interface; PLAYBOOK.md § Files
says how Patch uses it.

What `db add signatures` puts in the repo:

| file | what it is |
|---|---|
| `migrations/NNNN_signatures.sql` | one table: the text as sent and its sha256, who it's for, and once signed the typed name, the time (UTC), the IP, the browser and the sha256 at that moment |
| `functions/sign/[token].js` | `/sign/<token>`: the document, a full-name box, the "I have read this and I agree to it" tick and the Sign button; phone first. GET never changes anything (link previews open it); POST checks the same site, the name, the tick, and that the text still hashes to what was sent, then records the signature once and tells the owner through patchlamp.com's form mail (`/f/<slug>/signature`) |
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
`sign show` (or `sign pdf`) renders `templates/print/signed.html` through
print's renderer, checks it (letter pages; the name, the time and the hash
read back from the PDF's text), saves it under `signed/`, and files it
under the customer as a job "Signed: <title>" (done, that day) when the
site keeps the customer book. Emailing the PDF to the owner and the signer
needs the customer-mail path on patchlamp.com (B119); until then `sign
show` prints both emails as drafts and Patch sends the owner the PDF.

**The hash** is sha256 of the stored text (UTF-8, `\n` line ends, no
trailing spaces, one final newline): `sign` writes it when sending, the
page recomputes it when signing and refuses if the two differ, and the PDF
prints it, so anyone can check a copy against the row.

## What it isn't

A drawn signature, an e-signature service with identity checks, a
template library (the owner's own text, word for word), or a way to send
the link (the owner sends it until Patch has a number of its own, B13).
