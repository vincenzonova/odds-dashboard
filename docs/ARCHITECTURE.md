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

## Key Design Decisions

### Scraper Execution Model
- **Bet9ja** uses a REST API (aiohttp) and runs in parallel with Playwright scrapers
- **SportyBet, MSport, Betgr8** use Playwright (headless Chromium) and run SEQUENTIALLY because Railway has limited resources for concurrent browser instances
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
| betgr8_scraper.py | 34KB | Betgr8 Playwright scraper (multi-league, multi-market) |
| betking_scraper.py | 14KB | BetKing scraper (PAUSED - geo-blocked) |
| betano_scraper.py | 14KB | Betano scraper (PAUSED) |
| betslip_checker.py | 26KB | Betslip/accumulator checking logic |
| debug_routes.py | 2KB | Debug endpoints (connectivity check) |
| test_main.py | 42KB | Unit tests (has duplicate sections L532-1062) |
| Dockerfile | 0.4KB | Docker build with Playwright |
| railway.toml | 0.2KB | Railway deployment config |
| requirements.txt | 0.2KB | Python dependencies |
| .github/workflows/test.yml | CI | GitHub Actions test workflow |

## Configuration Constants (main.py)

| Constant | Value | Description |
|----------|-------|-------------|
| MAX_MATCHES | 100 | Max matches per scraper |
| SCRAPE_DAYS | 2 | Default days ahead to scrape |
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

## Authentication
- JWT tokens stored in HTTP-only cookies
- Users: admin (admin123), vinz (odds2026)
- Passwords hashed with bcrypt

## Deployment
- **Platform**: Railway (EU West Amsterdam, europe-west4-drams3a)
- **Auto-deploy**: Pushes to main branch trigger automatic deployment
- **URL**: odds-dashboard-production.up.railway.app
- **Build**: Dockerfile installs Python deps + Playwright Chromium
- **CI**: GitHub Actions runs pytest on every push

## Known Gotchas

1. **Double braces in dashboard JS**: The dashboard HTML is inside a Python f-string. Any JS using `{}` must use `{{ }}` instead
2. **Ephemeral DB**: SQLite is lost on every deploy. First scrape takes ~6 minutes
3. **Sequential Playwright scrapers**: Can't run browser scrapers in parallel on Railway's resources
4. **TEAM_ALIASES is huge**: Lines 66-1138 (~1073 lines) are team name mappings. Be careful editing
5. **test_main.py has duplicate sections**: Lines 532-1062 duplicate lines 1-531 (Python overrides first class, tests still pass)
6. **SequenceMatcher false positives**: Common substrings like "ver"/"ton" can give deceptively high similarity. Threshold was raised to 0.70 to mitigate
7. **CDN caching**: GitHub raw content may be cached after commits. Use cache-busting query params
