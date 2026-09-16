# claude-tools

Small CLIs Claude Code calls from any project on this machine — its "toolbelt".
Each one reads its API keys from `~/.config/claude-tools/env` and never prints
them, so Claude can use a service without ever seeing the credential.

| tool | what |
|---|---|
| `bin/pf` | [Plateful](https://plateful.fyi) operator API: menu, photos, availability, orders, restaurant-scoped key minting. `PF_RESTAURANT=x` pins it to one restaurant's key and refuses to fall back to the platform key. |
| `bin/img` | Images: `img stock` (Pexels search + download), `img gen` (Gemini image generation, with style presets like `--style plateful-menu`), `img info`, `img doctor`. Every image gets a JSON sidecar recording its provenance. |
| `bin/discord` | Read-only view of the Discord servers the relay bot is in: `discord ls` (channels + last activity), `discord read "#memes" -n 30`, `discord doctor`. Chat rooms use it to see the rest of the server. |
| `bin/client` | Client workspaces (`~/projects/clients/<slug>`): `client new <slug> --name "Name" [--plateful SUB] [--live-url URL]` stamps CLAUDE.md + the permission allowlist from `templates/client/` and prints the `config.json` entry; `client ls`, `client doctor`, `client snippet`. `--restamp` rewrites the two files after a template change (repos/ and incoming/ untouched). Per-client facts that must survive a restamp (who decides what, standing instructions) live in the workspace's `NOTES.md`, folded into CLAUDE.md under "Notes for this client" on every stamp. No keys. |
| `bin/site` | Client websites on **Cloudflare Pages**, run *inside* a client workspace (`cd ~/projects/clients/<slug>`): `site new <name>` creates a public repo under `SITE_ORG` from `templates/site/`, clones it into `repos/<name>`, creates the Pages project by API, publishes it, writes the URL into `.client.json` and restamps the allowlist; `site publish [<name>]` sends the committed, pushed HEAD to the project by direct upload (`wrangler`, from this repo's `node_modules`) and reports the live URL + `Cache-Control` — seconds, no build, no shared deploy; `site ls`; `SITE_ADMIN=1 site domain <name> example.com` (apex + www on the project, the www→apex rule into `_redirects`, the two DNS lines for the registrar; no domain = validation/cert state); `SITE_ADMIN=1 site adopt <name>` (register a pre-Cloudflare repo and create its project); `SITE_ADMIN=1 site transfer <name> <github-user>`; `site template push`; `site doctor`. Which project a workspace may publish to lives in `~/.config/claude-tools/sites.json` (written by `new`/`adopt`, unreachable from a client session), never in an argument. Legacy GitHub Pages: `site new --gh-pages`, `site stamp`. Keys by name: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `GITHUB_TOKEN` (else `gh`'s login), `SITE_ORG`. |
| `bin/shot` | A headless browser so Claude can *look* at pages: `shot <url or local folder/file>` writes a PNG under `./shots/` (`--mobile`, `--tablet`, `--full`, `--dark`, `--selector`, `--click`, `--scroll-to`, `--type`, `--js`, `--all-sizes`, `--jpg`) and reports console errors / failed requests; `shot check <target> [--all]` is a QA pass (errors, broken images and links, sideways scroll on phones, tiny tap targets, missing alt, fonts, title/h1/meta); `shot css <target> <selector> [props]` shows computed styles and boxes; `shot text` / `shot html`; `shot site` (every same-origin page, desktop + mobile); `shot diff a.png b.png`; `shot clean`; `shot doctor`. Local targets are served on a loopback port so relative links work. Inside a client workspace (a folder with `.client.json`) it sandboxes itself: targets and outputs stay in the workspace, no loopback/private addresses. Code in `lib/shot.mjs`, deps in `package.json` (`npm install`, `npx playwright install chromium`). No keys. |
| `bin/todo` | Taylor's todo (`~/projects/TAYLOR-TODO.md`) in the terminal and on the web: `todo ls`, `todo done N`, `todo add "…"`, `todo sync` (a systemd timer runs it every 2 min), `todo init` (one time), `todo site push` (publishes `todo-site/index.html` to the public Pages repo `todo`; the file itself lives in the private repo `taylor-todo`, read and ticked from the page with a fine-grained token that stays in the browser), `todo doctor`. A side-car git repo `~/projects/.todo-git` tracks only that one file. |
| `bin/ctx` | How full a Claude session's context is: `ctx` lists every relay conversation with a fuel gauge (tokens of the model's window), how long since it was used, and how long until it expires and the next message starts fresh; `ctx <name\|project\|session-id>` narrows it; `ctx here` measures the session running in the current directory; `ctx --json`, `ctx -v` (cache split, transcript path), `ctx --live`, `ctx doctor`. Reads Claude Code's own transcripts (`~/.claude/projects/<cwd>/<session>.jsonl`) plus the relay's `state/state.json`; the context size is `input + cache_creation + cache_read` from the last assistant record. Context windows come from the `claude-api` skill's model table — an unlisted model is shown with a `?` rather than a wrong number. No keys. |
| `templates/site/` | What `site new` copies: a two-page static site (`index.html`, `photos.html`, `404.html`, one stylesheet with `:root` tokens, one script), a thin `CLAUDE.md` (that site's structure and deploy check; client voice lives in the workspace), a path-scoped `.claude/settings.json` for interactive sessions, `.nojekyll`. Placeholders `{{NAME}} {{REPO}} {{URL}} {{OWNER}} {{YEAR}} {{TAGLINE}}` are filled before the first commit. |
| `templates/client/` | What `client new` stamps: `CLAUDE.md` (client voice, sites, photos, what's Taylor's work), `PLATEFUL.md` (appended when the client has a restaurant), `settings.json` (base allow/deny plus `_rules` added per feature: repos, plateful, live_url). Edit here, then `client new <slug> --restamp`. |
| `setenv.sh` | Fills the key file without echoing values: `setenv.sh` walks the known keys, `setenv.sh SOME_KEY` adds one, `setenv.sh --list` shows which are set. |

## Install

```
git clone git@github.com:Taylor-Rem/claude-tools.git ~/projects/claude-tools
~/projects/claude-tools/install.sh
~/.config/claude-tools/setenv.sh
```

`install.sh` symlinks `bin/*` into `~/.local/bin` and `setenv.sh` into
`~/.config/claude-tools/`, so pulling this repo updates the live commands.
Python 3.11+ with `requests` and `Pillow` (Debian: `python3-requests python3-pil`).
`shot` needs Node 20+: `install.sh` runs `npm install` here and downloads
Playwright's Chromium (or falls back to a system Chrome). `node_modules/` also
holds `@playwright/mcp`, which `~/projects/.mcp.json` points at.

## The key file

`~/.config/claude-tools/env` is `KEY=value` lines, mode 600, written only by
`setenv.sh`. The convention every tool follows:

- read the file at startup, keep values in memory, never log or print them;
- when a key is missing, tell the user which `setenv.sh NAME` to run;
- `<tool> doctor` reports which keys are set and whether they authenticate,
  without revealing them.

Set `CLAUDE_TOOLS_ENV` to point the tools at a different file (tests, a second
machine).

The same file also holds one non-secret setting, `SITE_ORG` (the GitHub org
`site` creates repos under), because a client session can't set environment
variables. `setenv.sh SITE_ORG` writes it.

## Adding a tool

Drop an executable in `bin/`, have it read keys the same way (`img` has a
compact `read_env` you can copy), give it a `doctor` subcommand, add it to the
table above, and list any new key names in `KNOWN_KEYS` in `setenv.sh`. Re-run
`install.sh`.
