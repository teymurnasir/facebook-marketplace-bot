# Facebook Marketplace → Telegram (Canada)

Watches Canadian Facebook Marketplace for your car searches on a safer cloud interval and sends **new** listings to Telegram (never the same post twice).

## Searches (editable in `config.yaml`)

| Search | Years | Price (CAD) | Notes |
|--------|-------|-------------|--------|
| Mazda 3 | 2010–2014 | $300–$2300 | sedan/hatch optional keywords |
| Kia Optima Hybrid | 2011–2017 | $1000–$3000 | requires “hybrid” in title |

**Areas:** Toronto, Richmond Hill, Brampton, North York, Vaughan, Markham, East York, Mississauga, Scarborough, Hamilton (filter keywords). Scrapes a smaller set of hub cities so Facebook is less likely to throttle you.

## Setup

### 1. Python deps

```bash
cd facebook-script
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Telegram bot

1. Message [@BotFather](https://t.me/BotFather) → `/newbot` → copy the token.
2. Message your bot once (say `/start`).
3. Get your chat id: open  
   `https://api.telegram.org/bot<TOKEN>/getUpdates`  
   and copy `chat.id` (or use [@userinfobot](https://t.me/userinfobot)).

```bash
cp .env.example .env
# edit .env — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
```

### 3. Facebook login session (required)

Marketplace needs a logged-in browser session:

Cloud login snapshots are encrypted before caching. Set GitHub secret
`FACEBOOK_SESSION_CACHE_KEY` to a securely generated Fernet key, separately from
`FACEBOOK_STORAGE_STATE_B64`. Missing or invalid keys stop the workflow; the bot
never uploads plaintext login JSON to an Actions cache. Key rotation creates a
new encrypted cache generation. Never commit either secret or `storage_state.json`.
If login snapshots were previously cached in a public repository, delete those
caches and invalidate the exposed Facebook sessions before resuming scans.

```bash
python -m src.save_session
```

Log in, open Marketplace, press Enter in the terminal. This writes `storage_state.json` (gitignored).

### 4. First run (recommended): seed without spam

Marks everything currently listed as “already seen” so you only get **new** posts after that:

```bash
python main.py --seed
```

### 5. Start watching

```bash
python main.py
```

Useful flags:

- `python main.py --once` — one scan, then exit  
- `python main.py --seed` — mark current results seen, no Telegram  
- `HEADLESS=false` in `.env` — show the browser while debugging  

## How it works

1. Every `POLL_INTERVAL_MINUTES` (default 30), Chromium opens each hub city × each search URL (year + price filters).
2. Listings are parsed from the page (and Marketplace GraphQL when available).
3. Extra keyword filters run (e.g. Optima **hybrid**).
4. IDs are stored in `data/seen.db`; only unseen IDs are sent to Telegram.

Each scan sends a Telegram start message, confirms **Facebook session active** after
reading Marketplace listing data with the logged-in session, and includes that
status in the completion message. Login/checkpoint pages send a **login needed**
alert and stop the scan. If no authenticated listing data can be read, the bot
reports **status not verified** rather than assuming Facebook is active. Session
checks reuse the scan pages and do not add extra Facebook requests. `--seed` stays
silent. Disabling `TELEGRAM_SCAN_SUMMARY` hides only the completion summary.

For cloud scans, a confirmed login/checkpoint failure also records an inactive
session in the Worker and pauses automatic dispatches without changing the saved
interval or deleting findings. Repeated timer ticks stay silent while paused.
Send `/session` (or `/status`) for the last recorded Facebook check and pause
state; this command does not visit Facebook. To recover, log in locally with
`python -m src.save_session`, update `FACEBOOK_STORAGE_STATE_B64`, then send
`/scan`. Updating the secret or queueing a scan does not itself clear the pause:
a completed scan must read authenticated Marketplace data. Empty results,
network errors, browser crashes, and stale scan reports cannot clear the guard.
After verified recovery, the next automatic scan waits the full saved interval.
The guard prevents repeated failed automatic attempts; it does not reactivate a
Facebook account or guarantee that Facebook will accept a session indefinitely.

To test whether only the refreshed cache was rejected, use
`gh workflow run marketplace.yml --ref main -f reset_session=true` once. This
tries the existing original secret, not a new login, and does not clear the
pause until the scan verifies access. A security checkpoint requires action in
your normal browser; do not repeatedly dispatch recovery scans. If the original
secret is also rejected, refresh it from a valid login before testing again.

Send `/cars` in Telegram to browse all saved database findings, newest first,
with price, year, mileage, location, first/last seen dates, Marketplace links,
and Previous/Next buttons. Each page shows three cars. `/cars 2` opens page two.
Each successful scan syncs the complete `seen.db` history to the Cloudflare bot;
browsing does not start a Facebook scan. Old findings may include ads that have
since been removed. Only authorized Telegram chats can view the list.
Older saved findings are enriched when they reappear in a scan. Missing details
are labeled explicitly; the bot does not guess prices or mileage. Enrichment
does not re-send previously notified ads.

Search variants are honored (including "Optima HEV" for a hybrid search), while
hybrid searches still require hybrid/HEV/PHEV evidence in the card or seller description.
Scan summaries include the number of inspected and matching cards per search
and exclusion reasons when a search finds no matches.

Safety is shown in new alerts and `/cars` as `yes`, `no`, or `unknown`, based on
the seller's description about safety certification. A short seller excerpt is
included when available. Conditional claims (e.g. "can provide safety"), missing
descriptions, and conflicting claims stay unknown. This is a seller statement,
not an independent inspection or confirmation that a certificate is valid.
Descriptions are cached for 24 hours, with up to 30 detail-page visits per scan;
unavailable or unchecked descriptions remain unknown. Description mileage and
hybrid evidence are also used when the search card does not provide them.

Every saved, manual, and custom car search uses the same automatic query expansion:
compact names, model-number spacing/hyphens, and brand-omitted model names when
the make is recognized and the model is not purely numeric. For example,
`ford f150` also searches `ford f 150`, `ford f-150`, and `f150`;
`toyota camry hybrid` also searches `camry hybrid`, `toyota camry hev`, and
`toyota camry`. Hybrid evidence is still required, and a PHEV search requires
plug-in evidence. `HUV` is only a search spelling, never hybrid evidence.
Expansion stops at ten total queries; explicitly configured aliases are always
preserved even if they exceed ten. Unknown typos, translations, and alternative
model names can be added to `queries`; the bot cannot guarantee every possible ad.
Existing year, price, mileage, area, and custom keyword filters remain in effect.

## Tweaking searches

Edit `config.yaml`:

- `searches` — query, year/price, keyword rules  
- `locations` — Marketplace URL slugs to visit  
- `location_keywords` — which city names to keep  

## Run online (laptop off)

See **[DEPLOY.md](DEPLOY.md)** for:

- **GitHub Actions** — free cloud checks with a conservative Telegram-controlled interval  
- **Docker** — always-on on a VPS / Railway / Render  

## Notes

- Facebook changes markup often and may show checkpoints / rate-limit automation. If scrapes return 0 results, re-run `python -m src.save_session` and try `HEADLESS=false`.
- Use this for **personal** alerts on your own account. Aggressive scraping can lock the account — prefer 2-3 hour intervals and don’t add dozens of cities.
- This is not an official Facebook API.


## House rental watcher (MLS listings via Royal LePage)

`rental_main.py` uses the same `.env`, Python installation, Telegram bot and
recipients. It reads Royal LePage's public rental pages over HTTP, including
listings supplied by other brokerages. This avoids Realtor.ca's automated-browser
block; no Realtor account, saved Facebook session, API subscription or browser
installation is needed for the rental scan. Source coverage can differ from
Realtor.ca.

`rental-config.yaml` configures House, 2+ total bedrooms, CAD $2,000–$4,100/month,
finished basement and separate entrance. The original Realtor map link supplies
the exact rectangle; the car search radius does not apply. The watcher checks
coordinates itself. It assumes an entire house and excludes explicitly advertised
partial house rentals (`entire_house_only: false` permits basement apartments).
Basement and entrance criteria require affirmative description or structured
property fields. Unknown facts and non-monthly rent are excluded.

The source search covers Toronto, then applies the exact supplied bounds locally.
Every results page must complete before any alerts are sent. Provider result caps,
missing filters, access errors and incomplete pagination fail the scan instead of
being reported as zero matches. Detail pages are fetched only for candidates in
the selected rectangle, with a delay between requests. Matching is based on
listing data, not an independent inspection of the property.

```bash
# One scan; print matches without Telegram or saved history:
python rental_main.py --dry-run
# Send new matches to the existing Telegram recipients:
python rental_main.py --once
# Mark current matches seen silently for the configured recipients:
python rental_main.py --seed
# Run locally every poll_interval_minutes (default 180):
python rental_main.py
```

Delivery history is stored separately in `data/rentals.db`, per recipient.
Failed deliveries are retried on the next scan. Telegram `/rentals` starts the
independent `rentals.yml` GitHub workflow, subject to the existing authorized-chat
restriction and a five-minute command cooldown. The workflow also runs every
three hours (GitHub scheduling can be delayed). Automatic scans stay quiet when
there are no new matches; manual scans send a completion summary. Rental errors
are reported explicitly. The Facebook workflow, its session guard, `/settings`
and car findings remain independent.

The workflow reuses existing GitHub Telegram secrets and caches rental delivery
history separately. Publish the source/workflow to the default branch, deploy
the existing Worker, and run `python scripts/set_telegram_commands.py` to update
the bot menu. Change the workflow cron for cloud frequency; change
`poll_interval_minutes` for local frequency. Run only one deployment mode at a
time to avoid duplicate notifications from independent local/cloud histories.

The optional `source: realtor` backend remains experimental because automated
Realtor.ca access is blocked in the tested environment. `source: royallepage`
is the default and uses verified public HTML selectors and pagination.
