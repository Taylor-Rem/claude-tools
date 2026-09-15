#!/usr/bin/env bash
# Symlink the tools into ~/.local/bin and setenv.sh into ~/.config/claude-tools,
# so `git pull` here updates the live commands. Safe to re-run.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.local/bin" "$HOME/.config/claude-tools"
chmod 700 "$HOME/.config/claude-tools"
for f in "$here"/bin/*; do
  ln -sfn "$f" "$HOME/.local/bin/$(basename "$f")"
  echo "linked ~/.local/bin/$(basename "$f")"
done
ln -sfn "$here/setenv.sh" "$HOME/.config/claude-tools/setenv.sh"
echo "linked ~/.config/claude-tools/setenv.sh"
if command -v npm >/dev/null 2>&1; then
  (cd "$here" && npm install --no-audit --no-fund --silent && echo "installed node deps (shot, playwright mcp)")
  (cd "$here" && npx --no playwright install chromium >/dev/null 2>&1 && echo "playwright chromium present") \
    || echo "note: playwright chromium not installed; shot falls back to a system Chrome"
else
  echo "note: npm not found; bin/shot needs node 20+ (apt install nodejs npm, then re-run)"
fi
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) echo "note: add ~/.local/bin to PATH";; esac
echo "next: ~/.config/claude-tools/setenv.sh   (fills the key file; values are never echoed)"
