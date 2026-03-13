"""
Odds Dashboard Backend - FastAPI with 5 Bookmakers
Expanded to support: Bet9ja, SportyBet, BetKing, MSport, Betano
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from functools import wraps

from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import jwt
import bcrypt

# Import scrapers for all 5 bookmakers
from bet9ja_scraper import scrape_bet9ja
from sportybet_scraper import scrape_sportybet
from betking_scraper import scrape_betking
from msport_scraper import scrape_msport
from betano_scraper import scrape_betano

# Import betslip checker with all return calculators
from betslip_checker import (
    check_all_accumulators,
    calculate_bet9ja_returns,
    calculate_betking_returns,
    calculate_msport_returns,
    calculate_betano_returns,
    _sportybet_formula_fallback,
)

# Configuration
SECRET_KEY = "your-secret-key-change-in-production"
MAX_MATCHES = 100
REFRESH_INTERVAL_MINUTES = 5
DB_PATH = "odds_history.db"

# Global cache with expanded structure for 5 bookmakers
cache = {
    "rows": [],
    "last_updated": None,
    "status": "Initialisingâ¦",
    "is_refreshing": False,
    "accumulators": [],
    "raw_bet9ja": [],
    "raw_sportybet": [],
    "raw_betking": [],
    "raw_msport": [],
    "raw_betano": [],
    "match_name_map": {},
}

# Dummy user database (replace with real DB in production)
users = {
    "admin": {
        "password_hash": bcrypt.hashpw(b"admin123", bcrypt.gensalt()).decode(),
        "role": "admin",
    }
}

scheduler = None


def init_db():
    """Initialize SQLite database with schema for all 5 bookmakers."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS odds_history (
            id INTEGER PRIMARY KEY,
            timestamp TEXT,
            league TEXT,
            event TEXT,
            market TEXT,
            sign TEXT,
            bet9ja TEXT,
            sportybet TEXT,
            betking TEXT,
            msport TEXT,
            betano TEXT,
            diff REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT,
            role TEXT
        )
    """)

    conn.commit()
    conn.close()


def save_odds_to_db(rows: list):
    """Save merged odds to database with all 5 bookmakers."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    timestamp = datetime.now().isoformat()

    for row in rows:
        cursor.execute("""
            INSERT INTO odds_history
            (timestamp, league, event, market, sign, bet9ja, sportybet, betking, msport, betano, diff)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp,
            row.get("league", ""),
            row.get("event", ""),
            row.get("market", ""),
            row.get("sign", ""),
            row.get("bet9ja", "â"),
            row.get("sportybet", "â"),
            row.get("betking", "â"),
            row.get("msport", "â"),
            row.get("betano", "â"),
            row.get("diff", 0.0),
        ))

    conn.commit()
    conn.close()


def fuzzy_match_event(bet9ja_event: str, other_event: str, threshold: float = 0.7) -> bool:
    """Simple fuzzy matching for event names across bookmakers."""
    bet9ja_lower = bet9ja_event.lower().strip()
    other_lower = other_event.lower().strip()

    if bet9ja_lower == other_lower:
        return True

    # Extract team names (simple approach)
    bet9ja_parts = set(bet9ja_lower.split())
    other_parts = set(other_lower.split())

    if len(bet9ja_parts) == 0 or len(other_parts) == 0:
        return False

    overlap = len(bet9ja_parts & other_parts) / max(len(bet9ja_parts), len(other_parts))
    return overlap >= threshold


def merge_odds(raw_data: dict) -> list:
    """
    Merge odds from all 5 bookmakers using Bet9ja as primary reference.
    Returns list of dicts with odds from all available bookmakers.
    """
    bet9ja_events = {f"{e['league']}|{e['event']}": e for e in raw_data["bet9ja"]}

    merged_rows = []

    for bet9ja_key, bet9ja_event in bet9ja_events.items():
        league, event_name = bet9ja_key.split("|")

        for market in bet9ja_event.get("markets", {}).keys():
            for sign, odds_str in bet9ja_event["markets"][market].items():
                try:
                    bet9ja_odds = float(odds_str.replace(",", "."))
                except (ValueError, AttributeError):
                    continue

                row = {
                    "league": league,
                    "event": event_name,
                    "market": market,
                    "sign": sign,
                    "bet9ja": f"{bet9ja_odds:.2f}",
                }

                all_odds_values = [bet9ja_odds]

                # Find matching odds from SportyBet
                for sb_event in raw_data["sportybet"]:
                    if fuzzy_match_event(event_name, sb_event.get("event", "")):
                        sb_markets = sb_event.get("markets", {})
                        if market in sb_markets and sign in sb_markets[market]:
                            try:
                                sb_odds = float(sb_markets[market][sign].replace(",", "."))
                                row["sportybet"] = f"{sb_odds:.2f}"
                                all_odds_values.append(sb_odds)
                            except (ValueError, AttributeError):
                                row["sportybet"] = "â"
                        break

                # Find matching odds from BetKing
                for bk_event in raw_data["betking"]:
                    if fuzzy_match_event(event_name, bk_event.get("event", "")):
                        bk_markets = bk_event.get("markets", {})
                        if market in bk_markets and sign in bk_markets[market]:
                            try:
                                bk_odds = float(bk_markets[market][sign].replace(",", "."))
                                row["betking"] = f"{bk_odds:.2f}"
                                all_odds_values.append(bk_odds)
                            except (ValueError, AttributeError):
                                row["betking"] = "â"
                        break

                # Find matching odds from MSport
                for ms_event in raw_data["msport"]:
                    if fuzzy_match_event(event_name, ms_event.get("event", "")):
                        ms_markets = ms_event.get("markets", {})
                        if market in ms_markets and sign in ms_markets[market]:
                            try:
                                ms_odds = float(ms_markets[market][sign].replace(",", "."))
                                row["msport"] = f"{ms_odds:.2f}"
                                all_odds_values.append(ms_odds)
                            except (ValueError, AttributeError):
                                row["msport"] = "â"
                        break

                # Find matching odds from Betano
                for bn_event in raw_data["betano"]:
                    if fuzzy_match_event(event_name, bn_event.get("event", "")):
                        bn_markets = bn_event.get("markets", {})
                        if market in bn_markets and sign in bn_markets[market]:
                            try:
                                bn_odds = float(bn_markets[market][sign].replace(",", "."))
                                row["betano"] = f"{bn_odds:.2f}"
                                all_odds_values.append(bn_odds)
                            except (ValueError, AttributeError):
                                row["betano"] = "â"
                        break

                # Fill missing bookmakers with "â"
                for bookmaker in ["sportybet", "betking", "msport", "betano"]:
                    if bookmaker not in row:
                        row[bookmaker] = "â"

                # Calculate difference
                numeric_odds = [v for v in all_odds_values if isinstance(v, float)]
                if numeric_odds:
                    row["diff"] = max(numeric_odds) - min(numeric_odds)
                else:
                    row["diff"] = 0.0

                merged_rows.append(row)

    return merged_rows


async def safe_scrape(bookmaker_name: str, scrape_func, max_matches: int = MAX_MATCHES):
    """Safely scrape a bookmaker with error handling."""
    try:
        result = await scrape_func(max_matches=max_matches)
        return {
            "bookmaker": bookmaker_name,
            "data": result,
            "error": None,
        }
    except Exception as e:
        return {
            "bookmaker": bookmaker_name,
            "data": [],
            "error": str(e),
        }


async def do_refresh():
    """Refresh odds from all 5 bookmakers concurrently."""
    cache["status"] = "Refreshingâ¦"
    cache["is_refreshing"] = True

    try:
        # Scrape all bookmakers in parallel
        results = await asyncio.gather(
            safe_scrape("Bet9ja", scrape_bet9ja, max_matches=MAX_MATCHES),
            safe_scrape("SportyBet", scrape_sportybet, max_matches=MAX_MATCHES),
            safe_scrape("BetKing", scrape_betking, max_matches=MAX_MATCHES),
            safe_scrape("MSport", scrape_msport, max_matches=MAX_MATCHES),
            safe_scrape("Betano", scrape_betano, max_matches=MAX_MATCHES),
        )

        # Store raw data
        raw_data = {}
        errors = []

        for result in results:
            bookmaker = result["bookmaker"]
            if result["error"]:
                errors.append(f"{bookmaker}: {result['error']}")
                raw_data[bookmaker.lower()] = []
            else:
                raw_data[bookmaker.lower()] = result["data"]

        cache["raw_bet9ja"] = raw_data["bet9ja"]
        cache["raw_sportybet"] = raw_data["sportybet"]
        cache["raw_betking"] = raw_data["betking"]
        cache["raw_msport"] = raw_data["msport"]
        cache["raw_betano"] = raw_data["betano"]

        # Merge odds from all bookmakers
        cache["rows"] = merge_odds(raw_data)

        # Calculate accumulators
        cache["accumulators"] = await compute_accumulators_with_betslip()

        # Save to database
        save_odds_to_db(cache["rows"])

        cache["last_updated"] = datetime.now().isoformat()
        cache["status"] = f"Updated at {datetime.now().strftime('%H:%M:%S')}"

        if errors:
            cache["status"] += f" ({len(errors)} errors)"

    except Exception as e:
        cache["status"] = f"Error: {str(e)}"

    finally:
        cache["is_refreshing"] = False


async def compute_accumulators_with_betslip() -> list:
    """
    Compute best accumulators using betslip data.
    Returns results for all 5 bookmakers.
    """
    try:
        accumulators = check_all_accumulators(cache["rows"], cache.get("raw_bet9ja", []))
        return accumulators
    except Exception:
        return []


def token_required(f):
    """Decorator to require valid JWT token."""
    @wraps(f)
    async def decorated(*args, **kwargs):
        token = None
        request = None

        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break

        if not request:
            raise HTTPException(status_code=401, detail="Missing request context")

        auth_header = request.headers.get("Authorization")
        if not auth_header:
            raise HTTPException(status_code=401, detail="Missing authorization header")

        try:
            token = auth_header.split(" ")[1]
            payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            current_user = payload.get("sub")
        except (IndexError, jwt.InvalidTokenError):
            raise HTTPException(status_code=401, detail="Invalid token")

        return await f(current_user, *args, **kwargs)

    return decorated


def get_current_user(request: Request) -> str:
    """Extract current user from JWT token."""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    try:
        token = auth_header.split(" ")[1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except (IndexError, jwt.InvalidTokenError):
        raise HTTPException(status_code=401, detail="Invalid token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan context manager for startup/shutdown."""
    global scheduler

    # Startup
    init_db()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(do_refresh, "interval", minutes=REFRESH_INTERVAL_MINUTES)
    scheduler.start()

    # Initial refresh
    await do_refresh()

    yield

    # Shutdown
    if scheduler:
        scheduler.shutdown()


app = FastAPI(
    title="Odds Dashboard API",
    description="Multi-bookmaker odds comparison with betslip analysis",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# AUTHENTICATION ENDPOINTS
# ============================================================================

@app.post("/api/auth/login")
async def login(request: Request):
    """Login and receive JWT token."""
    try:
        body = await request.json()
        username = body.get("username")
        password = body.get("password")

        if not username or not password:
            raise HTTPException(status_code=400, detail="Missing credentials")

        user = users.get(username)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
            raise HTTPException(status_code=401, detail="Invalid username or password")

        token = jwt.encode(
            {"sub": username, "exp": datetime.utcnow() + timedelta(hours=24)},
            SECRET_KEY,
            algorithm="HS256",
        )

        return JSONResponse({"access_token": token, "token_type": "bearer"})

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/auth/logout")
async def logout(current_user: str = Depends(get_current_user)):
    """Logout (token invalidation handled client-side)."""
    return JSONResponse({"message": "Logged out successfully"})


# ============================================================================
# ODDS ENDPOINTS
# ============================================================================

@app.get("/api/odds")
async def get_odds(current_user: str = Depends(get_current_user)):
    """Get all merged odds from 5 bookmakers."""
    return JSONResponse({
        "rows": cache["rows"],
        "last_updated": cache["last_updated"],
        "status": cache["status"],
        "bookmakers": ["Bet9ja", "SportyBet", "BetKing", "MSport", "Betano"],
        "total_events": len(cache["rows"]),
    })


@app.get("/api/odds/by-league/{league}")
async def get_odds_by_league(league: str, current_user: str = Depends(get_current_user)):
    """Get odds filtered by league."""
    filtered = [row for row in cache["rows"] if row.get("league", "").lower() == league.lower()]
    return JSONResponse({
        "league": league,
        "rows": filtered,
        "count": len(filtered),
    })


@app.get("/api/status")
async def get_status(current_user: str = Depends(get_current_user)):
    """Get dashboard status and refresh info."""
    return JSONResponse({
        "status": cache["status"],
        "is_refreshing": cache["is_refreshing"],
        "last_updated": cache["last_updated"],
        "total_rows": len(cache["rows"]),
    })


@app.post("/api/refresh")
async def manual_refresh(current_user: str = Depends(get_current_user)):
    """Manually trigger a refresh of all odds."""
    if cache["is_refreshing"]:
        raise HTTPException(status_code=429, detail="Refresh already in progress")

    asyncio.create_task(do_refresh())
    return JSONResponse({"message": "Refresh started"})


# ============================================================================
# ACCUMULATOR & BETSLIP ENDPOINTS
# ============================================================================

@app.post("/api/custom-comparison")
async def api_custom_comparison(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """
    Generate comparison for user-selected odds from dashboard checkboxes.
    Expected body:
    {
        "selections": [
            {"event": "Arsenal - Everton", "sign": "1", "market": "1X2", "bet9ja": "1.50", ...},
            ...
        ],
        "stake": 100
    }
    """
    try:
        body = await request.json()
        selections = body.get("selections", [])
        stake = body.get("stake", 100.0)

        if not selections:
            raise HTTPException(status_code=400, detail="No selections provided")

        # Calculate returns for all 5 bookmakers
        result = {
            "bet9ja": calculate_bet9ja_returns(selections, stake),
            "sportybet": _sportybet_formula_fallback(selections, stake),
            "betking": calculate_betking_returns(selections, stake),
            "msport": calculate_msport_returns(selections, stake),
            "betano": calculate_betano_returns(selections, stake),
            "selections": selections,
            "size": len(selections),
            "stake": stake,
        }

        return JSONResponse(result)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/accumulators")
async def get_accumulators(current_user: str = Depends(get_current_user)):
    """Get computed best accumulators with returns for all bookmakers."""
    return JSONResponse({
        "accumulators": cache["accumulators"],
        "last_updated": cache["last_updated"],
    })


# ============================================================================
# HEALTH & UTILITY ENDPOINTS
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint (no auth required)."""
    return JSONResponse({
        "status": "healthy",
        "last_updated": cache["last_updated"],
        "is_refreshing": cache["is_refreshing"],
    })


@app.get("/api/bookmakers")
async def get_bookmakers(current_user: str = Depends(get_current_user)):
    """Get list of supported bookmakers."""
    return JSONResponse({
        "bookmakers": [
            {"name": "Bet9ja", "code": "bet9ja"},
            {"name": "SportyBet", "code": "sportybet"},
            {"name": "BetKing", "code": "betking"},
            {"name": "MSport", "code": "msport"},
            {"name": "Betano", "code": "betano"},
        ]
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
