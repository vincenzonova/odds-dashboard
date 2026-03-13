"""
Odds Dashboard — FastAPI Backend
---------------------------------
• Scrapes Bet9ja (JSON API) + SportyBet (Playwright) on startup and every N minutes
• Serves a live JSON API at GET /api/odds
• Serves the HTML dashboard at GET /
"""
import asyncio
import os
from datetime import datetime
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bet9ja_scraper import scrape_bet9ja
from sportybet_scraper import scrape_sportybet, fuzzy_match
from dashboard import build_dashboard_html

# ── Config ────────────────────────────────────────────────────────────
REFRESH_MINUTES = int(os.getenv("REFRESH_MINUTES", "10"))
MAX_MATCHES    = int(os.getenv("MAX_MATCHES", "40"))

# ── In-memory cache ────────────────────────────────────────────────────
cache: dict = {
    "rows": [],
    "last_updated": None,
    "status": "Initialising\u2026",
    "is_refreshing": False,
}
scheduler = AsyncIOScheduler()


def _build_sportybet_map(bet9ja_matches: list[dict], sb_events: list[dict]) -> dict:
    """Fuzzy-match SportyBet events to Bet9ja events, return {event_name: odds}."""
    sb_map = {}
    for b9 in bet9ja_matches:
        event_name = b9["event"]
        for sb in sb_events:
            if fuzzy_match(event_name, sb["event"]):
                sb_map[event_name] = sb.get("odds", {})
                break
        else:
            sb_map[event_name] = {}
    return sb_map


def merge_odds(bet9ja_matches: list[dict], sportybet_map: dict) -> list[dict]:
    MARKETS = [
        ("1X2",           ["1", "X", "2"]),
        ("O/U 2.5",       ["Over", "Under"]),
        ("Double Chance", ["1X", "12", "X2"]),
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
                    continue
                diff = None
                try:
                    b9_f = float(b9_val)
                    sb_f = float(sb_val)
                    diff  = round(sb_f - b9_f, 3)
                except (ValueError, TypeError):
                    pass
                rows.append({
                    "league":    league,
                    "event":     event,
                    "market":    market,
                    "sign":      sign,
                    "bet9ja":    b9_val or "\u2014",
                    "sportybet": sb_val or "\u2014",
                    "diff":      diff,
                })
    rows.sort(key=lambda r: (-(r["diff"] or 0), r["league"], r["event"]))
    return rows


def _sb_only_rows(sb_events: list[dict]) -> list[dict]:
    """Build rows from SportyBet data alone (when Bet9ja is unavailable)."""
    MARKETS = [("1X2", ["1", "X", "2"]), ("O/U 2.5", ["Over", "Under"])]
    rows = []
    for ev in sb_events:
        for market, signs in MARKETS:
            for sign in signs:
                sb_val = ev.get("odds", {}).get(market, {}).get(sign, "")
                if not sb_val:
                    continue
                rows.append({
                    "league":    ev.get("league", ""),
                    "event":     ev["event"],
                    "market":    market,
                    "sign":      sign,
                    "bet9ja":    "\u2014",
                    "sportybet": sb_val,
                    "diff":      None,
                })
    return rows


def _b9_only_rows(b9_matches: list[dict]) -> list[dict]:
    """Build rows from Bet9ja data alone (when SportyBet is unavailable)."""
    MARKETS = [("1X2", ["1", "X", "2"]), ("O/U 2.5", ["Over", "Under"]), ("Double Chance", ["1X", "12", "X2"])]
    rows = []
    for match in b9_matches:
        for market, signs in MARKETS:
            for sign in signs:
                b9_val = match.get("odds", {}).get(market, {}).get(sign, "")
                if not b9_val:
                    continue
                rows.append({
                    "league":    match.get("league", ""),
                    "event":     match["event"],
                    "market":    market,
                    "sign":      sign,
                    "bet9ja":    b9_val,
                    "sportybet": "\u2014",
                    "diff":      None,
                })
    return rows


async def do_refresh():
    if cache["is_refreshing"]:
        print("[Scheduler] Already refreshing, skipping.")
        return
    cache["is_refreshing"] = True
    cache["status"] = "Refreshing\u2026"
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Starting refresh...")

    try:
        # Bet9ja (JSON API) \u2014 may fail due to geo-blocking
        bet9ja_matches = []
        try:
            bet9ja_matches = await scrape_bet9ja(max_matches=MAX_MATCHES)
        except Exception as e:
            print(f"  [Bet9ja] Scraper failed: {e}")

        # SportyBet (Playwright) \u2014 always attempt
        sb_events = []
        try:
            sb_events = await scrape_sportybet(max_matches=MAX_MATCHES)
        except Exception as e:
            print(f"  [SportyBet] Scraper failed: {e}")

        if bet9ja_matches and sb_events:
            # Full comparison mode
            sportybet_map = _build_sportybet_map(bet9ja_matches, sb_events)
            rows = merge_odds(bet9ja_matches, sportybet_map)
            cache["status"] = f"OK \u2014 {len(rows)} rows, {len(bet9ja_matches)} Bet9ja + {len(sb_events)} SportyBet"
        elif bet9ja_matches:
            # Bet9ja only
            rows = _b9_only_rows(bet9ja_matches)
            cache["status"] = f"Bet9ja only \u2014 {len(rows)} rows (SportyBet unavailable)"
        elif sb_events:
            # SportyBet only
            rows = _sb_only_rows(sb_events)
            cache["status"] = f"SportyBet only \u2014 {len(rows)} rows (Bet9ja unavailable)"
        else:
            rows = []
            cache["status"] = "No data from either source"

        cache["rows"]         = rows
        cache["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[Refresh] Done: {len(rows)} rows")

    except Exception as e:
        cache["status"] = f"Error: {e}"
        print(f"[Refresh] ERROR: {e}")
    finally:
        cache["is_refreshing"] = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(do_refresh())
    scheduler.add_job(do_refresh, "interval", minutes=REFRESH_MINUTES)
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(title="Odds Dashboard", lifespan=lifespan)


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
    asyncio.create_task(do_refresh())
    return {"message": "Refresh triggered"}


@app.get("/health")
async def health():
    return {"status": "ok", "last_updated": cache["last_updated"]}
