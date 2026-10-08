# The consent machine — runbook

ROADMAP B139 · plan `~/projects/plans/55-autonomous-acquisition.md` § 5.9 ·
VISION § Decided "Autonomous acquisition" #6 · the law:
`~/projects/research/2026-10-07-autonomous-acquisition/law-and-platforms.md`
§ 2 (TCPA, Utah 13-25a) and § 3 (CTIA, Twilio).

Code: `lib/consent.py` (the machine), `bin/consent` (the door for people and
tools), `sms-relay/relay/consent.py` (the relay's inbound hook and outbound
gate). Tests: `tests/test_consent.py` here, `tests/test_consent.py` in the
relay.

## Why it is a machine

A text to a mobile number is the most expensive mistake the business can make
($500–$1,500 a text under the TCPA, Utah's private action, carrier fines). The
one clean way to text a prospect is a mailed card that asks them to text a
keyword first (brief § 3: "the cleanest path"). What that keyword buys is
narrow — Twilio's own reading is that an inbound text consents to **one direct
reply**, not to ongoing engagement — so the machine, not a model, decides every
send. A model is only ever told "You may send this reply." or "You may not text
this number." (VISION § Rules 8: the reason in a plain voice; never the state
to reason about.)

## States, per number and program

| state | entered by | what may be sent |
|---|---|---|
| INVITED | `consent invite` / `Machine.invite()`: a card mailed (card id, version, the CTA's exact text and its sha256, keyword, the number on the card, the recipient, what the card promises) | nothing |
| KEYWORD_RECEIVED | the keyword (first word of the text, any case) to the card's number | **one direct reply**: the compliance message plus the card's promise, composed in code |
| DISCLOSED | that reply sent (it carried "Msg & data rates may apply" and STOP) | a reply to a text of theirs; nothing unprompted |
| CONFIRMED | an affirmative reply (YES, Y, yeah, sure, ok, "yes please"…), logged verbatim; or `opt_in()` for START / a form | the program's scope: up to N texts on its subject within its time box, 8am–9pm in the program's timezone, never Sundays or its holidays |
| ACTIVE | the first scoped text sent | the rest of the allowance, each text checked before it leaves |
| EXPIRED | the allowance spent or the time box passed | a reply to a text of theirs; nothing unprompted |
| REVOKED | STOP, or any reasonable means ("stop texting me", "remove me", "wrong number", "not interested"…), on any program | nothing, on any program, until the number texts START |

HELP (or INFO) gets the help text and changes nothing. START from a revoked
number lifts the revocation and re-enters nothing by itself; a fresh keyword or
an `opt_in` does that. A web form's consent and START enter through
`opt_in(number, venture, program, source=form|start, evidence=…)` with their own
program's scope.

**Replies vs scoped texts.** Each text of theirs earns one reply, within 24
hours, in any state but REVOKED, at any hour (it answers them; Utah's quiet
hours are for solicitations). Everything else is a scoped text and needs
CONFIRMED/ACTIVE, allowance, the time box and the hours. The gate decides which
one a send is from the record: a reply when a text of theirs is waiting, scoped
otherwise.

**Revocation reach.** One STOP revokes every program the number is in, across
every venture in the store (FCC 26-67 ends all of one seller's telemarketing;
we go further, because a second business sharing the store is still us), at
once — well inside the ten business days.

## What each transition logs

`consents` (SQLite, `$CONSENT_DB`, default
`~/.local/state/claude-tools/consent.db`) is append-only: one row per event,
nothing updated or deleted. Every row has `at`, `number`, `venture`,
`program`, `from_state`, `to_state`, `event`, and `permits` (what it lets us do
afterwards, in words). By event:

- `card_mailed` (INVITED): `card_id`, `card_version`, `cta_text`, `cta_hash`,
  `keyword`, `our_number`, `recipient`, `promise`.
- `keyword` (INVITED → KEYWORD_RECEIVED): the card's fields copied, plus
  `inbound_at`, `inbound_text` (verbatim), `message_id` (Twilio's SID).
- `reply_sent` (→ DISCLOSED for the compliance message): `outbound_text`, SID.
- `confirmed`: the YES verbatim in `inbound_text`. `opted_in`: the agreed words
  in `inbound_text`, `source` form|start.
- `scoped_sent` (→ ACTIVE), `expired` (`reason`: allowance spent / time box
  passed), `revoked` (per program, plus a `*/*` number-wide row), `restarted`,
  `help`, `inbound`.
- `refused`: a text that did not go, its words in `outbound_text` and why in
  `reason`. The relay also logs the refusal in its own log.

`consent show NUMBER` prints a number's whole log; that is the evidence file
for a dispute.

## Programs are data (portable)

`consent program add VENTURE PROGRAM --name --business --subject --max --days
--terms [--contact] [--kind keyword|start|form] [--tz] [--holidays utah,…]`.
The engine names no business: the program's name, the business the messages
carry, the subject, the allowance, the time box, the terms link, the HELP
contact, the timezone (default `$CONSENT_TZ`, else America/Denver) and the
holiday list (a calendar name — `utah` computes Utah Code 63G-1-301's legal
holidays, with weekend dates blocked on both the day and its observed weekday —
and/or ISO dates for a day the Governor appoints) are registered per venture.
A second venture registers its own programs; `tests/test_portable.py` keeps
`lib/consent.py` free of Patchlamp's literals.

**A card can't start the machine without the carriers' lines** (VISION #6):
`invite` refuses a CTA that lacks the program's name, the keyword, a frequency
("up to 3 msgs"), "Msg & data rates may apply", STOP and HELP, or the terms
link. B54 (`leads mail`, the postcard) calls `invite` with the card id, the
version and the CTA's exact text; the hash is computed here.

## The messages (composed in code)

- Compliance (the one reply to the keyword): `{business}: {program name}.
  {promise} Reply YES for up to {N} more texts about {subject} in the next
  {days} days. Msg & data rates may apply. Reply STOP to end, HELP for help.
  Terms: {terms}`
- After YES: `Thanks. {business}: up to {N} texts about {subject} over the next
  {days} days. Msg & data rates may apply. Reply STOP to end, HELP for help.`
- HELP: `{business}: {program name}. Questions: {contact}. Up to {N} msgs about
  {subject}. Msg & data rates may apply. Reply STOP to end. Terms: {terms}`
- STOP: nothing from us. Twilio's built-in opt-out handling answers STOP on our
  long code with its standard confirmation and blocks further sends (error
  21610); a second confirmation from us would be one text too many. Twilio also
  answers HELP by default; if that doubles up, set the number's Advanced Opt-Out
  HELP text to ours and the relay's stays the same words.

## The relay

- Inbound (`core.handle`, a sender not in config.json, SMS only, before the
  START flow and the demo): a number the machine knows, or a text whose first
  word is a card's keyword, goes to the machine. Keyword, YES, HELP and STOP are
  answered (or silenced) in code with no run; any other text carries on down the
  stranger path exactly as before, with "You may send this reply." added to the
  run's setting line. A revoked number's texts get nothing back.
- Outbound (`SmsTransport.send`, every SMS the relay sends): a number the
  machine knows gets `may_send`; a no is logged and the text isn't sent
  (`send` returns False). Numbers it doesn't know — Taylor, clients, demo
  texters — are not governed, and with no store on disk nothing is consulted.
- The toolbelt is imported by path (`$CONSENT_LIB`, else beside `consent` on
  PATH, else `~/projects/claude-tools/lib/consent.py`). If the machine errors on
  a number it knows, that text is refused; on any other number the relay
  carries on.

## The 10DLC campaign (what Taylor pastes; TAYLOR-TODO § 1b)

The keyword program, the confirmation flow and the opt-in evidence, for the
campaign form in the Twilio console (Messaging → Regulatory Compliance →
Campaigns). The bracketed values are the ones B54 fixes when the card is
designed; the defaults below are this row's proposal.

**Campaign description.** Patchlamp builds and runs websites for small
businesses by text. Business owners who receive our printed postcard can text
the keyword [PATCH] to this number to see the website we prepared for their
business. We reply once with the link and our program disclosures, and ask
them to reply YES if they want up to [3] follow-up texts about their site over
the next [30] days. We send nothing else unless they reply YES; replies to
their own questions are one-to-one conversation with the owner. We never text
a number that has not texted us first.

**Message flow / call to action (opt-in).** Opt-in is by keyword, from a
printed postcard mailed to the business's address. The card reads: "Text
[PATCH] to [number] to see your site. Patchlamp Site Texts: up to [3] msgs.
Msg & data rates may apply. Reply STOP to end, HELP for help. Terms:
https://patchlamp.com/sms". The keyword text, its timestamp, the sending
number, the card's id and version and the exact wording of the card's call to
action are logged for every opt-in. Recurring messages require a second,
explicit opt-in: the owner replies YES to our first reply, and that reply is
logged verbatim.

**Sample messages.**
1. "Patchlamp: Patchlamp Site Texts. Here's the site we built for [business]:
   [link] Reply YES for up to 3 more texts about your site in the next 30 days.
   Msg & data rates may apply. Reply STOP to end, HELP for help. Terms:
   https://patchlamp.com/sms"
2. "Thanks. Patchlamp: up to 3 texts about your site over the next 30 days.
   Msg & data rates may apply. Reply STOP to end, HELP for help."

**Opt-out (STOP).** STOP, STOPALL, UNSUBSCRIBE, CANCEL, END, QUIT, REVOKE, OPT
OUT and plain-language requests ("stop texting me", "remove me") end every
program at once; the number receives nothing further until it texts START.

**Help (HELP).** "Patchlamp: Patchlamp Site Texts. Questions: [contact]. Up
to 3 msgs about your site. Msg & data rates may apply. Reply STOP to end.
Terms: https://patchlamp.com/sms"

**Frequency.** Up to [3] messages per opt-in over [30] days, plus one reply to
each message the owner sends. Sent 8am–9pm Mountain time, never on Sundays or
Utah legal holidays.

**Use case.** Low-Volume Mixed (customer care + marketing), or Marketing.
Opt-in URLs: patchlamp.com/sms (the program terms), /privacy, /terms. The
`/sms` page must describe this keyword program (the program name, the keyword,
the frequency, the rates line, STOP/HELP) before the campaign is submitted;
that page is the app's (a ROADMAP row, not this one).
