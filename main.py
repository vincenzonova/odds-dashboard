"""
Odds Dashboard — FastAPI Backend
---------------------------------
• Scrapes Bet9ja (Playwright) + SportyBet (API) on startup and every N minutes
• Serves a live JSON API at  GET /api/odds
• Serves the HTML dashboard at  GET /
"""

import asyncio
import os
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bet9ja_scraper import scrape_bet9ja
from sportybet_scraper import scrape_sportybet
from dashboard import build_dashboard_html

# ── Config ────────────────────────────────────────────────
REFRESH_MINUTES = int(os.getenv("REFRESH_MINUTES", "10"))
MAX_MATCHES     = int(os.getenv("MAX_MATCHES", "40"))

# ── In-memory cache ───────────────────────────────────────
cache: dict = {
    "rows":         [],      # list of comparison rows
    "last_updated": None,
    "status":       "Initialising…",
    "is_refreshing": False,
}

scheduler = AsyncIOScheduler()


# ── Scrape + merge logic ──────────────────────────────────

def merge_odds(bet9ja_matches: list[dict], sportybet_map: dict[str, dict]) -> list[dict]:
    """
    Combine Bet9ja and SportyBet odds into comparison rows.
    Each row = one market/sign combination per match.
    """
    MARKETS = [
        ("1X2",    ["1", "X", "2"]),
        ("O/U 2.5",["Over", "Under"]),
        ("O/U 1.5",["Over"]),
        ("GG/NG",  ["GG"]),
    ]

    rows = []
    for match in bet9ja_matches:
        event  = match["event"]
        league = match["league"]
        b9_odds = match.get("odds", {})
        sb_odds = sportybet_map.get(event, {})

        for market, signs in MARKETS:
            for sign in signs:
                b9_val = b9_odds.get(market, {}).get(sign, "")
                sb_val = sb_odds.get(market, {}).get(sign, "")

                if not b9_val and not sb_val:
                    continue  # skip if neither bookie has it

                # Compute numeric diff
                diff = None
                try:
                    b9_f  = float(b9_val)
                    sb_f  = float(sb_val)
                    diff = round(sb_f - b9_f, 3)
                except (ValueError, TypeError):
                    pass

                rows.append({
                    "league":    league,
                    "event":     event,
                    "market":    market,
                    "sign":      sign,
                    "bet9ja":    b9_val or "—",
                    "sportybet": sb_val or "—",
                    "diff":      diff,
                })

    # Sort: biggest positive diff first (SportyBet better), then by league
    rows.sort(key=lambda r: (-(r["diff"] or 0), r["league"], r["event"]))
    return rows


async def do_refresh():
    if cache["is_refreshing"]:
        print("[Scheduler] Already refreshing, skipping.")
        return

    cache["is_refreshing"] = True
    cache["status"] = "Refreshing…"
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Starting refresh...")

    try:
        # Bet9ja (Playwright)
        bet9ja_matches = await scrape_bet9ja(max_matches=MAX_MATCHES)

        if not bet9ja_matches:
            cache["status"] = "No matches found from Bet9ja"
            return

        # SportyBet (API)
        sportybet_map = scrape_sportybet(bet9ja_matches)

        # Merge
        rows = merge_odds(bet9ja_matches, sportybet_map)

        cache["rows"]         = rows
        cache["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cache["status"]       = f"OK — {len(rows)} rows, {len(bet9ja_matches)} matches"
        print(f"[Refresh] Done: {len(rows)} rows from {len(bet9ja_matches)} matches")

    except Exception as e:
        cache["status"] = f"Error: {e}"
        print(f"[Refresh] ERROR: {e}")
    finally:
        cache["is_refreshing"] = False


# ── App lifecycle ─────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initial scrape + schedule
    asyncio.create_task(do_refresh())
    scheduler.add_job(do_refresh, "interval", minutes=REFRESH_MINUTES)
    scheduler.start()
    yield
    # Shutdown
    scheduler.shutdown()


app = FastAPI(title="Odds Dashboard", lifespan=lifespan)


# ── Routes ────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return build_dashboard_html(cache)


@app.get("/api/odds")
async def api_odds():
    return JSONResponse({
        "last_updated": cache["last_updated"],
        "status":       cache["status"],
        "count":        len(cache["rows"]),
        "rows":         cache["rows"],
    })


@app.get("/api/refresh")
async def trigger_refresh():
    """Manually trigger a refresh (useful for testing)."""
    asyncio.create_task(do_refresh())
    return {"message": "Refresh triggered"}


@app.get("/health")
async def health():
    return {"status": "ok", "last_updated": cache["last_updated"]}
