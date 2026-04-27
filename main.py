"""
Odds Dashboard Backend - FastAPI with 5 Bookmakers
Expanded to support: Bet9ja, SportyBet, BetKing, MSport, Betano
"""
import asyncio
import logging
import subprocess
import json
import os
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
# from betking_scraper import scrape_betking  # PAUSED - geo-blocked
from msport_scraper import scrape_msport
from yajuego_scraper import scrape_yajuego
# from betfair_scraper import scrape_betfair  # PAUSED â reducing resource pressure on staging
# from betgr8_scraper import scrape_betgr8  # PAUSED
# from betano_scraper import scrape_betano  # PAUSED - timeout issues

# Import dashboard HTML builder
from dashboard import build_dashboard_html
from debug_routes import router as debug_router
from settings import settings
from middleware import RequestIDMiddleware, LoggingMiddleware

# Import betslip checker with all return calculators
from betslip_checker import (
    check_all_accumulators,
    calculate_bet9ja_returns,
    # calculate_betking_returns,  # PAUSED
    calculate_msport_returns,
    # calculate_betano_returns,  # PAUSED
    _sportybet_formula_fallback,
    calculate_yajuego_returns,
)

# Configuration
SECRET_KEY = settings.secret_key
MAX_MATCHES = settings.max_matches
SCRAPE_DAYS = settings.scrape_days
MSPORT_MIN_DAYS = settings.msport_min_days
BET9JA_MIN_DAYS = settings.bet9ja_min_days
REFRESH_INTERVAL_MINUTES = settings.refresh_interval_minutes
DB_PATH = settings.db_path
SCRAPER_TIMEOUTS = settings.scraper_timeouts

# ââ Betslip Service (separate Railway instance) âââââââââââââââââââââââ
BETSLIP_SERVICE_URL = settings.betslip_service_url
BETSLIP_API_SECRET = settings.betslip_api_secret
DEFAULT_SCRAPER_TIMEOUT = settings.default_scraper_timeout
GATHER_TIMEOUT_SECONDS = settings.gather_timeout_seconds

# --- Merge logic (extracted to merge.py) ---
from merge import (
    TEAM_ALIASES,
    SIGN_SWAP_MAP,
    _normalize_team,
    _team_sim,
    fuzzy_match_event,
    merge_odds,
)

BOOKMAKERS = ["bet9ja", "sportybet", "msport", "yajuego"]

# Global cache with expanded structure for 5 bookmakers
cache = {
    "rows": [],
    "last_updated": None,
    "status": "Not yet refreshed",
    "is_refreshing": False,
    "raw_bet9ja": [],
    "raw_sportybet": [],
    "raw_betking": [],
    "raw_msport": [],
    "raw_betano": [],
    "raw_yajuego": [],
    # "raw_betfair": [],  # PAUSED
    "match_name_map": {},
    "last_errors": [],
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
    "paulo": {
        "password_hash": bcrypt.hashpw(b"paulo2026", bcrypt.gensalt()).decode(),
        "role": "admin",
    },
    "alessandro": {
        "password_hash": bcrypt.hashpw(b"alessandro2026", bcrypt.gensalt()).decode(),
        "role": "admin",
    },
    "fabio": {
        "password_hash": bcrypt.hashpw(b"fabio2026", bcrypt.gensalt()).decode(),
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
            bet9ja_odds REAL,
            sportybet_odds REAL,
            betking_odds REAL,
            msport_odds REAL,
            betano_odds REAL,
            yajuego_odds REAL
        )
    """)
    conn.commit()
    conn.close()


def save_odds_to_db(rows: list):
    """Save current odds snapshot to SQLite database."""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        timestamp = datetime.now().isoformat()
        for row in rows:
            cursor.execute(
                """INSERT INTO odds_history (timestamp, league, event, market, sign,
                    bet9ja_odds, sportybet_odds, betking_odds, msport_odds, betano_odds, yajuego_odds)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    timestamp,
                    row.get("league", ""),
                    row.get("event", ""),
                    row.get("market", ""),
                    row.get("sign", ""),
                    row.get("bet9ja"),
                    row.get("sportybet"),
                    row.get("betking"),
                    row.get("msport"),
                    row.get("betano"),
                    row.get("yajuego"),
                ),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Error saving to DB: {e}")
