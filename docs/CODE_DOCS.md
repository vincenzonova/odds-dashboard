# Code Documentation

## File Overview

| File | Size | Purpose |
|------|------|---------|
| `main.py` | ~602 lines | Core app: FastAPI routes, auth, cache, scheduler, dashboard entry (imports merge logic from merge.py) |
| `merge.py` | ~616 lines | Team matching and odds merging: TEAM_ALIASES, SIGN_SWAP_MAP, _normalize_team, _team_sim, fuzzy_match_event, merge_odds |
| `dashboard.py` | ~31KB | Dashboard HTML/JS/CSS template (rendered inside Python f-string) |
| `bet9ja_scraper.py` | ~6KB | Bet9ja API scraper (aiohttp, no browser needed) |
| `sportybet_scraper.py` | ~15KB | SportyBet Playwright scraper with JS injection |
| `msport_scraper.py` | ~22KB | MSport Playwright scraper (multi-pass: 1X2, O/U, DC) |
| `betgr8_scraper.py` | ~34KB | Betgr8 Playwright scraper (multi-league, multi-market) |
| `betslip_checker.py` | ~26KB | Accumulator/betslip checking logic |
| `debug_routes.py` | ~2KB | Debug API endpoints |
| `test_main.py` | ~42KB | Pytest test suite |

## Configuration Constants (main.py)

```python
SECRET_KEY = "your-secret-key-change-in-production"   # L44 — JWT secret
MAX_MATCHES = 100                                       # L45 — max matches per scraper
SCRAPE_DAYS = 2                                         # L46 — default days ahead
MSPORT_MIN_DAYS = 7                                     # L47 — MSport needs wider window
BET9JA_MIN_DAYS = 7                                     # L48 — Bet9ja needs wider window
REFRESH_INTERVAL_MINUTES = 5                            # L49 — auto-refresh interval
DB_PATH = "odds_history.db"                             # L50 — SQLite (ephemeral on Railway)
SCRAPER_TIMEOUTS = {                                    # L51-58
    "bet9ja": 60,
    "sportybet": 420,
    "msport": 600,
    "betgr8": 420,
}
DEFAULT_SCRAPER_TIMEOUT = 120                           # L59
GATHER_TIMEOUT_SECONDS = 600                            # L60 — total gather timeout
```

## TEAM_ALIASES (merge.py L25-L400)

A dictionary mapping ~1073 lines of team name variations to canonical names. This is critical for matching the same team across different bookmakers that use different spellings.

Example:
```python
TEAM_ALIASES = {
    "man utd": "manchester united",
    "man united": "manchester united",
    "wolves": "wolverhampton",
    ...
}
```

## Key Functions (merge.py — matching/merge pipeline)

### `_normalize_team(name: str) -> str` (merge.py L402)
Normalizes a team name by lowercasing, stripping whitespace, removing common suffixes ("fc", "sc"), and looking up TEAM_ALIASES. Returns the canonical team name string.

### `_team_sim(a: str, b: str) -> float` (merge.py L423)
Computes similarity between two team names using `SequenceMatcher`. Both names are normalized first via `_normalize_team()`. Returns a float 0.0-1.0.

### `fuzzy_match_event(event1, event2, threshold=0.70) -> tuple` (merge.py L445)
Compares two match events (each formatted as "Team A - Team B"). Splits on " - ", computes team similarity for both orderings (same order and swapped), and returns `(is_match, should_swap)`. The threshold was raised from 0.55 to 0.70 to prevent false positives (e.g., "wolverhampton" vs "everton" was matching at 0.60).

### `merge_odds(raw_data: dict) -> list` (merge.py L490)
The core merging function. Takes raw scraper output keyed by bookmaker name and produces a unified list of match rows with odds from all bookmakers aligned.

**Two-pass approach:**
1. **Same-league matching** — matches events within the same league first
2. **Cross-league matching** — then attempts to match remaining events across leagues

**Duplicate bookmaker protection (L646+):** If a bookmaker already has odds for a merged event, the incoming duplicate is skipped rather than overwriting. This prevents fuzzy matching from incorrectly replacing correct odds.

