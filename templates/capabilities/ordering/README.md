# Ordering — the Order button

What this is: the client's own ordering page runs on Plateful (the engine
behind Patchlamp). This capability is the **link to it from their own site** —
a button in the header of every page and a short section on the home page.
Nothing here rebuilds ordering; the storefront already exists the moment
Taylor has set their restaurant up.

`PLAYBOOK.md` § Ordering in the workspace is the page to read first: what to
say to the client, and the order to do things in. This folder is just the
files.

## The three files

| file | where it goes |
|---|---|
| `button.html` | the header nav of **every** `.html` page in the site repo |
| `section.html` | the home page, after the menu, before "Find us" |
| `ordering.css` | appended to the site's `css/style.css` |

Fill two placeholders:

- `{{ORDER_URL}}` — the storefront, exactly as `pf me` prints it under
  `url=` for this restaurant (e.g. `https://marcos.plateful.fyi`). Never
  type it from memory; a wrong subdomain is a dead button on a live site.
- `{{NAME}}` — the restaurant's name as the site already writes it.

## Rules

- **Every page.** The site template has no includes, so the header is
  repeated in each `.html` file. Miss one and the button vanishes halfway
  through the site. `shot site <repo>` is how you check them all.
- **Don't restyle the site to suit the button.** `ordering.css` uses the
  site's own tokens on purpose. If the accent colour makes it invisible,
  change the button's rule here, not the site's palette.
- **One link target.** The button goes to their storefront and nowhere else.
  No tracking parameters, no shortener.
- **Pickup-only restaurants**: delete the delivery half of the sentence in
  `section.html` rather than promising something they don't do. `pf me`
  prints nothing about delivery, so ask the client if you don't know.
