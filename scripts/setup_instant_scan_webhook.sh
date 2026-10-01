#!/usr/bin/env bash
# Deploy Cloudflare Worker webhook so /scan starts immediately.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/telegram-webhook"

if [[ ! -f "$ROOT/.env" ]]; then
  echo "Missing .env"
  exit 1
fi

# shellcheck disable=SC1091
set -a
source "$ROOT/.env"
set +a

: "${TELEGRAM_BOT_TOKEN:?}"
: "${TELEGRAM_CHAT_ID:?}"

REPO="${GITHUB_REPO:-teymurnasir/facebook-marketplace-bot}"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  GITHUB_TOKEN="$(gh auth token)"
fi
: "${GITHUB_TOKEN:?Need GITHUB_TOKEN or gh auth login}"

echo "Deploying Cloudflare Worker (login/browser may open)…"
npx --yes wrangler@4 deploy

echo "Setting Worker secrets…"
printf '%s' "$TELEGRAM_BOT_TOKEN" | npx --yes wrangler@4 secret put TELEGRAM_BOT_TOKEN
printf '%s' "$TELEGRAM_CHAT_ID" | npx --yes wrangler@4 secret put TELEGRAM_CHAT_IDS
printf '%s' "$GITHUB_TOKEN" | npx --yes wrangler@4 secret put GITHUB_TOKEN
printf '%s' "$REPO" | npx --yes wrangler@4 secret put GITHUB_REPO

WORKER_URL="$(npx --yes wrangler@4 deployments list 2>/dev/null | head -5 || true)"
echo "If deploy printed a workers.dev URL, using that for webhook."
echo "Enter the Worker URL (https://….workers.dev):"
read -r WORKER_URL
WORKER_URL="${WORKER_URL%/}"

echo "Pointing Telegram webhook → $WORKER_URL"
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=${WORKER_URL}" \
  -d "allowed_updates=[\"message\"]" | tee /tmp/setwebhook.json
echo
echo "Done. Disable the old GitHub poller schedule if still enabled."
echo "Test in Telegram: /scan"
