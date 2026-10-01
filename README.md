# Facebook Marketplace → Telegram (Canada)

Watches Canadian Facebook Marketplace for your car searches every **30 minutes** and sends **new** listings to Telegram (never the same post twice).

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

## Tweaking searches

Edit `config.yaml`:

- `searches` — query, year/price, keyword rules  
- `locations` — Marketplace URL slugs to visit  
- `location_keywords` — which city names to keep  

## Run online (laptop off)

See **[DEPLOY.md](DEPLOY.md)** for:

- **GitHub Actions** — free, every 30 minutes in the cloud  
- **Docker** — always-on on a VPS / Railway / Render  

## Notes

- Facebook changes markup often and may show checkpoints / rate-limit automation. If scrapes return 0 results, re-run `python -m src.save_session` and try `HEADLESS=false`.
- Use this for **personal** alerts on your own account. Aggressive scraping can lock the account — keep intervals ≥ 30 minutes and don’t add dozens of cities.
- This is not an official Facebook API.
