# submissions — what people send from a form, in a list the owner can see

**Status: ready.** The texts it answers: "keep quote requests in a list I can
see", "I want to see everyone who's contacted us", "let me log in and see
the bookings people asked for".

What `db add submissions` puts in the repo:

| file | what it is |
|---|---|
| `migrations/NNNN_submissions.sql` | the `submissions` table (form, name, email, phone, message, every field as JSON, status, notes) |
| `functions/api/submissions.js` | `POST /api/submissions`: stores the row, forwards a copy to patchlamp.com so the owner is still emailed |
| `functions/_admin/submissions.js` | how `/admin/submissions` shows it: title, columns, the statuses (new, replied, done), notes |
| `form.html` | not copied — the form to paste into a page (`db add` prints it) |

After `db add submissions`:

1. Put the form on the page (the one `db add` printed, or change an existing
   form's `action` from `https://patchlamp.com/f/<slug>/<form>` to
   `/api/submissions` and add `<input type="hidden" name="_form" value="<form>">`).
   Keep the field names and the `website` honeypot. The thanks line reads
   `?sent=<form>` like before; `?sent=0` means it was refused (too many from
   one address, or empty).
2. Rename the list to the owner's word: `title` in
   `functions/_admin/submissions.js` ("Quote requests").
3. Commit, push, `site publish <name>`.
4. Prove it: post the live form once (`curl -s -X POST <url>api/submissions
   -H 'accept: application/json' -d _form=quote -d name=Test -d
   message=test`), then `db query "SELECT id, form, name, created_at FROM
   submissions ORDER BY id DESC LIMIT 3"`. Tell the owner to open
   `<url>admin`, type their email, and use the link.

Rules the Function keeps: at most 20 fields of 2,000 characters, plain field
names, five posts per visitor per ten minutes, the honeypot. The email copy
goes through patchlamp.com (`FORWARD_EMAIL = "off"` in `wrangler.toml`'s
`[vars]` stops it, e.g. for a very busy form the owner only reads on /admin).
