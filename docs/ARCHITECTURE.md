# Odds Dashboard - Architecture

## Overview

Real-time odds comparison dashboard that scrapes betting odds from 4 active bookmakers (Bet9ja, SportyBet, MSport, YaJuego) and displays them side-by-side for comparison. Built with FastAPI, deployed on Railway.

## System Architecture

```
[GitHub Main Branch]
    |
    v (auto-deploy on push)
[Railway - EU West Amsterdam]
    |
    v
[FastAPI App (main.py)]
    |     |     |
    |     |     +---> [Dashboard HTML (inline f-string)]
    |     |
    |     +---> [APScheduler: refresh every 5 min]
    |
    +---> [Scraper Pipeline]
            |
            +---> [Bet9ja API (aiohttp)] ----+
            |     (parallel)                  |
            +---> [Playwright Scrapers] ------+
            |       +-> SportyBet (sequential)|
            |       +-> MSport   (sequential) |
            +---> [YaJuego API] --------------+
                                              |
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

### Playwright Browser Pattern (CRITICAL)

**All Playwright scrapers MUST follow this pattern.** This was established after a production outage in April 2026 where scrapers crashed due to incompatible Chrome flags.

Since Playwright v1.49, headless mode uses `chromium_headless_shell` — a lightweight binary that does NOT support all Chromium flags. Specifically:
- **`--disable-blink-features=AutomationControlled` CRASHES the browser** — NEVER use this flag
- Anti-bot evasion must use **JavaScript-based stealth** via `page.add_init_script()`

Required pattern:
```python
browser = await pw.chromium.launch(
    headless=True,
    args=["--no-sandbox", "--disable-dev-shm-usage"],
)
context = await browser.new_context(
    ignore_https_errors=True,
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
)
page = await context.new_page()
await page.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    window.chrome = {runtime: {}};
""")
```

Key requirements:
- Always create a **browser context** (never use `browser.new_page()` directly)
- Always set `ignore_https_errors=True` (SportyBet has SSL cert issues)
- Always add the stealth init script before navigating
- Always clean up: `context.close()` then `browser.close()` (never duplicate close calls)

### Scraper Execution Model
- **Bet9ja** uses a REST API (aiohttp) and runs in parallel with Playwright scrapers
- **SportyBet, MSport, YaJuego** use Playwright (headless Chromium) and now run SEQUENTIALLY to prevent Chromium crashes (Railway Pro plan: 32 vCPU / 32 GB RAM)
- Each scraper has its own timeout: Bet9ja=60s, SportyBet=420s, MSport=600s, YaJuego=420s
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

### Favicon

Both the dashboard (dashboard.py) and login page (main.py) use an inline SVG favicon embedded as a base64 data URI. The icon is a lightning bolt on an indigo rounded-rectangle background. No external file is needed — the favicon is self-contained in the HTML `<head>` via a `<link rel="icon">` tag.

### Ephemeral Storage

Railway containers have NO persistent storage. Each deployment starts with a fresh SQLite database. Data is populated by the scraper pipeline on startup and refreshed every 5 minutes.

## Branching & Deployment

| Branch | Purpose | URL | Auto-deploy |
|--------|---------|-----|-------------|
| `main` | Production | https://odds-dashboard-production.up.railway.app | Yes |
| `staging` | Staging/Testing | https://stunning-vibrancy-production-a011.up.railway.app | Yes |

Always test changes on staging before merging to main.

## File Structure

| File | Size | Purpose |
|------|------|--------|
| main.py | ~43KB | Core app: FastAPI routes, merge logic, team aliases, auth, dashboard |
| merge.py | ~616 lines | Team matching: TEAM_ALIASES, SIGN_SWAP_MAP, _normalize_team, merge_odds |
| dashboard.py | ~31KB | Dashboard HTML template (JS/CSS inline) |
| bet9ja_scraper.py | ~6KB | Bet9ja API scraper (aiohttp, no browser) |
| sportybet_scraper.py | ~15KB | SportyBet Playwright scraper (JS stealth + browser context) |
| msport_scraper.py | ~22KB | MSport Playwright scraper (multi-pass: 1X2, O/U, DC; JS stealth) |
| yajuego_scraper.py | ~34KB | YaJuego API scraper (multi-league, multi-market) |
| betfair_scraper.py | ~28KB | Betfair API scraper (currently paused) |
| betking_scraper.py | ~14KB | BetKing scraper (PAUSED - geo-blocked) |
| betano_scraper.py | ~14KB | Betano scraper (PAUSED) |
| betgr8_scraper.py | - | Betgr8 Playwright scraper |
| betslip_checker.py | ~26KB | Betslip/accumulator checking logic |
| betslip_scraper.py | - | Playwright-based betslip scraping for live checks |
| betslip_service.py | - | Separate FastAPI microservice wrapping betslip_scraper |
| debug_routes.py | ~2KB | Debug endpoints (connectivity check) |
| test_main.py | ~42KB | Unit tests |
| Dockerfile | ~0.4KB | Docker build with Playwright |
| railway.toml | ~0.2KB | Railway deployment config |
| requirements.txt | ~0.2KB | Python dependencies |
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
| /api/errors | Yes | GET | Last scraper errors per bookmaker |
| /api/custom-comparison | Yes | POST | Formula-based accumulator comparison |
| /api/live-comparison | Yes | POST | Live betslip check via betslip service |
| /debug/connectivity | No | GET | Tests DNS/TCP/HTTP to bookmaker sites |
| /health | No | GET | Returns last_updated and is_refreshing |

## Authentication

- JWT tokens stored in HTTP-only cookies
- Users: admin (admin123), vinz (odds2026)
- Passwords hashed with bcrypt

## Deployment

- **Platform**: Railway Pro plan (EU West Amsterdam, europe-west4-drams3a) — 32 vCPU / 32 GB RAM
- **Auto-deploy**: Pushes to main branch trigger automatic deployment
- **URL**: odds-dashboard-production.up.railway.app
- **Build**: Dockerfile installs Python deps + Playwright Chromium
- **Docker base image**: `mcr.microsoft.com/playwright/python:v1.49.0-jammy`
- **CI**: GitHub Actions runs pytest on every push

### Betslip Service Deployment

- **Platform**: Railway (Asia Southeast, asia-southeast1-eqsg3a)
- **Service name**: innovative-tranquility
- **URL**: innovative-tranquility-production.up.railway.app
- **Start command**: uvicorn betslip_service:app --host 0.0.0.0 --port 8080
- **Auto-deploy**: Same repo, pushes to main trigger deployment

## Known Gotchas

1. **`--disable-blink-features=AutomationControlled` CRASHES headless_shell**: Playwright v1.49 uses `chromium_headless_shell` for headless mode. This binary does not support the `--disable-blink-features` flag. Use JS stealth via `page.add_init_script()` instead.
2. **Double braces in dashboard JS**: The dashboard HTML is inside a Python f-string. Any JS using `{}` must use `{{ }}` instead
3. **Ephemeral DB**: SQLite is lost on every deploy. First scrape takes ~6 minutes
4. **Bet9ja GROUP IDs are season-specific**: If European competitions return 0 events, IDs in `bet9ja_scraper.py` need updating via the `GetSports?DISP=0` API. Current (2025/26): CL=1185641, EL=1185689, ECL=1946188
5. **TEAM_ALIASES is huge**: Lines 66-1138 (~1073 lines) are team name mappings. Be careful editing
6. **SequenceMatcher false positives**: Common substrings like "ver"/"ton" can give deceptively high similarity. Threshold was raised to 0.70 to mitigate
7. **CDN caching**: GitHub raw content may be cached after commits. Use cache-busting query params
8. **Browser context required**: Always create a browser context via `browser.new_context()` — never use `browser.new_page()` directly. The context allows setting `ignore_https_errors`, custom user agent, and proper cleanup.
9. **No duplicate close calls**: Calling `context.close()` twice will throw. Ensure cleanup code only closes context once before closing the browser.

## Incident History

### April 2026 — SportyBet & MSport Playwright Crash

**Symptom**: Both scrapers returned 0 odds on staging and production. Error in `/api/errors`: `BrowserType.launch: Target page, context or browser has been closed`

**Root cause**: `--disable-blink-features=AutomationControlled` flag in browser launch args is incompatible with Playwright v1.49's `chromium_headless_shell` binary.

**Fix**: Removed the flag, added JS-based stealth via `page.add_init_script()`, added proper browser context with `ignore_https_errors=True` and custom user agent.

**Prevention**: Added this pattern as mandatory in CLAUDE.md and docs, added tests to verify scrapers don't use incompatible flags.
