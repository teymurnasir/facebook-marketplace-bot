#!/usr/bin/env bash
# Encode storage_state.json for GitHub Actions secret FACEBOOK_STORAGE_STATE_B64
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FILE="${1:-$ROOT/storage_state.json}"

if [[ ! -f "$FILE" ]]; then
  echo "Missing $FILE — run: python -m src.save_session"
  exit 1
fi

echo "Copy everything below into GitHub → Settings → Secrets → FACEBOOK_STORAGE_STATE_B64"
echo "--------------------------------------------------------------------"
base64 < "$FILE" | tr -d '\n'
echo
echo "--------------------------------------------------------------------"
