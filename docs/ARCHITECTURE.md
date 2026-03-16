# Odds Dashboard - Architecture

## Overview

Real-time odds comparison dashboard that scrapes betting odds from 4 Nigerian bookmakers (Bet9ja, SportyBet, MSport, Betgr8) and displays them side-by-side for comparison. Built with FastAPI, deployed on Railway.

## System Architecture

```
[GitHub Main Branch]
       |
       v (auto-deploy on push)
[Railway - EU West Amsterdam]
       |
       v
[FastAPI App (main.py)]
  |         |          |
  |         |          +---> [Dashboard HTML (inline f-string)]
  |         |
  |         +---> [APScheduler: refresh every 5 min]
  |
  +---> [Scraper Pipeline]
           |
           +---> [Bet9ja API (aiohttp)] ----+
           |                                 |  (parallel)
           +---> [Playwright Scrapers] ------+
                    |                        |
                    +-> SportyBet (sequential)|
                    +-> MSport   (sequential)|
                    +-> Betgr8   (sequential)|
                                             v
                                    [merge_odds()]
                                             |
                                             v
                                    [SQLite DB (ephemeral)]
                                             |
                                             v
                                    [/api/odds JSON endpoint]
```

## Betslip Service (Separate Railway Instance)

The betslip service runs as a separate Railway deployment to handle live accumulator/betslip checking via Playwright browser automation.

- **Service name**: innovative-tranquility
- **URL**: https://innovative-tranquility-production.up.railway.app
- **Region**: asia-southeast1-eqsg3a
- **File**: betslip_service.py (FastAPI wrapper around betslip_scraper.py)
- **Auth**: API secret via BETSLIP_API_SECRET env var
- **Health check**: GET / returns {"status":"ok","service":"betslip"}

### Live Check Flow

1. User selects matches on dashboard and clicks "Live Check"
2. Dashboard JS calls `/api/live-comparison` on main service
3. Main service forwards request to betslip service via HTTP POST
4. Betslip service uses Playwright to check actual bookmaker betslips
5. If betslip service fails or is unavailable, main service falls back to formula-based calculation
6. Response includes: results per bookmaker, selections list, stake, and size

### Environment Variables (Main Service)

