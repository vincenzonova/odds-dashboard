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
from difflib import SequenceMatcher
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
from betgr8_scraper import scrape_betgr8
# from betano_scraper import scrape_betano  # PAUSED - timeout issues

# Import dashboard HTML builder
from dashboard import build_dashboard_html

# Import betslip checker with all return calculators
from betslip_checker import (
    check_all_accumulators,
    calculate_bet9ja_returns,
    # calculate_betking_returns,  # PAUSED
    calculate_msport_returns,
    # calculate_betano_returns,  # PAUSED
    _sportybet_formula_fallback,
)

# Configuration
SECRET_KEY = "your-secret-key-change-in-production"
MAX_MATCHES = 100
REFRESH_INTERVAL_MINUTES = 5
DB_PATH = "odds_history.db"
SCRAPER_TIMEOUTS = {
    "Bet9ja": 60,       # API-based, fast
    # "BetKing": 60,      # PAUSED
    # "Betano": 60,       # PAUSED
    "SportyBet": 420,   # Playwright, needs 3-5 min for all leagues
    "MSport": 300,      # Playwright, needs 2-4 min
    "Betgr8": 300,      # Playwright, needs 2-4 min
}
DEFAULT_SCRAPER_TIMEOUT = 120
GATHER_TIMEOUT_SECONDS = 600

