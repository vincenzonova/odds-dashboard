"""
Odds Dashboard — FastAPI Backend with Auth, DB, and Accumulators
------------------------------------------------------------------
• Scrapes Bet9ja (JSON API) + SportyBet (Playwright) on startup and every N minutes
• Session-based authentication with login system
• SQLite database for historical odds tracking
• Accumulator betting calculations with bonuses
• Serves a live JSON API at GET /api/odds
• Serves the HTML dashboard at GET /
"""
import asyncio
import os
import sqlite3
import hashlib
import secrets
import random
import re
from datetime import datetime, timedelta
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from playwright.async_api import async_playwright

from bet9ja_scraper import scrape_bet9ja
from sportybet_scraper import scrape_sportybet, fuzzy_match
from dashboard import build_dashboard_html
from betslip_checker import (
    check_all_accumulators,
    calculate_bet9ja_returns,
    _sportybet_formula_fallback,
)

# ── Config ────────────────────────────────────────────────────────
REFRESH_MINUTES = int(os.getenv("REFRESH_MINUTES", "10"))
MAX_MATCHES    = int(os.getenv("MAX_MATCHES", "40"))
DB_PATH        = os.getenv("DB_PATH", "/tmp/odds_history.db")

# Auth credentials
AUTH_USERNAME = "vinz"
AUTH_PASSWORD = "odds2026"
SESSION_SECRET_KEY = secrets.token_hex(32)

# ── In-memory cache ──────────────────────────────────────────────
cache: dict = {
    "rows": [],
    "last_updated": None,
    "status": "Initialising…",
    "is_refreshing": False,
    "accumulators": [],          # Pre-computed accumulators with real betslip data
    "raw_bet9ja": [],            # Raw Bet9ja match data (with original team names)
    "raw_sportybet": [],         # Raw SportyBet match data (with original team names)
    "match_name_map": {},        # {normalized_event: {sb_home, sb_away, b9_home, b9_away}}
}
scheduler = AsyncIOScheduler()
sessions: dict = {}  # {session_token: {"username": str, "created": datetime}}


# ── Database Initialization ────────────────────────────────────────
def init_db():
    """Create the odds_history table if it doesn't exist."""
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
            diff REAL
        )
    """)
    conn.commit()
    conn.close()


def save_odds_to_db(rows: list[dict]):
    """Insert all rows into the odds_history table."""
    if not rows:
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for row in rows:
        cursor.execute("""
            INSERT INTO odds_history (timestamp, league, event, market, sign, bet9ja, sportybet, diff)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp,
            row.get("league", ""),
            row.get("event", ""),
            row.get("market", ""),
            row.get("sign", ""),
            row.get("bet9ja", ""),
            row.get("sportybet", ""),
            row.get("diff"),
        ))
    conn.commit()
    conn.close()

# ── Authentication ────────────────────────────────────────────────
def generate_session_token(username: str) -> str:
    """Generate a simple session token from username."""
    return hashlib.sha256(f"{username}{SESSION_SECRET_KEY}".encode()).hexdigest()


def create_session(username: str) -> str:
    """Create a session and return the token."""
    token = generate_session_token(username)
    sessions[token] = {
        "username": username,
        "created": datetime.now().isoformat(),
    }
    return token


def verify_session(token: Optional[str]) -> Optional[str]:
    """Verify a session token and return the username if valid."""
    if token and token in sessions:
        return sessions[token]["username"]
    return None


async def get_current_user(request: Request) -> str:
    """Dependency to check if user is authenticated. Redirects to /login for HTML pages."""
    token = request.cookies.get("session_token")
    username = verify_session(token)
    if not username:
        # Check if this is an API call or HTML page request
        if request.url.path.startswith("/api/"):
            raise HTTPException(status_code=401, detail="Not authenticated")
        # For HTML pages, redirect to login
        raise HTTPException(
            status_code=307,
            headers={"Location": "/login"},
        )
    return username


