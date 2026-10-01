#!/usr/bin/env bash
# Deploy Cloudflare Worker webhook: /scan + shared /settings.
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
WORKER_URL="${WORKER_URL:-https://marketplace-telegram-webhook.hello-forward.workers.dev}"
CONFIG_TOKEN="${CONFIG_TOKEN:-$(openssl rand -hex 24)}"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
  GITHUB_TOKEN="$(gh auth token)"
fi
: "${GITHUB_TOKEN:?Need GITHUB_TOKEN or gh auth login}"

echo "Deploying Cloudflare Worker…"
npx --yes wrangler@4 deploy

echo "Setting Worker secrets…"
printf '%s' "$TELEGRAM_BOT_TOKEN" | npx --yes wrangler@4 secret put TELEGRAM_BOT_TOKEN
printf '%s' "$TELEGRAM_CHAT_ID" | npx --yes wrangler@4 secret put TELEGRAM_CHAT_IDS
printf '%s' "$GITHUB_TOKEN" | npx --yes wrangler@4 secret put GITHUB_TOKEN
printf '%s' "$REPO" | npx --yes wrangler@4 secret put GITHUB_REPO
printf '%s' "$CONFIG_TOKEN" | npx --yes wrangler@4 secret put CONFIG_TOKEN

# Seed default shared config into remote KV
echo "Seeding KV config…"
npx --yes wrangler@4 kv key put config --remote \
  --namespace-id=5c38578fe2534736ae844cfb6bfc2453 \
  --path=./default-config.json

WORKER_URL="${WORKER_URL%/}"
echo "Pointing Telegram webhook → $WORKER_URL (message + callback_query)"
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=${WORKER_URL}" \
  --data-urlencode 'allowed_updates=["message","callback_query"]' | tee /tmp/setwebhook.json
echo

echo "Setting GitHub Actions secrets for live config…"
gh secret set SETTINGS_CONFIG_URL --repo "$REPO" --body "${WORKER_URL}/config"
gh secret set SETTINGS_CONFIG_TOKEN --repo "$REPO" --body "$CONFIG_TOKEN"

echo
echo "Done."
echo "  Worker:  $WORKER_URL"
echo "  Config:  $WORKER_URL/config"
echo "  Telegram: /settings  (shared group filters)  /scan"
echo "Save CONFIG_TOKEN somewhere if you need to re-set GitHub secrets later."
