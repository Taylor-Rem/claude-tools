#!/usr/bin/env bash
# Fill ~/.config/claude-tools/env without opening an editor.
#
# This file holds Claude's cross-project "toolbelt" keys (stock photos, image
# generation, Plateful operator key, ...). App secrets stay in each repo's own
# .env — this is only for tools Claude calls from any project.
#
# Secrets are read with echo disabled, so nothing lands in shell history,
# scrollback, or a Claude transcript. Re-run any time: press Enter at a prompt
# to keep the value that's already there.
#
#   ./setenv.sh                 # walk through the known keys
#   ./setenv.sh SOME_NEW_KEY    # add/update just the named key(s)
#   ./setenv.sh --list          # show which keys are set (never the values)
#
# Tools consume the file with:
#   set -a; . "$HOME/.config/claude-tools/env"; set +a

set -euo pipefail
umask 077

ENV_FILE="${CLAUDE_TOOLS_ENV:-$HOME/.config/claude-tools/env}"
KNOWN_KEYS=(
  PEXELS_API_KEY        # img stock
  GEMINI_API_KEY        # img gen
  PLATEFUL_API_KEY      # pf (platform key; PLATEFUL_KEY_<SUB> are minted by `pf keys create`)
  TELEGRAM_BOT_TOKEN    # sms-relay
  DISCORD_BOT_TOKEN     # sms-relay
  GITHUB_TOKEN          # site (repo create/pages); gh honours it as GH_TOKEN
  GOOGLE_MAPS_API_KEY   # leads (Places API (New), Place Details)
)

mkdir -p "$(dirname "$ENV_FILE")"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

# Pull whatever is already set so re-running is non-destructive.
declare -A current=()
while IFS='=' read -r k v; do
  [[ -z "$k" || "$k" == \#* ]] && continue
  current["$k"]="$v"
done < "$ENV_FILE"

if [[ "${1:-}" == "--list" ]]; then
  for k in "${!current[@]}"; do
    if [[ -n "${current[$k]}" ]]; then echo "$k  (set)"; else echo "$k  (empty)"; fi
  done | sort
  exit 0
fi

keys=("${@:-}")
[[ -z "${keys[0]}" ]] && keys=("${KNOWN_KEYS[@]}")

for k in "${keys[@]}"; do
  if [[ -n "${current[$k]:-}" ]]; then hint="(set — Enter to keep)"; else hint="(empty)"; fi
  read -rs -p "$k $hint: " val
  echo
  if [[ -n "$val" ]]; then
    current["$k"]="$val"
  else
    current["$k"]="${current[$k]:-}"
  fi
done

tmp="$(mktemp "${ENV_FILE}.XXXXXX")"
{
  echo "# Claude toolbelt keys. Managed by setenv.sh — values never echoed."
  for k in $(printf '%s\n' "${!current[@]}" | sort); do
    printf '%s=%s\n' "$k" "${current[$k]}"
  done
} > "$tmp"
chmod 600 "$tmp"
mv "$tmp" "$ENV_FILE"

echo "Wrote $ENV_FILE ($(grep -c '=' "$ENV_FILE") keys)."
