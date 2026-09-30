# Batch: the night's sites side by side

Tonight's preview sites each passed their own judge. You see them together,
the way Taylor will in the morning: one after another on his phone, and then
the messages he'll paste to each business. Your job is what no single judge
could see: sameness, and the order.

Caps: **15 minutes, 40 turns.** You read, you write `batch.json`, you stop.

## What you have

- `messages.json` — one row a site: `slug`, `name`, `category`, `city`,
  `look`, the hero photo's `hero_id` and `hero_alt`, `screen` (the first phone
  screen, a PNG here), and `message` (the text Taylor will send).
- `screens/` — the first phone screen of each site. Look at every one.

## The checks

1. **No two heroes alike**: the same photo, or two photos a person would
   take for the same shot, on two sites.
2. **No more than four of ten in one look** (code balances the looks; say so
   if two sites still read as the same template filled twice).
3. **The messages read as different notes**: each one's specific line is about
   that business. Two messages that say the same thing about two businesses
   read like a mail merge.
4. **The order**: the best first. Taylor sends from the top when his time is
   short: the sites that most clearly show the business, with a reach that
   will be read, go first.

## What you can do

- Reorder: `order` lists every slug, best first.
- Hold one back: `drop` a slug with the reason, when it spoils the batch
  (its hero is another's, its message says nothing of its own) and a fix is
  not possible tonight. Code removes it; the rest go out. Use it rarely.
- Note: one line a slug in `notes`, for Taylor.

Write `batch.json`, exactly this shape:

```json
{"schema": 1,
 "order": ["pinnacle-painting-sandy", "lemon-detailing-lehi", "garage-doctors-of-utah-mapleton"],
 "drop": {},
 "notes": {"lemon-detailing-lehi": "The pick-up and drop-off line is the strongest opener of the night."},
 "heroes_alike": [],
 "messages_alike": [],
 "last_word": "Three distinct sites; the painter's is the one to send first."}
```

You write `batch.json` and nothing else; you run nothing; you never contact
anyone. When it is written, stop.
