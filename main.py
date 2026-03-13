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
from fastapi.responses import JSONResponse, HTMLResponse
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

# Import dashboard HTML builder
from dashboard import build_dashboard_html

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
    "status": "Initialising…",
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
    },
    "vinz": {
        "password_hash": bcrypt.hashpw(b"odds2026", bcrypt.gensalt()).decode(),
        "role": "admin",
    },
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
            row.get("bet9ja", "—"),
            row.get("sportybet", "—"),
            row.get("betking", "—"),
            row.get("msport", "—"),
            row.get("betano", "—"),
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
    Merge odds from all 5 bookmakers using ANY available data.
    Uses a unified event index built from all bookmakers, so data shows
    even if some bookmakers return nothing (e.g. geo-blocked).
    """
    BOOKMAKERS = ["bet9ja", "sportybet", "betking", "msport", "betano"]

    # Build a unified event index: key -> {league, event, markets: {market: {sign: {bookmaker: odds}}}}
    unified = {}

    for bk_name in BOOKMAKERS:
        for ev in raw_data.get(bk_name, []):
            league = ev.get("league", "")
            event_name = ev.get("event", "")
            if not event_name:
                continue

            # Try to find existing key via fuzzy match
            matched_key = None
            for existing_key in unified:
                existing_event = unified[existing_key]["event"]
                if fuzzy_match_event(existing_event, event_name):
                    matched_key = existing_key
                    break

            if matched_key is None:
                matched_key = f"{league}|{event_name}"
                unified[matched_key] = {
                    "league": league,
                    "event": event_name,
                    "markets": {},
                }

            # Add this bookmaker's odds into the unified entry
            for market, signs in ev.get("markets", {}).items():
                if market not in unified[matched_key]["markets"]:
                    unified[matched_key]["markets"][market] = {}
                for sign, odds_str in signs.items():
                    if sign not in unified[matched_key]["markets"][market]:
                        unified[matched_key]["markets"][market][sign] = {}
                    try:
                        odds_val = float(str(odds_str).replace(",", "."))
                        unified[matched_key]["markets"][market][sign][bk_name] = odds_val
                    except (ValueError, AttributeError, TypeError):
                        pass

    # Now flatten the unified index into rows
    merged_rows = []

    for key, entry in unified.items():
        league = entry["league"]
        event_name = entry["event"]

        for market, signs in entry["markets"].items():
            for sign, bk_odds in signs.items():
                row = {
                    "league": league,
                    "event": event_name,
                    "market": market,
                    "sign": sign,
                }

                all_odds_values = []

                for bk_name in BOOKMAKERS:
                    if bk_name in bk_odds:
                        row[bk_name] = f"{bk_odds[bk_name]:.2f}"
                        all_odds_values.append(bk_odds[bk_name])
                    else:
                        row[bk_name] = "\u2014"

                # Calculate difference
                if len(all_odds_values) >= 2:
                    row["diff"] = round(max(all_odds_values) - min(all_odds_values), 2)
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
    cache["status"] = "Refreshing…"
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


# ============================================================================
# DASHBOARD HTML ROUTES
# ============================================================================

LOGIN_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Odds Dashboard - Login</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0f1923;color:#e0e0e0;font-family:system-ui,-apple-system,sans-serif;display:flex;justify-content:center;align-items:center;min-height:100vh}
.login-box{background:#1a2634;padding:2rem;border-radius:12px;width:360px;box-shadow:0 4px 24px rgba(0,0,0,.4)}
h1{text-align:center;margin-bottom:1.5rem;color:#4fc3f7}
input{width:100%;padding:.75rem;margin-bottom:1rem;border:1px solid #2d3e50;border-radius:8px;background:#0f1923;color:#e0e0e0;font-size:1rem}
button{width:100%;padding:.75rem;background:#1976d2;color:#fff;border:none;border-radius:8px;font-size:1rem;cursor:pointer}
button:hover{background:#1565c0}
.error{color:#ef5350;text-align:center;margin-bottom:1rem;display:none}
</style></head><body>
<div class="login-box">
<h1>Odds Dashboard</h1>
<div class="error" id="err"></div>
<input type="text" id="user" placeholder="Username" value="vinz">
<input type="password" id="pass" placeholder="Password">
<button onclick="doLogin()">Login</button>
</div>
<script>
async function doLogin(){
  const e=document.getElementById('err');e.style.display='none';
  const r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username:document.getElementById('user').value,password:document.getElementById('pass').value})});
  const d=await r.json();
  if(r.ok){localStorage.setItem('token',d.access_token);window.location.href='/dashboard';}
  else{e.textContent=d.detail||'Login failed';e.style.display='block';}
}
document.getElementById('pass').addEventListener('keypress',e=>{if(e.key==='Enter')doLogin();});
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
async def root():
    """Redirect root to login page."""
    return HTMLResponse('<meta http-equiv="refresh" content="0;url=/login">')


@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """Serve login page."""
    return HTMLResponse(LOGIN_HTML)


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page():
    """Serve main dashboard (requires valid token via JS)."""
    return HTMLResponse(build_dashboard_html(cache))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