async def safe_scrape(bookmaker_name: str, scrape_func, max_matches: int = MAX_MATCHES, days: int = None):
    """Safely scrape a bookmaker with error handling and per-scraper timeout."""
    import time as _time
    timeout = SCRAPER_TIMEOUTS.get(bookmaker_name, DEFAULT_SCRAPER_TIMEOUT)
    start_ts = _time.time()
    try:
        result = await asyncio.wait_for(
            scrape_func(max_matches=max_matches) if days is None else scrape_func(max_matches=max_matches, days=days),
            timeout=timeout
        )
        elapsed = round(_time.time() - start_ts, 1)
        logger.warning(f"  [Scraper] {bookmaker_name} completed: {len(result)} events in {elapsed}s (timeout was {timeout}s)")
        diag = {"count": len(result), "elapsed_s": elapsed, "error": None, "timeout_s": timeout, "timestamp": datetime.now().isoformat()}
        cache.setdefault("scraper_diagnostics", {})[bookmaker_name] = diag
        return {
            "bookmaker": bookmaker_name,
            "data": result,
            "error": None,
        }
    except asyncio.TimeoutError:
        elapsed = round(_time.time() - start_ts, 1)
        logger.warning(f"  [Scraper] {bookmaker_name} TIMED OUT after {timeout}s (elapsed: {elapsed}s)")
        diag = {"count": 0, "elapsed_s": elapsed, "error": f"timeout after {timeout}s", "timeout_s": timeout, "timestamp": datetime.now().isoformat()}
        cache.setdefault("scraper_diagnostics", {})[bookmaker_name] = diag
        return {
            "bookmaker": bookmaker_name,
            "data": [],
            "error": f"Scraper timeout after {timeout}s",
        }
    except Exception as e:
        elapsed = round(_time.time() - start_ts, 1)
        logger.error(f"  [Scraper] {bookmaker_name} ERROR after {elapsed}s: {e}")
        diag = {"count": 0, "elapsed_s": elapsed, "error": str(e), "timeout_s": timeout, "timestamp": datetime.now().isoformat()}
        cache.setdefault("scraper_diagnostics", {})[bookmaker_name] = diag
        return {
            "bookmaker": bookmaker_name,
            "data": [],
            "error": str(e),
        }


async def do_refresh():
    """Refresh odds from all 5 bookmakers concurrently."""
    cache["status"] = "Refreshing..."
    cache["is_refreshing"] = True
    try:
        # Scrape all bookmakers in parallel with global timeout
        # Run Bet9ja (API) in parallel with Playwright scrapers run sequentially
        # to avoid memory pressure from 3+ concurrent headless browsers
        async def _run_playwright_scrapers():
            """Run Playwright scrapers sequentially (one browser at a time)."""
            kill_stale_chromium()
            r1 = await safe_scrape("SportyBet", scrape_sportybet, max_matches=MAX_MATCHES, days=SCRAPE_DAYS)
            r2 = await safe_scrape("MSport", scrape_msport, max_matches=MAX_MATCHES, days=max(SCRAPE_DAYS, MSPORT_MIN_DAYS))
            return [r1, r2]

        # API scrapers (Bet9ja, YaJuego) run in parallel with sequential Playwright scrapers
        bet9ja_result, yajuego_result, playwright_results = await asyncio.gather(
            safe_scrape("Bet9ja", scrape_bet9ja, max_matches=MAX_MATCHES, days=max(SCRAPE_DAYS, BET9JA_MIN_DAYS)),
            safe_scrape("YaJuego", scrape_yajuego, max_matches=MAX_MATCHES, days=SCRAPE_DAYS),
            _run_playwright_scrapers(),
        )
        results = [bet9ja_result, yajuego_result] + playwright_results

        # Store raw data
        raw_data = {}
        errors = []
        for result in results:
            bookmaker = result["bookmaker"]
            if result["error"]:
                errors.append(f"{bookmaker}: {result['error']}")
            raw_data[bookmaker.lower()] = result.get("data", [])

        cache["raw_bet9ja"] = raw_data.get("bet9ja", [])
        cache["raw_sportybet"] = raw_data.get("sportybet", [])
        # cache["raw_betking"] = raw_data.get("betking", [])  # PAUSED
        cache["raw_msport"] = raw_data.get("msport", [])
        cache["raw_yajuego"] = raw_data.get("yajuego", [])
        # cache["raw_betano"] = raw_data.get("betano", [])  # PAUSED

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
            cache["last_errors"] = errors

    except asyncio.TimeoutError:
        cache["status"] = f"Error: Refresh timeout after {GATHER_TIMEOUT_SECONDS}s"
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
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(do_refresh, "interval", minutes=REFRESH_INTERVAL_MINUTES)
    scheduler.start()
    # Initial refresh in background (non-blocking so server starts immediately)
    asyncio.create_task(do_refresh())
    yield
    # Shutdown
    if scheduler:
        scheduler.shutdown()