### SIGN_SWAP_MAP (merge.py L21)
When team order is reversed between bookmakers, odds signs must be swapped:
```python
SIGN_SWAP_MAP = {
    "1": "2", "2": "1", "X": "X",
    "1X": "X2", "X2": "1X", "12": "12",
    "Over": "Over", "Under": "Under"
}
```

## Key Functions (main.py — app logic)

### `safe_scrape(bookmaker_name, scrape_func, max_matches, days)` (main.py L158)
Wraps individual scraper calls with timeout handling and error logging. Returns empty list on failure.

### `do_refresh()` (main.py L188)
Orchestrates a full refresh cycle:
1. Runs Bet9ja (API) in parallel with sequential Playwright scrapers (SportyBet -> MSport -> Betgr8)
2. Calls `merge_odds()` on collected data
3. Saves to SQLite via `save_odds_to_db()`

### `init_db()` (L474)
Creates the SQLite `odds_history` table if it doesn't exist. Called at startup.

### `save_odds_to_db(rows: list)` (L507)
Persists merged odds rows to SQLite. Note: Railway has no persistent storage, so this data is lost on redeploy.

## Scraper Architecture

### Bet9ja (bet9ja_scraper.py)
- **Type**: Pure API scraper using aiohttp (no browser)
- **Approach**: Calls Bet9ja's internal API endpoints to fetch prematch odds
- **Speed**: Fastest scraper (~60s timeout)
- **Markets**: 1X2, Over/Under, Double Chance

### SportyBet (sportybet_scraper.py)
- **Type**: Playwright browser automation with JS injection
- **Approach**: Navigates to league pages, injects `JS_EXTRACT_MAIN` to query DOM elements
- **DOM selectors**: `.match-row`, `.home-team`, `.away-team`, `.m-outcome-odds`
- **Odds mapping**: First 3 odds = 1X2 (Home, Draw, Away); indices 3-4 = Over/Under
- **Leagues**: PL, La Liga, Serie A, Bundesliga, Ligue 1, CL, EL (via TOURNAMENT_URLS)

### MSport (msport_scraper.py)
- **Type**: Playwright browser automation
- **Approach**: Multi-pass scraping — separate passes for 1X2, Over/Under, and Double Chance
- **Timeout**: 600s (longest, due to multi-pass)

### Betgr8 (betgr8_scraper.py)
- **Type**: Playwright browser automation
- **Approach**: Multi-league, multi-market scraping in a single browser session
- **Size**: Largest scraper file (~34KB)

## API Endpoints

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/` | GET | No | Redirects to /login |
| `/login` | GET/POST | No | Login page and auth handler |
| `/dashboard` | GET | Yes | Main dashboard page |
| `/api/odds` | GET | Yes | All current odds as JSON |
| `/api/odds/{league}` | GET | Yes | Odds filtered by league |
| `/api/status` | GET | Yes | Scraper status and last refresh time |
| `/api/refresh` | POST | Yes | Trigger manual refresh |

## Authentication

JWT-based with session cookies. Two hardcoded users:
- `admin` / `admin123` — Full access
- `vinz` / `odds2026` — Standard access

Token is stored as an HTTP-only cookie named `token`.

## Dashboard (dashboard.py)

The dashboard is a single HTML file with inline JS and CSS, rendered as a Python f-string. This means:

**CRITICAL**: All literal JavaScript braces `{}` must be doubled `{{ }}` in the template. Forgetting this causes Python f-string errors.

Key JS features:
- Fetch odds from `/api/odds` with auth cookie
- Render comparison grid with bookmaker columns
- League filter dropdown
- Date range filter
- Auto-refresh polling with progress indicator
- Accumulator builder (select odds, see combined payout)

## Testing (test_main.py)

Uses pytest. Key test areas:
- Team normalization and aliases
- Fuzzy matching thresholds
- Merge logic with mock scraper data
- Sign swapping for reversed team orders
- API endpoint auth requirements

**Known issue**: Lines 532-1062 are an exact duplicate of lines 1-531. Python silently overrides the first class definitions with the second, so tests still pass but the file is bloated.
