# claude-tools

Small CLIs Claude Code calls from any project on this machine — its "toolbelt".
Each one reads its API keys from `~/.config/claude-tools/env` and never prints
them, so Claude can use a service without ever seeing the credential.

| tool | what |
|---|---|
| `bin/pf` | [Plateful](https://plateful.fyi) operator API: menu, photos, availability, orders, restaurant-scoped key minting. `PF_RESTAURANT=x` pins it to one restaurant's key and refuses to fall back to the platform key. |
| `bin/img` | Images: `img stock` (Pexels search + download), `img gen` (Gemini image generation, with style presets like `--style plateful-menu`), `img info`, `img doctor`. Every image gets a JSON sidecar recording its provenance. |
| `bin/client` | Client workspaces (`~/projects/clients/<slug>`): `client new <slug> --name "Name" [--plateful SUB] [--live-url URL]` stamps CLAUDE.md + the permission allowlist from `templates/client/` and prints the `config.json` entry; `client ls`, `client doctor`, `client snippet`. `--restamp` rewrites the two files after a template change (repos/ and incoming/ untouched). No keys. |
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

## The key file

`~/.config/claude-tools/env` is `KEY=value` lines, mode 600, written only by
`setenv.sh`. The convention every tool follows:

- read the file at startup, keep values in memory, never log or print them;
- when a key is missing, tell the user which `setenv.sh NAME` to run;
- `<tool> doctor` reports which keys are set and whether they authenticate,
  without revealing them.

Set `CLAUDE_TOOLS_ENV` to point the tools at a different file (tests, a second
machine).

## Adding a tool

Drop an executable in `bin/`, have it read keys the same way (`img` has a
compact `read_env` you can copy), give it a `doctor` subcommand, add it to the
table above, and list any new key names in `KNOWN_KEYS` in `setenv.sh`. Re-run
`install.sh`.
