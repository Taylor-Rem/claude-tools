# claude-tools — read first

`README.md` here for the tools; `../VISION.md` for what they serve. These CLIs
are shared by every session on the machine: keep them backwards compatible,
read keys by name from `~/.config/claude-tools/env`, never print a value.
`img gen` writes a cost ledger line per image — anything else that spends
money should too (see `sms-relay/relay/ledger.py`).
