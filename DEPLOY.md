# Run the bot online

Yes — you can run this in the cloud so your laptop can be off.  
Facebook login cookies still come from your account (saved once locally, uploaded as a secret).

**Important limits**

- Facebook may block datacenter / GitHub IPs. If scans start returning 0 results, refresh the session (`python -m src.save_session`) and update the secret.
- Sessions expire or get invalidated after password changes / checkpoints — re-export cookies when that happens.
- Keep the GitHub repo **private** (it holds a session secret).

---

## Option A — GitHub Actions (free, recommended)

Runs `python main.py --once` when the Telegram-controlled cloud interval is due. Use a conservative 2-3 hour interval for free cloud runs.

### 1. Create a private GitHub repo and push this project

```bash
cd /Users/teymurnasirli/Documents/facebook-script
git init
git add .
git commit -m "Facebook Marketplace Telegram bot"
# create private repo on github.com, then:
git branch -M main
git remote add origin https://github.com/YOUR_USER/facebook-script.git
git push -u origin main
```

### 2. Add repository secrets

GitHub → your repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret | Value |
|--------|--------|
| `TELEGRAM_BOT_TOKEN` | from `.env` |
| `TELEGRAM_CHAT_ID` | from `.env` |
| `FACEBOOK_STORAGE_STATE_B64` | output of the command below |

```bash
cd /Users/teymurnasirli/Documents/facebook-script
source .venv/bin/activate
bash scripts/encode_session.sh
# paste the long base64 string into FACEBOOK_STORAGE_STATE_B64
```

### 3. Trigger a test run

GitHub → **Actions → Marketplace scan → Run workflow**

If it works, you’ll get Telegram messages only when **new** cars appear.  
The schedule (`*/30 * * * *`) keeps running after that.

### 4. When Facebook session dies

1. On your Mac: `python -m src.save_session`
2. Re-run `bash scripts/encode_session.sh`
3. Update the `FACEBOOK_STORAGE_STATE_B64` secret
4. Send `/scan` in Telegram and check for verified Facebook access.

Session caches are scoped to a fingerprint of the secret. Replacing the secret
automatically starts a new cache generation; no manual cache clearing is needed.
Failed or unverified scans do not save session caches. The login helper validates
login cookies before overwriting the local session file. Cookie expiry dates do
not guarantee continued access: Facebook can reject an otherwise unexpired session.

---

## Option B — Always-on Docker (VPS / Railway / Render)

Good if you have a small Linux server (~$4–6/mo).

```bash
# on the server
git clone <your-private-repo> facebook-script
cd facebook-script
# copy .env and storage_state.json onto the server
docker compose up -d --build
```

Or single container:

```bash
docker build -t marketplace-bot .
docker run -d --restart unless-stopped --name marketplace-bot \
  --env-file .env \
  -e FACEBOOK_STORAGE_STATE=/data/storage_state.json \
  -v "$(pwd)/storage_state.json:/data/storage_state.json:ro" \
  -v marketplace-data:/app/data \
  marketplace-bot
```

---

## Trigger a scan from Telegram

In the authorized chat/group:

- `/scan` — start a Marketplace search now on GitHub Actions  
- `/id` — show this chat’s Telegram id (use this for groups)  
- `/help` — command list  

A workflow checks Telegram about every **1 minute**, replies that the scan is starting, then runs the full search (usually 3–10 minutes).

### Use a group
1. Add the bot to the group  
2. In the group send `/id` (or check Actions logs / getUpdates)  
3. Set GitHub secret `TELEGRAM_CHAT_ID` to that group id (example: `-5313360485`)  
4. Optional: multiple chats → `-5313360485,5690531169`  
5. In [@BotFather](https://t.me/BotFather): `/setprivacy` → your bot → **Disable** (so it sees group commands reliably)  
6. Send `/scan` in the group again  

Automatic scans still run on the configured safe interval.

## Local laptop (still works)

```bash
source .venv/bin/activate
python main.py          # loops on the configured interval while the Mac is on
```

For “always on” without cloud, leave that terminal running, or use `launchd` — but the machine must stay awake.
