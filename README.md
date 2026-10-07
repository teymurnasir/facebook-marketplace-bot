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
hybrid searches still require hybrid/HEV/PHEV evidence in the listing card.
Scan summaries include the number of inspected and matching cards per search
and exclusion reasons when a search finds no matches.

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
