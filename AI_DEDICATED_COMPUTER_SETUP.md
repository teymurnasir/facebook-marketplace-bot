# AI setup brief for the dedicated Facebook Marketplace computer

Read this file first on the second computer. The user should not need to
re-explain the project. Your job is to make this repository run reliably on
that computer as the dedicated 24/7 Facebook Marketplace scanner.

## What this project does

This repo is a personal Facebook Marketplace car-alert bot.

It:

1. Uses Playwright Chromium with a saved Facebook login session.
2. Scans Canadian Facebook Marketplace searches for configured cars.
3. Filters by year, price, mileage, query text, and location.
4. Stores seen listing IDs in SQLite so duplicates are not sent.
5. Sends new listings to Telegram.
6. Uses Telegram `/settings` through a Cloudflare Worker as the cloud source
   of truth for searches, locations, radius, mileage, and auto interval.

Main repo:

```text
https://github.com/teymurnasir/facebook-marketplace-bot
```

Important files:

```text
main.py
src/scraper.py
src/save_session.py
src/config_loader.py
src/storage.py
src/telegram_notifier.py
telegram-webhook/worker.js
.github/workflows/marketplace.yml
.github/workflows/auto-tick.yml
scripts/encode_session.sh
scripts/json_config_to_yaml.py
```

## Current live architecture

Current cloud flow:

```text
Telegram /settings
  -> Cloudflare Worker KV
  -> GitHub Actions marketplace.yml
  -> Python scanner
  -> Telegram alerts
```

Cloudflare Worker URL:

```text
https://marketplace-telegram-webhook.hello-forward.workers.dev
```

GitHub Actions secrets that already exist by name:

```text
FACEBOOK_STORAGE_STATE_B64
SEEN_DB_B64
SETTINGS_CONFIG_TOKEN
SETTINGS_CONFIG_URL
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID
```

Do not print or expose secret values.

## Recommended stable architecture for the second computer

Best stability is to run the Facebook-scanning workflow on the dedicated
computer via a GitHub self-hosted runner.

Reason: GitHub-hosted cloud runners use datacenter IPs and changing browser
environments, which increases Facebook login/checkpoint risk. A dedicated
computer on the user's normal/home network gives Facebook a more consistent
IP, machine, and browser session.

Target flow:

```text
Telegram /settings
  -> Cloudflare Worker KV
  -> GitHub Actions marketplace.yml
  -> self-hosted runner on second computer
  -> Playwright Chromium on second computer
  -> Telegram alerts
```

This keeps Telegram `/settings` and `/scan` working without redesigning the
bot.

## Setup steps on the second computer

Assume macOS unless the user explicitly says otherwise.

### 1. Install base tools

Install Xcode command line tools if missing:

```bash
xcode-select --install
```

Install Homebrew if missing:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Install required tools:

```bash
brew install python@3.12 node git gh
```

Authenticate GitHub CLI:

```bash
gh auth login
```

Use the GitHub account that owns or has admin access to:

```text
teymurnasir/facebook-marketplace-bot
```

### 2. Clone the repo

```bash
mkdir -p ~/Projects
cd ~/Projects
git clone https://github.com/teymurnasir/facebook-marketplace-bot.git
cd facebook-marketplace-bot
```

### 3. Install Python dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 4. Create local .env

Copy the example:

```bash
cp .env.example .env
```

Fill `.env` with the user's Telegram token/chat and runtime settings. If you
can read GitHub secret names but not values, ask the user for the values or
have them paste the existing `.env` from the first computer.

