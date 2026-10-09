# The Factory: the runbook (`bin/infra`, ROADMAP B144, plan 55 § 5.7)

The production line that makes sending capacity: a domain, its DNS, its mailboxes, their credentials,
warm-up, the registry rows, certification, and only then the lane. This page says which steps are the
machine's (an API call, then a read of the world to check it) and which are a person's, and why each
human one is human. Read it before a live run, and correct it the day something here turns out wrong.

## The path, step by step

| # | step | who | how | why it's that one |
|---|---|---|---|---|
| 0 | the provider account, the card, the API key | **Taylor** | TODO § 1 "The production line's provider" | an identity and a payment: only he signs and pays |
| 0b | the contract verdict for the provider | **Taylor** reads, Flint records | `infra contract infraforge --verdict PERMITTED --clause "…" --read DATE --word "Taylor, DATE"` | a judgment about a contract; a guessed verdict is how a whole account gets suspended (VISION § Decided 2026-10-07 #2). `provision` refuses until it exists and files the step itself |
| 1 | `infra plan` | machine | the pool against the active and warming lanes' thirty-day capacity, half per contract | demand decides when; it changes nothing |
| 2 | Taylor's `go` on a purchase | **Taylor** | his word; Flint runs `infra provision … --go` | money, until sixty clean days; then `INFRA_AUTO_PURCHASE=1` lets the schedule do it |
| 3 | buy the domain | API | `buy_domain` (keyed, ledgered first) | — |
| 3b | registrant verification email (if the registrar sends one) | **Taylor** | filed by the tool when the provider says so | an identity: the registrant is him. Registries suspend an unverified domain after fifteen days |
| 4 | SPF, DKIM, DMARC, MX | API (the vendor sets them) | `set_auth_dns`; we read them back from public DNS | — |
| 5 | mailboxes | API | `create_mailbox` with a password made here, written to the toolbelt env by asset id *before* the call | — |
| 6 | warm-up on | API with the two Salesforge ids, else **Taylor's click** | `start_warmup`: Infraforge's export to Salesforge with `warmupActivated` when `INFRA_SALESFORGE_WORKSPACE` and `INFRA_WARMFORGE_WORKSPACE` are set; else a filed click in Warmforge. `infra warmup --go` runs the export later for mailboxes still waiting on the click and ticks it (B150) | the ids come with a Salesforge subscription (TODO § 1 "Warm-up: Warmforge") |
| 7 | VERIFY | machine | DNS answers from 1.1.1.1 (`dig`), an SMTP and IMAP login per mailbox | the API's "ok" is never the proof |
| 8 | COMMIT | machine | registry rows `warming`, the commit ledger line, a HISTORY line printed for Flint | — |
| 9 | add the domain to Google Postmaster Tools | **Taylor** (one click and a paste) | filed by the tool at commit; the TXT value goes through `infra dns-txt D VALUE` | Postmaster has no API for adding a domain, and the account is his identity |
| 9a | the TXT write keeps the rest | machine | `infra dns-txt` reads the live set, adds the record and PUTs the lot; `infra dns-restore D` puts back the set read at purchase when one is lost | the vendor's `PUT /domains/{id}/dns` replaces the whole set: on 2026-10-08 the first TXT write left one record where MX, SPF, DKIM and DMARC had been, and the warm-up bounced for a day (Cowork, 2026-10-09) |
| 10 | seed inboxes (once, not per domain) | **Taylor** | filed by `certify` or `seeds` when `INFRA_SEED_INBOXES` is empty | new Google and Microsoft accounts need a person (phone verification) |
| 11 | seed sends, seven days | machine | `infra seeds send --all`, then `infra seeds read --all`, once a weekday | a schedule line Flint adds after the first commit (not built in this row) |
| 12 | CERTIFY | machine | `infra certify D`, or the daily `infra tick` for every domain past its date: every check below, then `active` | — |
| 13 | the lane | machine | nothing: `outreach` reads the registry (B150), so an `active` mailbox under a PERMITTED contract takes first letters from the next send window, under `OUTREACH_MAILBOX_PER_DAY` (its ramp counted from the mailbox's own day in `warming`) or its own registry cap | no env edit; `infra drain D` takes it out the same way |

## What `certify` checks (all of them, or the domain stays `warming`)

- **DNS and logins**: SPF, DKIM (at the vendor's selector) and DMARC published; every mailbox logs in.
- **The seeds are ours**: at least one seed inbox, none on a sending domain. The vendor never hears of them.
- **Placement in the seed inboxes**: each mailbox's latest probe is in each seed's INBOX (spam or missing fails).
- **SPF, DKIM, DMARC pass at the receivers**: the seeds' own Authentication-Results headers say pass.
- **Seven days of our own seed sends** (the ramp's first step; seeds only, never a prospect).
- **Warming**: fourteen days, or seven when the vendor sold it pre-warmed (its word, plus ours).
- **Postmaster verified and reading**: the morning fetch (`outreach postmaster fetch`, which now includes the
  registry's Factory domains) got an answer for the domain in the last three days, `ok` or `no data`. At low
  volume "no data" is normal and still proves the domain is verified for our account.
- **The vendor's placement probe**, when the vendor has one: at or above the registry's floor (50% in the inbox);
  recorded as a `probe` reading. The lowest-trust signal; never the only one.
- **No human step open** for the domain in TAYLOR-TODO (each is filed with `infra_step=<key>`; a ticked entry is closed).

## The tick (B150): demand on a timer

`infra tick` is `systemd/infra-tick.timer` (06:40 daily; Flint enables it, it isn't enabled by install). Every day it
certifies each `committed` domain whose warming days are up (the same checks as `infra certify`; a failure is a line
in its report and the proposal, never an exit code). On weekdays it runs the plan with the pool from `INFRA_POOL_CMD`
(default `leads batch --stats --json`, whose `qualify` is the businesses a first letter may go to; `INFRA_POOL_KEY`
picks another field) and writes `STATE/proposal.json`, whose `line` the morning message (`leads today`) prints for
three days. When the plan wants units it names candidate domains (the venture's name with a verb before or a word
after, checked with the vendor's availability call) and the exact `infra provision … --go` line for Taylor.

It buys on its own only when **both** hold: sixty clean days and `INFRA_AUTO_PURCHASE=1`. Clean days are counted
from the registry's own events, so no flag stands in for them: the first Factory COMMIT's `warming` starts the
count; an incident on a Factory row, a drain on reputation or a rollback restarts it (a VERIFY that failed before
its COMMIT doesn't: DNS propagating is the usual cause, and the re-run is the compensation). Then it runs the
provision lines itself under `INFRA_USD_PER_DAY` and `INFRA_UNITS_PER_WEEK`, and stops at the first cap, the halt
or an unknown purchase. Until then a purchase is Taylor's money and waits on his word.

## The control plane

Every operation is PLAN → APPLY → VERIFY → COMMIT, journalled in `~/.local/state/claude-tools/infra/ops/<id>.json`.

- **Keys before calls.** Each external call has a key `<operation>:<step>`; its `intent` line goes into the
  toolbelt ledger (`~/.local/state/claude-tools/ledger.jsonl`, `kind: infra`, with venture, tenant, inputs and the
  planned cost) before the call is made. The operation's `commit` line carries the result and the cost (`books`
  reads `cost_usd` and the `vendor` name). No password ever goes into the ledger or the journal.
- **Resume.** Re-running the same `infra provision` line after a crash skips what finished. A step whose key is
  in the ledger but whose result never came back is asked of the provider (does it hold the domain, the
  mailbox?); found means done, with no second call. A purchase with no trace is **never** re-sent on its own:
  the run stops and says to look in the dashboard, and `--retry-purchase` re-sends it under the same key.
- **Compensation.** A failed verify leaves the rows `provisioning` with an incident; re-running verifies again (DNS
  can take an hour). `infra rollback provision-D` deletes the mailboxes, removes the records, turns auto-renew off,
  drops the credentials and retires the rows. The domain is kept until it lapses and is never bought twice.
- **Limits.** `INFRA_USD_PER_DAY` (default $50 committed a day) and `INFRA_UNITS_PER_WEEK` (default two domains
  started in seven days). A purchase waits on `--go` (Taylor's word) until sixty clean days.
- **The global stop.** `infra halt "why"` (or `FACTORY_HALT=1`) refuses every new external mutation: a purchase,
  a DNS write, a mailbox create or delete, a warm-up enrolment, a seed send, a rollback's deletions. Status, plan,
  certify's checks, `seeds read`, the inbox and monitoring carry on. `infra resume` lifts the flag file. Taylor
  can say "halt the factory" by text; the reply is `infra halt "<his words>"`.

## Credentials by asset id

A Factory mailbox's login lives in the toolbelt env under its registry row's id:
`OUTREACH_MAILBOX_<ID>_PASSWORD`, `_USER`, `_SMTP`, `_IMAP`. `lib/outreach_mail.py credentials()` reads those
first and falls back to the old `OUTREACH_APP_PASSWORD_<ADDRESS>` on the lane's hosts, so the Workspace mailboxes
keep working unchanged, and a Factory mailbox needs no entry in `OUTREACH_MAILBOXES` at all (B150: the lane reads the
registry). Which mailboxes send cold, and when, is the registry's rule (`active` under a PERMITTED contract), not this file's.
Keys stay on this box: `infra` never runs inside a sandboxed or headless client run (plan 55 § 5.8).

## The Infraforge adapter: confirmed on the first live unit (2026-10-08)

Base `https://api.infraforge.ai/public` (`INFRA_PROVIDER_API_BASE`), `Authorization: <key>`. Confirmed by the
first two domains (getpatchlamp.com, patchlamphq.com; Flint with Taylor's go), corrected in
`lib/providers/infraforge.py` the same afternoon:

| what | what Infraforge actually wants | status |
|---|---|---|
| workspaces | `GET /workspaces` → `[{id, name, slug, mailserver}]`; `mailserver` is every mailbox's SMTP (465) and IMAP (993) host | confirmed |
| availability | `GET /check-domain-availability?domain=` → `{available, price, minCreationPeriodMonths}` | confirmed ($14 a .com) |
| purchase | `POST /domains {"domains": [..], "workspaceId", "contactDetails": {firstName, lastName, email, address1, city, province, postalCode, country, organization, phone}}`; the registrant is the venture's `[registrant]` | confirmed |
| list domains | `GET /domains` → rows with `sld` + `tld` (no `name`), `autoRenewStatus`, `expiresAt`, `status` | confirmed |
| DNS read | `GET /domains/{id}/dns` → MX, SPF, DMARC (`p=reject`), DKIM at `default._domainkey`, all set on purchase, `editable: false` | confirmed |
| DNS write | `PUT /domains/{id}/dns {"records": [{"name": <full hostname; the apex is the domain itself>, "type", "value"}]}` → visible in public DNS within a minute | confirmed (the Postmaster TXT, 2026-10-08) |
| auto-renew | `PUT /domains/{id}/enable-autorenew` → 204; the vendor registers with it **off**, so `buy_domain` turns it on | confirmed |
| mailboxes | `POST /mailboxes {"domains": [{"domain": D, "mailboxes": [{"email", "firstName", "lastName"}]}]}`; the create body's `password` is ignored; `PATCH /mailboxes/{id} {"password"}` sets it (the login was refused, 535, until then); the record carries no hosts and no credentials | confirmed |
| warm-up enrolment | **Infraforge doesn't warm; Warmforge does** (Taylor, 2026-10-08). The one API path: `POST /mailboxes/export-to-salesforge {fromWorkspaceId, toWorkspaceId (Salesforge), toWarmforgeWorkspaceId, tagName, warmupActivated: true, includedIds}` — needs a Salesforge subscription ($40/mo Pro, unlimited Warmforge). With `INFRA_SALESFORGE_WORKSPACE` and `INFRA_WARMFORGE_WORKSPACE` set it is a call; else a filed click in Warmforge ($10 a slot a month standalone) | confirmed (the body by probe; the call itself on the first unit with the ids) |
| placement probe | none | certification rests on our seeds |
| idempotency | `Idempotency-Key` sent; not documented | our ledger key is the guard |
| DNS delete, pre-warmed inventory | not seen; none on offer 2026-10-08 ("out of pre-warmed domains") | filed steps |

A 400 answers with `{"message": "invalid request body", "data": ["<field> is a required field", …]}`, and `_req`
now carries that body in its error, so the next unknown field is read, not guessed.

## When something goes wrong

- **"no PERMITTED contract verdict"**: the terms haven't been read; the TODO entry says how. Not a bug.
- **"the provider doesn't show it" (exit 6)**: a purchase was in flight when a run died. Look in the dashboard;
  if the domain is there, re-run the line (it will find it); if it isn't, re-run with `--retry-purchase`.
- **VERIFY failed (exit 4)**: usually DNS still propagating. Re-run in an hour. If a record is truly missing, the
  vendor didn't set it: `infra rollback` and tell Flint, or fix it in the dashboard and re-run.
- **A human step (exit 3)**: it's in TAYLOR-TODO § 1 with the exact click; re-run the same line when it's ticked.
- **Halted (exit 5)**: on purpose. `infra status` says who halted it and why.
- If you can't tell what happened, `infra status` and the operation's journal under `ops/` are the record; saying
  "I couldn't, here's what I saw" is a good report.