app = FastAPI(
    title="Odds Dashboard API",
    description="Multi-bookmaker odds comparison with betslip analysis",
    lifespan=lifespan,
)

app.add_middleware(LoggingMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(debug_router)

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

def _filter_rows_by_date(rows, days):
    """Filter merged rows to only include events within 'days' from now."""
    cutoff = datetime.now() + timedelta(days=days)
    filtered = []
    for row in rows:
        st = row.get("start_time", "")
        if not st:
            filtered.append(row)
            continue
        try:
            event_dt = None
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%SZ"):
                try:
                    event_dt = datetime.strptime(str(st)[:19], fmt[:min(len(fmt), 19)])
                    break
                except ValueError:
                    continue
            if event_dt is None or event_dt <= cutoff:
                filtered.append(row)
        except Exception:
            filtered.append(row)
    return filtered


@app.get("/api/odds")
async def get_odds(current_user: str = Depends(get_current_user)):
    """Get all merged odds from 5 bookmakers, filtered by SCRAPE_DAYS setting."""
    filtered = _filter_rows_by_date(cache["rows"], SCRAPE_DAYS)
    return JSONResponse({
        "rows": filtered,
        "last_updated": cache["last_updated"],
        "status": cache["status"],
        "bookmakers": ["Bet9ja", "SportyBet", "BetKing", "MSport", "Betano"],
        "total_events": len(filtered),
    })


@app.get("/api/odds/by-league/{league}")
async def get_odds_by_league(league: str, current_user: str = Depends(get_current_user)):
    """Get odds filtered by league."""
    all_rows = _filter_rows_by_date(cache["rows"], SCRAPE_DAYS)
    filtered = [row for row in all_rows if row.get("league", "").lower() == league.lower()]
    return JSONResponse({
        "league": league,
        "rows": filtered,
        "count": len(filtered),
    })


@app.get("/api/errors")
async def get_errors(current_user: str = Depends(get_current_user)):
    """Get last scraper errors for debugging."""
    return JSONResponse({
        "errors": cache.get("last_errors", []),
        "status": cache["status"],
        "last_updated": cache["last_updated"],
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


@app.get("/api/settings")
async def get_settings(current_user: str = Depends(get_current_user)):
    """Get current dashboard settings."""
    global SCRAPE_DAYS
    return JSONResponse({"scrape_days": SCRAPE_DAYS})


@app.post("/api/settings")
async def update_settings(request: Request, current_user: str = Depends(get_current_user)):
    """Update dashboard settings."""
    global SCRAPE_DAYS
    body = await request.json()
    new_days = body.get("scrape_days")
    if new_days is not None:
        new_days = int(new_days)
        if 1 <= new_days <= 10:
            SCRAPE_DAYS = new_days
            return JSONResponse({"scrape_days": SCRAPE_DAYS, "message": f"Scrape range updated to {SCRAPE_DAYS} days"})
        else:
            raise HTTPException(status_code=400, detail="scrape_days must be between 1 and 10")
    raise HTTPException(status_code=400, detail="No valid settings provided")


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
        bookmakers = body.get("bookmakers", ["bet9ja", "sportybet", "msport", "yajuego"])
        if not selections:
            raise HTTPException(status_code=400, detail="No selections provided")

        # Calculate returns for selected bookmakers
        all_calcs = {
            "bet9ja": lambda: calculate_bet9ja_returns(selections, stake),
            "sportybet": lambda: _sportybet_formula_fallback(selections, stake),
            "msport": lambda: calculate_msport_returns(selections, stake),
            "yajuego": lambda: calculate_yajuego_returns(selections, stake),
        }
        result = {}
        for bm in bookmakers:
            if bm in all_calcs:
                result[bm] = all_calcs[bm]()
        result["selections"] = selections
        result["size"] = len(selections)
        result["stake"] = stake
        return JSONResponse(result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))




@app.post("/api/live-comparison")
async def api_live_comparison(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """
    Live betslip comparison â proxies to the separate betslip service.
    The betslip service runs Playwright on its own Railway instance to
    avoid resource contention with the main odds scraper.

    Falls back to formula-based calculation if the betslip service is
    not configured or unreachable.
    """
    try:
        body = await request.json()
        selections = body.get("selections", [])
        stake = body.get("stake", 100.0)
        bookmakers = body.get("bookmakers", ["bet9ja", "sportybet", "msport", "yajuego"])

        if not selections:
            raise HTTPException(status_code=400, detail="No selections provided")

        # If betslip service URL is configured, call the external service
        if BETSLIP_SERVICE_URL:
            import httpx
            async with httpx.AsyncClient(timeout=180.0) as client:
                resp = await client.post(
                    f"{BETSLIP_SERVICE_URL}/api/scrape-betslips",
                    json={
                        "selections": selections,
                        "stake": stake,
                        "bookmakers": bookmakers,
                        "secret": BETSLIP_API_SECRET,
                    },
                )
                if resp.status_code == 200:
                    betslip_data = resp.json()
                    betslip_results = betslip_data.get("results", betslip_data)
                    # Supplement failed bookmakers with formula fallback
                    fallback_calcs = {
                        "bet9ja": lambda: calculate_bet9ja_returns(selections, stake),
                        "sportybet": lambda: _sportybet_formula_fallback(selections, stake),
                        "msport": lambda: calculate_msport_returns(selections, stake),
                        "yajuego": lambda: calculate_yajuego_returns(selections, stake),
                    }
                    for bm in bookmakers:
                        bm_result = betslip_results.get(bm, {})
                        if not bm_result.get("potential_win"):
                            if bm in fallback_calcs:
                                betslip_results[bm] = fallback_calcs[bm]()
                                betslip_results[bm]["source"] = "formula_fallback"
                    if "results" in betslip_data:
                        betslip_data["results"] = betslip_results
                    if "selections" not in betslip_data:
                        betslip_data["selections"] = selections
                    betslip_data["size"] = len(selections)
                    betslip_data["stake"] = stake
                    return JSONResponse(betslip_data)
                else:
                    logger.info(f"[live-comparison] Betslip service returned {resp.status_code}: {resp.text}")
                    # Fall through to formula fallback

        # Fallback: formula-based calculation (same as custom-comparison)
        logger.info("[live-comparison] Betslip service not available, using formula fallback")
        all_calcs = {
            "bet9ja": lambda: calculate_bet9ja_returns(selections, stake),
            "sportybet": lambda: _sportybet_formula_fallback(selections, stake),
            "msport": lambda: calculate_msport_returns(selections, stake),
            "yajuego": lambda: calculate_yajuego_returns(selections, stake),
        }
        result = {}
        for bm in bookmakers:
            if bm in all_calcs:
                result[bm] = all_calcs[bm]()
        result["selections"] = selections
        result["size"] = len(selections)
        result["stake"] = stake
        result["source"] = "formula_fallback"
        return JSONResponse(result)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[live-comparison] Live comparison failed: {e}")
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
<html><head><meta charset="utf-8"><link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAzMiAzMiI+PHJlY3Qgd2lkdGg9IjMyIiBoZWlnaHQ9IjMyIiByeD0iNiIgZmlsbD0iIzYzNjZmMSIvPjxwYXRoIGQ9Ik0xOCA0TDEwIDE4aDVsLTMgMTAgMTAtMTRoLTV6IiBmaWxsPSIjZmZmIi8+PC9zdmc+"/><title>Odds Dashboard - Login</title>
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


@app.get("/debug/scraper-diagnostics")
async def scraper_diagnostics():
    """Public endpoint showing per-scraper timing, counts, and errors."""
    diag = cache.get("scraper_diagnostics", {})
    raw_counts = {
        "bet9ja": len(cache.get("raw_bet9ja", [])),
        "sportybet": len(cache.get("raw_sportybet", [])),
        "msport": len(cache.get("raw_msport", [])),
        "yajuego": len(cache.get("raw_yajuego", [])),
    }
    return JSONResponse({
        "scraper_diagnostics": diag,
        "raw_event_counts": raw_counts,
        "merged_row_count": len(cache.get("rows", [])),
        "last_errors": cache.get("last_errors", []),
        "status": cache.get("status", "unknown"),
        "last_updated": cache.get("last_updated", "never"),
        "config": {
            "SCRAPE_DAYS": SCRAPE_DAYS,
            "SCRAPER_TIMEOUTS": SCRAPER_TIMEOUTS,
            "GATHER_TIMEOUT_SECONDS": GATHER_TIMEOUT_SECONDS,
            "MAX_MATCHES": MAX_MATCHES,
        }
    })



if __name__ == "__main__":
    import uvicorn

logger = logging.getLogger(__name__)


def kill_stale_chromium():
    """Kill any lingering Chromium/headless_shell processes to prevent thread exhaustion."""
    try:
        subprocess.run(["pkill", "-f", "headless_shell"], capture_output=True, timeout=5)
        subprocess.run(["pkill", "-f", "chromium"], capture_output=True, timeout=5)
        logger.info("Cleaned up stale Chromium processes")
    except Exception as e:
        logger.warning(f"Chromium cleanup failed: {e}")


    uvicorn.run(app, host="0.0.0.0", port=8000)