Minimum `.env`:

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
POLL_INTERVAL_MINUTES=30
HEADLESS=true
FACEBOOK_STORAGE_STATE=storage_state.json
```

Optional but useful if manually fetching Telegram settings:

```text
SETTINGS_CONFIG_URL=https://marketplace-telegram-webhook.hello-forward.workers.dev/config
SETTINGS_CONFIG_TOKEN=...
```

Never commit `.env`.

### 5. Save a Facebook session on this computer

This is required. Run:

```bash
source .venv/bin/activate
python3 -m src.save_session
```

A Chromium window opens. The user must log into Facebook, open Marketplace
once, then return to the terminal and press Enter.

Verify the session file contains the key Facebook cookies, without printing
cookie values:

```bash
python3 - <<'PY'
import json
d = json.load(open("storage_state.json"))
names = {c.get("name") for c in d.get("cookies", [])}
print("has_c_user:", "c_user" in names)
print("has_xs:", "xs" in names)
print("cookie_count:", len(d.get("cookies", [])))
PY
```

Expected:

```text
has_c_user: True
has_xs: True
```

### 6. Update GitHub secret with this computer's session

Still in the repo:

```bash
bash scripts/encode_session.sh
```

Copy the long base64 output.

Update GitHub repository secret:

```text
Repo -> Settings -> Secrets and variables -> Actions -> FACEBOOK_STORAGE_STATE_B64
```

Or use GitHub CLI:

```bash
gh secret set FACEBOOK_STORAGE_STATE_B64 --repo teymurnasir/facebook-marketplace-bot
```

Paste the long base64 value when prompted.

### 7. Install GitHub self-hosted runner

In GitHub:

```text
Repo -> Settings -> Actions -> Runners -> New self-hosted runner
```

Follow GitHub's macOS instructions exactly. When configuring labels, add:

```text
marketplace-bot
```

Install it as a service so it survives reboot. GitHub's runner setup normally
gives commands like:

```bash
./config.sh --url https://github.com/teymurnasir/facebook-marketplace-bot --token <TOKEN> --labels marketplace-bot
sudo ./svc.sh install
sudo ./svc.sh start
```

The exact token is generated by GitHub on the runner setup page. Do not invent
it.

Verify:

```bash
gh api repos/teymurnasir/facebook-marketplace-bot/actions/runners --jq '.runners[] | {name, status, labels: [.labels[].name]}'
```

Expected: runner is `online` and has the `marketplace-bot` label.

### 8. Move Marketplace scan workflow to the self-hosted runner

Only do this after the runner is online.

Edit:

```text
.github/workflows/marketplace.yml
```

Change:

```yaml
runs-on: ubuntu-latest
```

To:

```yaml
runs-on: [self-hosted, marketplace-bot]
```

Commit and push:

```bash
git checkout main
git pull
git add .github/workflows/marketplace.yml
git commit -m "Run marketplace scan on dedicated runner"
git push origin main
```

Do not change `auto-tick.yml` unless necessary. It can remain on
`ubuntu-latest` because it only pings the Worker and does not log into
Facebook.

### 9. Prevent the computer from sleeping

On macOS, make the computer stay awake while plugged in:

```bash
sudo pmset -a sleep 0 disksleep 0 womp 1
```

Also check:

```text
System Settings -> Lock Screen / Battery / Displays
```

Disable sleep while plugged in. Display sleep is OK; system sleep is not.

### 10. End-to-end verification

Run syntax checks:

```bash
python3 -m compileall -q main.py src scripts
node --check telegram-webhook/worker.js
```

Run a visible local browser test without Telegram spam:

```bash
HEADLESS=false .venv/bin/python main.py --seed
```

Expected:

```text
Saved refreshed Facebook session -> storage_state.json
Cycle done: <number> scraped, <number> new
Seed complete - existing listings marked seen, no Telegram spam
```

Run a real cloud/self-hosted test:

```bash
gh workflow run marketplace.yml --repo teymurnasir/facebook-marketplace-bot --ref main
gh run list --repo teymurnasir/facebook-marketplace-bot --workflow marketplace.yml --limit 3
```

Watch the newest run:

```bash
gh run watch <RUN_ID> --repo teymurnasir/facebook-marketplace-bot --exit-status
```

Success means:

```text
Load live Telegram settings or custom job: success
Restore Facebook session: success
Run one Marketplace scan: success
Save seen.db for next run: success
Save refreshed Facebook session for next run: success
```

### 11. Telegram verification

In Telegram:

```text
/settings
```

Verify cars, locations, radius, mileage, and auto interval.

Then:

```text
/scan
```

Expected:

1. Telegram says the scan started.
2. GitHub Actions starts `marketplace.yml`.
3. The job runs on the self-hosted runner.
4. New listings, if any, arrive in Telegram.

## Important operational notes

### Facebook session duration

No script can guarantee Facebook will never log out. Facebook can invalidate
sessions because of:

- Security checks.
- Login from different machines/IPs.
- Password or 2FA changes.
- Too many scans.
- Datacenter/cloud IPs.
- Marketplace automation detection.

The dedicated runner reduces risk because the browser/IP are more consistent,
but it cannot eliminate the risk.

When Facebook logs out:

```bash
cd ~/Projects/facebook-marketplace-bot
source .venv/bin/activate
python3 -m src.save_session
bash scripts/encode_session.sh
gh secret set FACEBOOK_STORAGE_STATE_B64 --repo teymurnasir/facebook-marketplace-bot
```

Then run `/scan` again.

### Do not commit local secrets/state

Never commit:

```text
.env
storage_state.json
data/
.wrangler/
```

These are intentionally gitignored.

### Avoid duplicate schedulers

Use one primary automatic scanner.

Preferred:

```text
auto-tick.yml -> Worker /tick -> marketplace.yml -> self-hosted runner
```

Do not also run a separate local loop unless you intentionally disable the
GitHub auto path, or duplicate Telegram alerts may happen because separate
machines can have separate `seen.db` state.

### Existing known-good verification from first computer

On 2026-10-02, a live GitHub Actions test passed:

```text
Cycle done: 11 scraped, 11 new
Saved refreshed Facebook session -> storage_state.json
```

A local visible browser test also passed:

```text
HEADLESS=false .venv/bin/python main.py --seed
Cycle done: 11 scraped, 11 new
Seed complete - existing listings marked seen, no Telegram spam
```

Use these as baseline expectations.