# Comprehensive team name aliases for major European leagues
TEAM_ALIASES = {
    # English Premier League & Championship
    "manchester united": "manchester utd",
    "man utd": "manchester utd",
    "man united": "manchester utd",
    "tottenham hotspur": "tottenham",
    "spurs": "tottenham",
    "wolverhampton wanderers": "wolverhampton",
    "wolves": "wolverhampton",
    "manchester city": "manchester city",
    "man city": "manchester city",
    "brighton and hove albion": "brighton",
    "brighton & hove albion": "brighton",
    "brighton hove": "brighton",
    "brighton hove albion": "brighton",
    "west ham united": "west ham",
    "west ham utd": "west ham",
    "leicester city": "leicester",
    "newcastle united": "newcastle",
    "newcastle utd": "newcastle",
    "crystal palace": "crystal palace",
    "fulham fc": "fulham",
    "aston villa": "aston villa",
    "brentford fc": "brentford",
    "luton town": "luton",
    "ipswich town": "ipswich",
    "nottingham forest": "nottingham",
    "nott'm forest": "nottingham",
    "nott forest": "nottingham",
    "nottm forest": "nottingham",
    "nott. forest": "nottingham",
    "everton fc": "everton",
    "chelsea fc": "chelsea",
    "liverpool fc": "liverpool",
    "arsenal fc": "arsenal",
    "bournemouth afc": "bournemouth",
    "southampton fc": "southampton",

    # Spanish La Liga
    "atletico de madrid": "atletico madrid",
    "atletico madrid": "atletico madrid",
    "atl. madrid": "atletico madrid",
    "fc barcelona": "barcelona",
    "barcelona": "barcelona",
    "real madrid": "real madrid",
    "real sociedad": "real sociedad",
    "r. sociedad": "real sociedad",
    "villarreal cf": "villarreal",
    "villarreal": "villarreal",
    "sevilla fc": "sevilla",
    "sevilla": "sevilla",
    "real betis": "betis",
    "betis": "betis",
    "rc celta": "celta",
    "celta vigo": "celta",
    "rayo vallecano": "rayo vallecano",
    "rayo": "rayo vallecano",
    "athletic bilbao": "ath bilbao",
    "athletic club": "ath bilbao",
    "ath. bilbao": "ath bilbao",
    "ud almeria": "almeria",
    "almeria": "almeria",
    "cf osasuna": "osasuna",
    "osasuna": "osasuna",
    "getafe cf": "getafe",
    "getafe": "getafe",
    "sd huesca": "huesca",
    "huesca": "huesca",
    "real oviedo": "oviedo",
    "oviedo": "oviedo",
    "eibar sd": "eibar",
    "eibar": "eibar",
    "elche cf": "elche",
    "elche": "elche",
    "ponferradina": "ponferradina",
    "cd leganes": "leganes",
    "leganes": "leganes",
    "cd alcorcon": "alcorcon",
    "alcorcon": "alcorcon",

    # Italian Serie A
    "fc internazionale": "inter",
    "inter milan": "inter",
    "internazionale": "inter",
    "inter": "inter",
    "ac milan": "milan",
    "ac milano": "milan",
    "milan": "milan",
    "as roma": "roma",
    "roma": "roma",
    "ss lazio": "lazio",
    "lazio": "lazio",
    "ssc napoli": "napoli",
    "napoli": "napoli",
    "uc sampdoria": "sampdoria",
    "sampdoria": "sampdoria",
    "genoa cfc": "genoa",
    "genoa": "genoa",
    "hellas verona": "verona",
    "verona": "verona",
    "us sassuolo": "sassuolo",
    "sassuolo": "sassuolo",
    "acf fiorentina": "fiorentina",
    "fiorentina": "fiorentina",
    "cagliari calcio": "cagliari",
    "cagliari": "cagliari",
    "parma calcio": "parma",
    "parma": "parma",
    "uc reggiana": "reggiana",
    "reggiana": "reggiana",
    "spezia calcio": "spezia",
    "spezia": "spezia",
    "pisa sporting club": "pisa",
    "pisa": "pisa",
    "frosinone calcio": "frosinone",
    "frosinone": "frosinone",
    "benevento calcio": "benevento",
    "benevento": "benevento",
    "udinese calcio": "udinese",
    "udinese": "udinese",
    "us sassuolo": "sassuolo",
    "sassuolo calcio": "sassuolo",
    "sassuolo": "sassuolo",
    "genoa cfc": "genoa",
    "genoa": "genoa",
    "como 1907": "como",
    "como": "como",
    "venezia fc": "venezia",
    "venezia": "venezia",
    "monza": "monza",
    "ac monza": "monza",
    "us lecce": "lecce",
    "lecce": "lecce",
    "empoli fc": "empoli",
    "empoli": "empoli",
    "torino fc": "torino",
    "torino": "torino",

    # German Bundesliga
    "fc bayern": "bayern",
    "bayern munich": "bayern",
    "bayern munchen": "bayern",
    "bayern": "bayern",
    "borussia dortmund": "dortmund",
    "b. dortmund": "dortmund",
    "bvb": "dortmund",
    "dortmund": "dortmund",
    "borussia monchengladbach": "gladbach",
    "borussia m'gladbach": "gladbach",
    "b. monchengladbach": "gladbach",
    "b. m'gladbach": "gladbach",
    "m'gladbach": "gladbach",
    "monchengladbach": "gladbach",
    "gladbach": "gladbach",
    "rb leipzig": "leipzig",
    "rasenballsport leipzig": "leipzig",
    "leipzig": "leipzig",
    "bayer leverkusen": "leverkusen",
    "bayer 04 leverkusen": "leverkusen",
    "leverkusen": "leverkusen",
    "vfb stuttgart": "stuttgart",
    "stuttgart": "stuttgart",
    "eintracht frankfurt": "e. frankfurt",
    "ein. frankfurt": "e. frankfurt",
    "e. frankfurt": "e. frankfurt",
    "1. fc heidenheim": "heidenheim",
    "fc heidenheim": "heidenheim",
    "heidenheim": "heidenheim",
    "tsg hoffenheim": "hoffenheim",
    "1899 hoffenheim": "hoffenheim",
    "hoffenheim": "hoffenheim",
    "vfl wolfsburg": "wolfsburg",
    "wolfsburg": "wolfsburg",
    "fc augsburg": "augsburg",
    "augsburg": "augsburg",
    "1. fc union berlin": "union berlin",
    "fc union berlin": "union berlin",
    "union berlin": "union berlin",
    "werder bremen": "werder bremen",
    "sv werder bremen": "werder bremen",
    "1. fsv mainz 05": "mainz",
    "mainz 05": "mainz",
    "mainz": "mainz",
    "fc st. pauli": "st. pauli",
    "st. pauli": "st. pauli",
    "holstein kiel": "holstein kiel",
    "sc freiburg": "freiburg",
    "freiburg": "freiburg",
    "vfl bochum": "bochum",
    "bochum": "bochum",

    # French Ligue 1
    "paris saint-germain": "psg",
    "paris saint germain": "psg",
    "paris sg": "psg",
    "psg": "psg",
    "olympique marseille": "marseille",
    "ol. marseille": "marseille",
    "marseille": "marseille",
    "olympique lyon": "lyon",
    "olympique lyonnais": "lyon",
    "ol. lyon": "lyon",
    "lyon": "lyon",
    "as monaco": "monaco",
    "fc monaco": "monaco",
    "monaco": "monaco",
    "rc lens": "lens",
    "lens": "lens",
    "losc lille": "lille",
    "lille osc": "lille",
    "lille": "lille",
    "stade rennais": "rennes",
    "rennes": "rennes",
    "ogc nice": "nice",
    "nice": "nice",
    "stade brestois": "brest",
    "stade brest": "brest",
    "brest": "brest",
    "montpellier hsc": "montpellier",
    "montpellier": "montpellier",
    "toulouse fc": "toulouse",
    "toulouse": "toulouse",
    "fc lorient": "lorient",
    "lorient": "lorient",
    "fc metz": "metz",
    "metz": "metz",
    "aj auxerre": "auxerre",
    "auxerre": "auxerre",
    "angers sco": "angers",
    "angers": "angers",
    "le havre ac": "le havre",
    "le havre": "le havre",
    "stade de reims": "reims",
    "reims": "reims",
    "as saint-etienne": "saint-etienne",
    "as st-etienne": "saint-etienne",
    "saint-etienne": "saint-etienne",
    "rc strasbourg": "strasbourg",
    "strasbourg": "strasbourg",
    "fc nantes": "nantes",
    "nantes": "nantes",
    "clermont foot": "clermont",
    "clermont": "clermont",
}