| Variable | Default | Description |
|----------|---------|-------------|
| BETSLIP_SERVICE_URL | "" | Full URL of betslip service (e.g., https://innovative-tranquility-production.up.railway.app) |
| BETSLIP_API_SECRET | "betslip-secret-key" | Shared secret for authenticating requests to betslip service |

## Key Design Decisions

### Scraper Execution Model
- **Bet9ja** uses a REST API (aiohttp) and runs in parallel with Playwright scrapers
- **SportyBet, MSport, Betgr8** use Playwright (headless Chromium) and now run in PARALLEL via `asyncio.gather` (Railway Pro plan: 32 vCPU / 32 GB RAM)
- Each scraper has its own timeout: Bet9ja=60s, SportyBet=420s, MSport=600s, Betgr8=420s
- Global gather timeout: 600s

### Event Matching (merge_odds)
The most critical and complex part of the system. Different bookmakers use different team names (e.g., "Wolverhampton Wanderers" vs "Wolves" vs "Wolverhampton"). The merge pipeline:

1. **_normalize_team()**: Strips suffixes (fc, sc, cf...), prefixes (fc, sc, afc...), accents, and resolves aliases via TEAM_ALIASES dict
2. **_team_sim()**: Calculates similarity between normalized names using (in priority order): exact match (1.0), containment (0.88), word overlap (0.55+), prefix match (0.85), SequenceMatcher fallback
3. **fuzzy_match_event()**: Compares two "Home - Away" event strings. Threshold = 0.70 (raised from 0.55 to fix false positives like wolverhampton/everton)
4. **merge_odds()**: Two-pass merge:
   - Same-league matching: iterates new events against existing events in same league
   - Cross-league matching: catches events listed under different league names (threshold = 0.75)
   - Duplicate bookmaker protection: skips if the bookmaker already has odds for an entry

### SIGN_SWAP_MAP
When team order is reversed between bookmakers (e.g., "Team A - Team B" on one vs "Team B - Team A" on another), odds signs are swapped: 1<->2, 1X<->X2, X stays X.

### Dashboard Rendering
The dashboard HTML is served as a Python f-string from main.py. **CRITICAL**: All literal JavaScript braces must be doubled (`{{ }}`) because Python's f-string interprets single braces as template variables.

### Ephemeral Storage
Railway containers have NO persistent storage. Each deployment starts with a fresh SQLite database. Data is populated by the scraper pipeline on startup and refreshed every 5 minutes.

## File Structure

| File | Size | Purpose |
|------|------|---------|
| main.py | 43KB (1192 lines) | Core app: FastAPI routes, merge logic, team aliases, auth, dashboard |
| dashboard.py | 31KB | Dashboard HTML template (JS/CSS inline) |
| bet9ja_scraper.py | 6KB | Bet9ja API scraper (aiohttp, no browser) |
| sportybet_scraper.py | 15KB | SportyBet Playwright scraper (JS injection) |
| msport_scraper.py | 22KB | MSport Playwright scraper (multi-pass: 1X2, O/U, DC) |
| betgr8_scraper.py | 16KB | Betgr8 Playwright scraper (multi-league, multi-market) |
| betking_scraper.py | 14KB | BetKing scraper (PAUSED - geo-blocked) |
| betano_scraper.py | 14KB | Betano scraper (PAUSED) |
| betslip_checker.py | 26KB | Betslip/accumulator checking logic |
| betslip_scraper.py | - | Playwright-based betslip scraping for live checks |
| betslip_service.py | - | Separate FastAPI microservice wrapping betslip_scraper (deployed as own Railway instance) |
| debug_routes.py | 2KB | Debug endpoints (connectivity check) |
| test_main.py | 42KB | Unit tests (has duplicate sections L532-1062) |
| Dockerfile | 0.4KB | Docker build with Playwright |
| railway.toml | 0.2KB | Railway deployment config |
| requirements.txt | 0.2KB | Python dependencies |
| .github/workflows/test.yml | CI | GitHub Actions test workflow |

## Configuration Constants (main.py)

| Constant | Value | Description |
|----------|-------|-------------|
| MAX_MATCHES | 160 | Max matches per scraper |
| SCRAPE_DAYS | 7 | Default days ahead to scrape |
| MSPORT_MIN_DAYS | 7 | MSport needs wider window |
| BET9JA_MIN_DAYS | 7 | Bet9ja also uses wider window |
| REFRESH_INTERVAL_MINUTES | 5 | Auto-refresh interval |
| SCRAPER_TIMEOUTS | varies | Per-bookmaker timeout (see above) |
| GATHER_TIMEOUT_SECONDS | 600 | Max total scrape time |

## API Endpoints

| Endpoint | Auth | Method | Description |
|----------|------|--------|-------------|
| /login | No | POST | JWT auth (returns token as cookie) |
| /logout | Yes | POST | Clears auth cookie |
| /dashboard | Yes | GET | Main dashboard HTML page |
| /api/odds | Yes | GET | All merged odds as JSON |
| /api/odds/{league} | Yes | GET | Odds filtered by league |
| /api/status | Yes | GET | Scraper refresh status |
| /api/refresh | Yes | POST | Trigger manual refresh |
| /api/settings | Yes | GET/POST | Dashboard settings (days, max) |
| /api/custom-comparison | Yes | POST | Formula-based accumulator comparison (instant, used by Quick Compare) |
| /api/live-comparison | Yes | POST | Live betslip check via betslip service with formula fallback |

## Authentication
- JWT tokens stored in HTTP-only cookies
- Users: admin (admin123), vinz (odds2026), paulo (paulo2026), alessandro (alessandro2026)
- Passwords hashed with bcrypt

## Deployment
- **Platform**: Railway Pro plan (EU West Amsterdam, europe-west4-drams3a) — 32 vCPU / 32 GB RAM
- **Auto-deploy**: Pushes to main branch trigger automatic deployment
- **URL**: odds-dashboard-production.up.railway.app
- **Build**: Dockerfile installs Python deps + Playwright Chromium
- **CI**: GitHub Actions runs pytest on every push to main and staging branches

### Betslip Service Deployment

- **Platform**: Railway (Asia Southeast, asia-southeast1-eqsg3a)
- **Service name**: innovative-tranquility
- **URL**: innovative-tranquility-production.up.railway.app
- **Start command**: uvicorn betslip_service:app --host 0.0.0.0 --port 8080
- **Auto-deploy**: Same repo, pushes to main trigger deployment



### Staging Environment
- **Branch**: staging (created from main)
- **Railway service**: stunning-vibrancy
- **URL**: stunning-vibrancy-production-a011.up.railway.app
- **Region**: asia-southeast1-eqsg3a
- **Purpose**: Test scraper optimizations and new features before merging to main
- **Auto-deploy**: Pushes to staging branch trigger automatic deployment
- **Scraper wait time optimizations** (staging only):
  - Betgr8: WAIT_SECONDS=3 (prod: 5), settle time=1s (prod: 2s), dropdown wait=1s (prod: 1.5s)
  - MSport: DOM render=2s (prod: 3s), dropdown=500ms (prod: 800ms), odds update=1.5s (prod: 2.5s)
  - SportyBet: unchanged (already optimized)
  - Bet9ja: unchanged (API-based, no browser waits)

## Known Gotchas

1. **Double braces in dashboard JS**: The dashboard HTML is inside a Python f-string. Any JS using `{}` must use `{{ }}` instead
2. **Ephemeral DB**: SQLite is lost on every deploy. First scrape takes ~6 minutes
3. **Bet9ja GROUP IDs are season-specific**: If European competitions return 0 events, IDs in `bet9ja_scraper.py` need updating via the `GetSports?DISP=0` API. Current (2025/26): CL=1185641, EL=1185689, ECL=1946188
4. **TEAM_ALIASES is huge**: Lines 66-1138 (~1073 lines) are team name mappings. Be careful editing
5. **test_main.py has duplicate sections**: Lines 532-1062 duplicate lines 1-531 (Python overrides first class, tests still pass)
6. **SequenceMatcher false positives**: Common substrings like "ver"/"ton" can give deceptively high similarity. Threshold was raised to 0.70 to mitigate
7. **CDN caching**: GitHub raw content may be cached after commits. Use cache-busting query params
