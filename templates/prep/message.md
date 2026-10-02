<!--
The prep run's message frame (plan ~/projects/plans/28-prep-run.md § Contracts, "The message").
Fixed text Taylor approves once with `prep approve` (the hash of this file is what he approved:
edit a word and it needs approving again). Code fills the braces; the builder writes only
{specific}, one sentence of at most 140 characters from `high` facts.

  {business}     plain_name(): the business as a person says it, never a person's name
  {fault}        the first computed fault of their listing, said to them (to_you())
  {specific}     the builder's one sentence (message.json), from high facts
  {preview_url}  their preview, the only link

`## message` is what Taylor pastes into an Instagram DM, a Facebook message or an email.
Its shape (Steel, 2026-10-02, Taylor's word): a six-word intro, the fault, "so I built you one",
the builder's sentence, the link, and a question at the end — a reader between jobs answers a
question and scrolls past a statement; the business name is in the sentence, not the greeting.
`## call` is what he says when the only way in is the phone (`prep run --allow-calls`).
Lint in code: under 700 characters, one link and it is the preview, no price, no guarded
word, no exclamation mark.
-->

## message

Hi, I'm Taylor. I fix websites for small businesses around American Fork. I looked {business} up on Google and {fault}. So I built you one. {specific} Here it is: {preview_url} Nothing to sign, and I'll take it down the moment you say so. Worth a look?

## call

Say: "Hi, is this {business}? This is Taylor. I fix websites for small businesses around American Fork. I looked you up on Google and {fault}. So I built you one. {specific} Could I text you the link? Nothing to sign, and I'll take it down the moment you say so."