# ── Accumulator Logic ────────────────────────────────────────────
def _parse_event_date(raw: str):
    """Parse various date formats from Bet9ja API into datetime."""
    if not raw:
        return None
    s = str(raw).strip()
    # .NET JSON date: /Date(1742234400000)/
    m = re.match(r'/Date\((\d+)\)/', s)
    if m:
        return datetime.fromtimestamp(int(m.group(1)) / 1000)
    # Pure unix timestamp
    try:
        ts = float(s)
        if ts > 1e12:
            ts /= 1000
        if 1e9 < ts < 2e10:
            return datetime.fromtimestamp(ts)
    except (ValueError, TypeError):
        pass
    # Try common string formats
    for fmt in (
        "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
        "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(s[:len(fmt)+4], fmt)
        except (ValueError, TypeError):
            continue
    print(f"  [DateParse] Unknown date format: {s[:50]}")
    return None


def build_accumulator_selections(rows: list[dict], name_map: dict, raw_bet9ja: list = None, shuffle: bool = False) -> list[dict]:
    """
    Build a pool of accumulator-worthy selections from the odds rows.
    Returns raw accumulators (without bonus/win — those get filled by betslip checker).

    Each accumulator: {size, selections: [{event, sign, bet9ja, sportybet,
                        league, sb_home, sb_away, b9_home, b9_away}]}
    """
    # Build date lookup from raw_bet9ja for 48h filtering
    event_dates = {}
    if raw_bet9ja:
        for m in raw_bet9ja:
            st = m.get("start_time", "")
            if st:
                event_dates[m["event"]] = _parse_event_date(st)
    now = datetime.now()
    cutoff = now + timedelta(hours=48)

    # Extract matched events where both bookmakers have 1X2 odds 1.20-1.80
    event_selections = {}
    for row in rows:
        if row["market"] != "1X2":
            continue
        if row["bet9ja"] == "—" or row["sportybet"] == "—":
            continue
        try:
            b9_odds = float(row["bet9ja"])
            sb_odds = float(row["sportybet"])
            if not (1.20 <= b9_odds <= 1.80 and 1.20 <= sb_odds <= 1.80):
                continue
        except (ValueError, TypeError):
            continue

        event = row["event"]

        # Skip events beyond 48h cutoff
        evt_dt = event_dates.get(event)
        if evt_dt and evt_dt > cutoff:
            continue

        sign = row["sign"]
        names = name_map.get(event, {})
        if event not in event_selections:
            event_selections[event] = []
        event_selections[event].append({
            "event": event,
            "sign": sign,
            "bet9ja": b9_odds,
            "sportybet": sb_odds,
            "league": row.get("league", names.get("league", "")),
            "sb_home": names.get("sb_home", ""),
            "sb_away": names.get("sb_away", ""),
            "b9_home": names.get("b9_home", ""),
            "b9_away": names.get("b9_away", ""),
        })

    # Build pool: pick one selection per event (best or random)
    all_selections = []
    event_list = list(event_selections.items())
    if shuffle:
        random.shuffle(event_list)
    for event, sels in event_list:
        if shuffle:
            all_selections.append(random.choice(sels))
        else:
            all_selections.append(sels[0])
    if not shuffle:
        all_selections.sort(key=lambda s: s["bet9ja"])

    if len(all_selections) < 3:
        return []

    # Build accumulators: 2x each size
    accumulator_sizes = [3, 5, 8, 10, 15]
    accumulators = []
    for size in accumulator_sizes:
        if len(all_selections) < size:
            continue
        accumulators.append({
            "size": size,
            "selections": all_selections[:size],
        })
        if len(all_selections) >= size * 2:
            accumulators.append({
                "size": size,
                "selections": all_selections[size:size*2],
            })

    return accumulators

async def compute_accumulators_with_betslip(
    accumulators: list[dict],
    sb_page=None,
    b9_page=None,
    stake: float = 100,
) -> list[dict]:
    """
    For each accumulator, get real bonus/win amounts.
    Uses SportyBet's actual betslip via Playwright, Bet9ja's documented formula.
    If sb_page provided, uses real betslip; otherwise falls back to estimate.
    """
    if not accumulators:
        return []

    if sb_page:
        # Use the full betslip checker for real amounts
        raw_results = await check_all_accumulators(sb_page, b9_page, accumulators, stake)
        # Validate SB results: if odds are off >20% from expected, use formula
        for i, res in enumerate(raw_results):
            sels = accumulators[i]["selections"]
            expected_sb = 1.0
            for s in sels:
                expected_sb *= s.get("sportybet", s.get("odds", 1.0))
            actual_sb = res.get("sportybet", {}).get("odds", 0)
            if actual_sb <= 0 or abs(actual_sb - expected_sb) / expected_sb > 0.20:
                print(f"  [Validation] Acca #{i+1}: SB odds {actual_sb} vs expected {expected_sb:.2f} -- using formula")
                res["sportybet"] = _sportybet_formula_fallback(sels, stake)
            # Bet9ja always uses formula (geo-blocked) - label as calculated
            res["bet9ja"] = calculate_bet9ja_returns(sels, stake)
            res["bet9ja"]["source"] = "calculated"
        return raw_results

    # Fallback: formula-based for both
    results = []
    for acca in accumulators:
        sels = acca["selections"]
        b9 = calculate_bet9ja_returns(sels, stake)
        b9["source"] = "calculated"
        sb = _sportybet_formula_fallback(sels, stake)
        results.append({
            "size": acca["size"],
            "selections": [{"event": s["event"], "sign": s["sign"], "bet9ja": s.get("bet9ja", 0), "sportybet": s.get("sportybet", 0)} for s in sels],
            "bet9ja": b9,
            "sportybet": sb,
        })
    return results


# ── Odds Merging ──────────────────────────────────────────────────
def _build_sportybet_map(bet9ja_matches: list[dict], sb_events: list[dict]) -> tuple[dict, dict]:
    """
    Fuzzy-match SportyBet events to Bet9ja events.
    Returns:
      sb_map: {event_name: odds}
      name_map: {event_name: {sb_home, sb_away, b9_home, b9_away, league}}
    """
    sb_map = {}
    name_map = {}
    for b9 in bet9ja_matches:
        event_name = b9["event"]
        b9_parts = event_name.split(" - ", 1)
        b9_home = b9_parts[0].strip() if len(b9_parts) == 2 else event_name
        b9_away = b9_parts[1].strip() if len(b9_parts) == 2 else ""

        for sb in sb_events:
            if fuzzy_match(event_name, sb["event"]):
                sb_map[event_name] = sb.get("odds", {})
                sb_parts = sb["event"].split(" - ", 1)
                sb_home = sb_parts[0].strip() if len(sb_parts) == 2 else sb["event"]
                sb_away = sb_parts[1].strip() if len(sb_parts) == 2 else ""
                name_map[event_name] = {
                    "sb_home": sb_home, "sb_away": sb_away,
                    "b9_home": b9_home, "b9_away": b9_away,
                    "league": b9.get("league", ""),
                }
                break
        else:
            sb_map[event_name] = {}
            name_map[event_name] = {
                "sb_home": "", "sb_away": "",
                "b9_home": b9_home, "b9_away": b9_away,
                "league": b9.get("league", ""),
            }
    return sb_map, name_map


def merge_odds(bet9ja_matches: list[dict], sportybet_map: dict) -> list[dict]:
    MARKETS = [
        ("1X2",           ["1", "X", "2"]),
        ("O/U 2.5",       ["Over", "Under"]),
        ("O/U 1.5",       ["Over", "Under"]),
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
                    "bet9ja":    b9_val or "—",
                    "sportybet": sb_val or "—",
                    "diff":      diff,
                })
    rows.sort(key=lambda r: (-(r["diff"] or 0), r["league"], r["event"]))
    return rows