# Global cache with expanded structure for 5 bookmakers
cache = {
    "rows": [],
    "last_updated": None,
    "status": "Initialising...",
    "is_refreshing": False,
    "accumulators": [],
    "raw_bet9ja": [],
    "raw_sportybet": [],
    "raw_betking": [],
    "raw_msport": [],
    "raw_betano": [],
    "raw_betgr8": [],
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
            betgr8 TEXT,
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
            INSERT INTO odds_history (timestamp, league, event, market, sign, bet9ja, sportybet, betking, msport, betano, betgr8, diff)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp,
            row.get("league", ""),
            row.get("event", ""),
            row.get("market", ""),
            row.get("sign", ""),
            row.get("bet9ja", "-"),
            row.get("sportybet", "-"),
            row.get("betking", "-"),
            row.get("msport", "-"),
            row.get("betano", "-"),
            row.get("betgr8", "-"),
            row.get("diff", 0.0),
        ))
    conn.commit()
    conn.close()


def _normalize_team(name: str) -> str:
    """Normalize a team name for matching."""
    n = name.lower().strip()
    # Remove common suffixes
    for suffix in [" fc", " cf", " sc", " ssc", " bc", " afc", " calcio"]:
        if n.endswith(suffix):
            n = n[:-len(suffix)].strip()
    # Check aliases
    return TEAM_ALIASES.get(n, n)


def _team_sim(a: str, b: str) -> float:
    """Similarity between two normalized team names."""
    if a == b:
        return 1.0
    # Containment check
    if a in b or b in a:
        return 0.85
    # Word overlap
    wa = set(a.split())
    wb = set(b.split())
    if not wa or not wb:
        return 0.0
    overlap = len(wa & wb) / max(len(wa), len(wb))
    if overlap > 0:
        return max(overlap, 0.3)  # boost any word overlap
    # Character-level similarity as fallback
    return SequenceMatcher(None, a, b).ratio()


# Signs that need swapping when teams are in reversed order
SIGN_SWAP_MAP = {
    "1": "2",
    "2": "1",
    "1X": "X2",
    "X2": "1X",
    # These stay the same:
    "X": "X",
    "12": "12",
    "Over": "Over",
    "Under": "Under",
}


def fuzzy_match_event(event1: str, event2: str, threshold: float = 0.55) -> tuple:
    """
    Fuzzy matching for event names across bookmakers.
    Returns (is_match: bool, is_reversed: bool).
    is_reversed=True means event2 has teams in opposite order from event1.
    Team names are normalized before comparison.
    """
    e1 = event1.lower().strip()
    e2 = event2.lower().strip()
    if e1 == e2:
        return (True, False)

    # Split into home/away teams using " - " separator
    parts1 = [p.strip() for p in e1.split(" - ", 1)]
    parts2 = [p.strip() for p in e2.split(" - ", 1)]

    if len(parts1) != 2 or len(parts2) != 2:
        # Fallback to simple word overlap (can't detect reversal)
        words1 = set(e1.split())
        words2 = set(e2.split())
        if not words1 or not words2:
            return (False, False)
        overlap = len(words1 & words2) / max(len(words1), len(words2))
        return (overlap >= threshold, False)

    home1, away1 = parts1
    home2, away2 = parts2

    # Normalize teams
    home1_norm = _normalize_team(home1)
    away1_norm = _normalize_team(away1)
    home2_norm = _normalize_team(home2)
    away2_norm = _normalize_team(away2)

    # Try direct match: home1~home2, away1~away2
    if _team_sim(home1_norm, home2_norm) >= threshold and _team_sim(away1_norm, away2_norm) >= threshold:
        return (True, False)

    # Try reversed match: home1~away2, away1~home2
    if _team_sim(home1_norm, away2_norm) >= threshold and _team_sim(away1_norm, home2_norm) >= threshold:
        return (True, True)

    return (False, False)


