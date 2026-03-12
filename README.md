# Odds Dashboard

Auto-scrapes Bet9ja + SportyBet odds every N minutes and serves a live dark-theme comparison dashboard.

## Features
- Auto-discovers today's top matches from Bet9ja (Playwright/headless Chrome)
- Fetches matching odds from SportyBet API (works from Nigerian IPs)
- Dark-theme sortable dashboard: filter by league, search, sort any column
- Color-coded: green = best odds, diff column shows value gap
- Auto-refreshes every 10 minutes, manual refresh button

## Deploy on Railway (free tier)

1. Go to [railway.app](https://railway.app) and sign up / log in
2. Click **New Project** → **Deploy from GitHub repo**
3. Select `vincenzonova/odds-dashboard`
4. Railway auto-detects the Dockerfile — click **Deploy**
5. Once deployed, go to **Settings → Networking → Generate Domain**
6. Open the generated URL — your dashboard is live!

### Optional env vars (set in Railway Variables tab)
| Variable | Default | Description |
|---|---|---|
| REFRESH_MINUTES | 10 | How often to re-scrape |
| MAX_MATCHES | 40 | Max matches to fetch per cycle |

## Run locally

```bash
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --reload
```

Open http://localhost:8000

## Note on SportyBet geo-blocking
SportyBet's API only responds from Nigerian IPs. Railway's free tier uses US servers — use a Nigerian hosting region or proxy if needed. Bet9ja data always works regardless of location.