def _sb_only_rows(sb_events: list[dict]) -> list[dict]:
    """Build rows from SportyBet data alone (when Bet9ja is unavailable)."""
    MARKETS = [
        ("1X2", ["1", "X", "2"]),
        ("O/U 2.5", ["Over", "Under"]),
        ("O/U 1.5", ["Over", "Under"]),
    ]
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
                    "bet9ja":    "—",
                    "sportybet": sb_val,
                    "diff":      None,
                })
    return rows


def _b9_only_rows(b9_matches: list[dict]) -> list[dict]:
    """Build rows from Bet9ja data alone (when SportyBet is unavailable)."""
    MARKETS = [
        ("1X2", ["1", "X", "2"]),
        ("O/U 2.5", ["Over", "Under"]),
        ("O/U 1.5", ["Over", "Under"]),
        ("Double Chance", ["1X", "12", "X2"]),
    ]
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
                    "sportybet": "—",
                    "diff":      None,
                })
    return rows


# ── Refresh Logic ──────────────────────────────────────────────────
async def do_refresh():
    if cache["is_refreshing"]:
        print("[Scheduler] Already refreshing, skipping.")
        return
    cache["is_refreshing"] = True
    cache["status"] = "Refreshing…"
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Starting refresh...")

    try:
        # Bet9ja (JSON API) — may fail due to geo-blocking
        bet9ja_matches = []
        try:
            bet9ja_matches = await scrape_bet9ja(max_matches=MAX_MATCHES)
        except Exception as e:
            print(f"  [Bet9ja] Scraper failed: {e}")

        # SportyBet (Playwright) — always attempt
        sb_events = []
        try:
            sb_events = await scrape_sportybet(max_matches=MAX_MATCHES)
        except Exception as e:
            print(f"  [SportyBet] Scraper failed: {e}")

        if bet9ja_matches and sb_events:
            # Full comparison mode
            sportybet_map, name_map = _build_sportybet_map(bet9ja_matches, sb_events)
            rows = merge_odds(bet9ja_matches, sportybet_map)
            cache["match_name_map"] = name_map
            cache["status"] = f"OK — {len(rows)} rows, {len(bet9ja_matches)} Bet9ja + {len(sb_events)} SportyBet"
        elif bet9ja_matches:
            # Bet9ja only
            rows = _b9_only_rows(bet9ja_matches)
            cache["status"] = f"Bet9ja only — {len(rows)} rows (SportyBet unavailable)"
        elif sb_events:
            # SportyBet only
            rows = _sb_only_rows(sb_events)
            cache["status"] = f"SportyBet only — {len(rows)} rows (Bet9ja unavailable)"
        else:
            rows = []
            cache["status"] = "No data from either source"

        cache["rows"]         = rows
        cache["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cache["raw_bet9ja"]   = bet9ja_matches
        cache["raw_sportybet"] = sb_events

        # Save to database
        save_odds_to_db(rows)

        # Build accumulators with real betslip data
        name_map = cache.get("match_name_map", {})
        raw_accas = build_accumulator_selections(rows, name_map, raw_bet9ja=bet9ja_matches)
        if raw_accas:
            print(f"[Refresh] Building {len(raw_accas)} accumulators with betslip checker...")
            try:
                # Use a fresh Playwright browser for betslip checking
                async with async_playwright() as pw:
                    browser = await pw.chromium.launch(
                        headless=True,
                        args=["--no-sandbox", "--disable-dev-shm-usage"],
                    )
                    sb_page = await browser.new_page()
                    # Block images for speed
                    await sb_page.route(
                        "**/*.{png,jpg,jpeg,gif,webp,woff,woff2,svg}",
                        lambda r: r.abort(),
                    )
                    # Optionally try Bet9ja page too
                    b9_page = None
                    try:
                        b9_page = await browser.new_page()
                        await b9_page.route(
                            "**/*.{png,jpg,jpeg,gif,webp,woff,woff2,svg}",
                            lambda r: r.abort(),
                        )
                        await b9_page.goto("https://sports.bet9ja.com/", timeout=15000)
                        await b9_page.wait_for_timeout(2000)
                    except Exception as e:
                        print(f"  [Bet9ja] Website unavailable for betslip: {e}")
                        b9_page = None

                    cache["accumulators"] = await compute_accumulators_with_betslip(
                        raw_accas, sb_page=sb_page, b9_page=b9_page, stake=100,
                    )
                    await browser.close()

                print(f"[Refresh] Accumulators: {len(cache['accumulators'])} built")
            except Exception as e:
                print(f"[Refresh] Betslip check failed, using formula: {e}")
                cache["accumulators"] = await compute_accumulators_with_betslip(
                    raw_accas, sb_page=None, b9_page=None, stake=100,
                )
        else:
            cache["accumulators"] = []

        print(f"[Refresh] Done: {len(rows)} rows, {len(cache['accumulators'])} accumulators")

    except Exception as e:
        cache["status"] = f"Error: {e}"
        print(f"[Refresh] ERROR: {e}")
    finally:
        cache["is_refreshing"] = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    asyncio.create_task(do_refresh())
    scheduler.add_job(do_refresh, "interval", minutes=REFRESH_MINUTES)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(title="Odds Dashboard", lifespan=lifespan)


# ── Login Routes ──────────────────────────────────────────────────
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    """Serve the login form."""
    return _login_html("")


def _login_html(error_msg: str = "") -> str:
    err_div = f'<div class="error">{error_msg}</div>' if error_msg else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"/><meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>Login - Odds Dashboard</title>
<style>
body {{ font-family:'Inter','Segoe UI',system-ui,sans-serif; display:flex; justify-content:center; align-items:center; height:100vh; background:#0f1117; margin:0; color:#e2e8f0; }}
.login-box {{ background:#1a1d27; padding:40px; border-radius:12px; border:1px solid #2d3144; width:340px; }}
h1 {{ margin:0 0 8px; font-size:1.4rem; text-align:center; }} h1 span {{ color:#6366f1; }}
p {{ text-align:center; color:#64748b; font-size:0.85rem; margin:0 0 24px; }}
label {{ display:block; margin-top:16px; font-size:0.85rem; color:#94a3b8; font-weight:600; }}
input {{ width:100%; padding:10px 12px; margin-top:6px; box-sizing:border-box; border:1px solid #2d3144; border-radius:8px; background:#0f1117; color:#e2e8f0; font-size:0.9rem; outline:none; }}
input:focus {{ border-color:#6366f1; }}
button {{ width:100%; padding:12px; margin-top:24px; background:#6366f1; color:#fff; border:none; border-radius:8px; cursor:pointer; font-size:1rem; font-weight:600; }}
button:hover {{ background:#4f46e5; }}
.error {{ color:#ef4444; margin-top:12px; text-align:center; font-size:0.85rem; }}
</style></head><body>
<div class="login-box">
<h1>⚽ Odds <span>Dashboard</span></h1>
<p>Sign in to continue</p>
<form method="post" action="/login">
<label>Username</label><input type="text" name="username" required autofocus>
<label>Password</label><input type="password" name="password" required>
<button type="submit">Sign In</button>
</form>{err_div}
</div></body></html>"""


@app.post("/login")
async def login(request: Request):
    """Handle login form submission."""
    form_data = await request.form()
    username = form_data.get("username", "")
    password = form_data.get("password", "")

    if username == AUTH_USERNAME and password == AUTH_PASSWORD:
        token = create_session(username)
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie("session_token", token, max_age=86400, httponly=True)
        return response
    else:
        return HTMLResponse(_login_html("Invalid credentials. Please try again."), status_code=401)


@app.get("/logout")
async def logout(response: Response):
    """Clear session and redirect to login."""
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_token")
    return response


# ── Protected Routes ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(current_user: str = Depends(get_current_user)):
    return build_dashboard_html(cache)


@app.get("/api/odds")
async def api_odds(current_user: str = Depends(get_current_user)):
    return JSONResponse({
        "last_updated": cache["last_updated"],
        "status":       cache["status"],
        "count":        len(cache["rows"]),
        "rows":         cache["rows"],
    })


@app.get("/api/refresh")
async def trigger_refresh(current_user: str = Depends(get_current_user)):
    asyncio.create_task(do_refresh())
    return {"message": "Refresh triggered"}


@app.get("/api/accumulators")
async def api_accumulators(current_user: str = Depends(get_current_user)):
    """Return pre-computed accumulator bets with real betslip data."""
    accumulators = cache.get("accumulators", [])
    return JSONResponse({
        "count": len(accumulators),
        "accumulators": accumulators,
    })


@app.get("/api/history")
async def api_history(event: str = "", market: str = "", current_user: str = Depends(get_current_user)):
    """Return historical odds for an event and market."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = "SELECT * FROM odds_history WHERE 1=1"
    params = []

    if event:
        query += " AND event LIKE ?"
        params.append(f"%{event}%")

    if market:
        query += " AND market = ?"
        params.append(market)

    query += " ORDER BY timestamp DESC LIMIT 1000"

    cursor.execute(query, params)
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return JSONResponse({
        "count": len(rows),
        "rows": rows,
    })


@app.get("/api/regenerate")
async def api_regenerate(current_user: str = Depends(get_current_user)):
    """Regenerate accumulators with random selections from the same pool."""
    rows = cache.get("rows", [])
    name_map = cache.get("match_name_map", {})
    raw_bet9ja = cache.get("raw_bet9ja", [])
    raw_accas = build_accumulator_selections(rows, name_map, raw_bet9ja=raw_bet9ja, shuffle=True)
    if raw_accas:
        try:
            cache["accumulators"] = await compute_accumulators_with_betslip(
                raw_accas, sb_page=None, b9_page=None, stake=100,
            )
        except Exception as e:
            print(f"[Regenerate] Error: {e}")
            cache["accumulators"] = []
    else:
        cache["accumulators"] = []
    return JSONResponse({
        "count": len(cache.get("accumulators", [])),
        "accumulators": cache.get("accumulators", []),
    })


@app.get("/health")
async def health():
    return {"status": "ok", "last_updated": cache["last_updated"]}

# v2.1 - Regenerate + Calculated labels