def merge_odds(raw_data: dict) -> list:
    """
    Merge odds from all 5 bookmakers using ANY available data.
    Uses a unified event index built from all bookmakers, with league-based grouping
    for faster and more accurate matching.
    """
    BOOKMAKERS = ["bet9ja", "sportybet", "msport", "betgr8"]  # betking & betano PAUSED

    # Build league index: league -> {event_key -> event_data}
    league_index = {}

    for bk_name in BOOKMAKERS:
        for ev in raw_data.get(bk_name, []):
            league = ev.get("league", "")
            event_name = ev.get("event", "")
            if not event_name:
                continue

            # Initialize league if not present
            if league not in league_index:
                league_index[league] = {}

            # Try to find existing key via fuzzy match within same league
            matched_key = None
            is_reversed = False
            for existing_key in league_index[league]:
                existing_event = league_index[league][existing_key]["event"]
                match_result = fuzzy_match_event(existing_event, event_name)
                if match_result[0]:  # is_match
                    matched_key = existing_key
                    is_reversed = match_result[1]
                    break

            if matched_key is None:
                matched_key = f"{league}|{event_name}"
                league_index[league][matched_key] = {
                    "league": league,
                    "event": event_name,
                    "markets": {},
                }
            else:
                print(f"  [Merge] Matched '{event_name}' ({bk_name}) -> '{league_index[league][matched_key]['event']}' (reversed={is_reversed})")

            # Add this bookmaker's odds into the unified entry
            # SportyBet uses "odds" key, others use "markets"
            markets_data = ev.get("markets", ev.get("odds", {}))
            for market, signs in markets_data.items():
                if market not in league_index[league][matched_key]["markets"]:
                    league_index[league][matched_key]["markets"][market] = {}
                for sign, odds_str in signs.items():
                    # Swap sign if teams are in reversed order
                    actual_sign = SIGN_SWAP_MAP.get(sign, sign) if is_reversed else sign
                    if actual_sign not in league_index[league][matched_key]["markets"][market]:
                        league_index[league][matched_key]["markets"][market][actual_sign] = {}
                    try:
                        odds_val = float(str(odds_str).replace(",", "."))
                        league_index[league][matched_key]["markets"][market][actual_sign][bk_name] = odds_val
                    except (ValueError, AttributeError, TypeError):
                        pass

    # Flatten the league index into rows
    merged_rows = []
    for league, entries in league_index.items():
        for key, entry in entries.items():
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
                            row[bk_name] = "-"

                    # Calculate difference
                    if len(all_odds_values) >= 2:
                        row["diff"] = round(max(all_odds_values) - min(all_odds_values), 2)
                    else:
                        row["diff"] = 0.0

                    merged_rows.append(row)

    return merged_rows


async def safe_scrape(bookmaker_name: str, scrape_func, max_matches: int = MAX_MATCHES):
    """Safely scrape a bookmaker with error handling and per-scraper timeout."""
    timeout = SCRAPER_TIMEOUTS.get(bookmaker_name, DEFAULT_SCRAPER_TIMEOUT)
    try:
        result = await asyncio.wait_for(
            scrape_func(max_matches=max_matches),
            timeout=timeout
        )
        print(f"  [Scraper] {bookmaker_name} completed: {len(result)} events (timeout was {timeout}s)")
        return {
            "bookmaker": bookmaker_name,
            "data": result,
            "error": None,
        }
    except asyncio.TimeoutError:
        print(f"  [Scraper] {bookmaker_name} TIMED OUT after {timeout}s")
        return {
            "bookmaker": bookmaker_name,
            "data": [],
            "error": f"Scraper timeout after {timeout}s",
        }
    except Exception as e:
        print(f"  [Scraper] {bookmaker_name} ERROR: {e}")
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
        results = await asyncio.wait_for(
            asyncio.gather(
                safe_scrape("Bet9ja", scrape_bet9ja, max_matches=MAX_MATCHES),
                safe_scrape("SportyBet", scrape_sportybet, max_matches=MAX_MATCHES),
                # safe_scrape("BetKing", scrape_betking, max_matches=MAX_MATCHES),  # PAUSED
                safe_scrape("MSport", scrape_msport, max_matches=MAX_MATCHES),
            safe_scrape("Betgr8", scrape_betgr8, max_matches=MAX_MATCHES),
                # safe_scrape("Betano", scrape_betano, max_matches=MAX_MATCHES),  # PAUSED
            ),
            timeout=GATHER_TIMEOUT_SECONDS
        )

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
        cache["raw_betgr8"] = raw_data.get("betgr8", [])
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
