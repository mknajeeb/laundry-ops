#!/usr/bin/env bash
# Choose WashPro or VeeWash (Mac user package). Skip prompt: RINSE_VENDOR=washpro|veewash
set -euo pipefail

_raw="${RINSE_VENDOR:-}"
if [[ -n "$_raw" ]]; then
  _low="$(printf '%s' "$_raw" | tr '[:upper:]' '[:lower:]')"
  case "$_low" in
    washpro|wash-pro|wp) echo washpro; exit 0 ;;
    veewash|vee-wash|vee|vw) echo veewash; exit 0 ;;
    *) echo "Unknown RINSE_VENDOR: $_raw (use washpro or veewash)" >&2; exit 1 ;;
  esac
fi

# Optional macOS dialog when launched from Finder (.command) and osascript exists
if [[ "$(uname -s)" == "Darwin" ]] && command -v osascript >/dev/null 2>&1; then
  _choice="$(osascript <<'APPLESCRIPT' 2>/dev/null || true
set d to display dialog "Which Rinse vendor are you scraping?" with title "Rinse export" buttons {"VeeWash", "WashPro"} default button "WashPro" cancel button ""
if button returned of d is "WashPro" then
  return "washpro"
else
  return "veewash"
end if
APPLESCRIPT
)"
  if [[ "$_choice" == "washpro" || "$_choice" == "veewash" ]]; then
    echo "$_choice"
    exit 0
  fi
fi

echo ""
echo "Which Rinse vendor portal are you using?"
echo "  1) WashPro"
echo "  2) VeeWash"
echo ""
printf "Enter 1 or 2: "
read -r _pick
_pick_low="$(printf '%s' "$_pick" | tr '[:upper:]' '[:lower:]')"
case "$_pick_low" in
  1|washpro|wash\ pro) echo washpro ;;
  2|veewash|vee\ wash) echo veewash ;;
  *)
    echo "Invalid choice." >&2
    exit 1
    ;;
esac
