# Odds Dashboard — Product Overview

## What It Is

The Odds Dashboard is a real-time sports betting odds comparison tool focused on the **Nigerian market**. It scrapes odds from multiple Nigerian bookmakers and presents them side-by-side so users can instantly spot the best available price for any match.

## Problem It Solves

Nigerian bettors typically check each bookmaker's website individually to compare odds — a slow, manual process. The Odds Dashboard automates this by collecting odds from all major bookmakers in one place, saving time and helping users find the best value.

## Target Users

- Sports bettors in Nigeria who want to compare odds across bookmakers
- Users interested in 1X2 (match result), Over/Under, and Double Chance markets
- Focus on major European football leagues (Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League)

## Active Bookmakers

| Bookmaker | Scraper Type | Status |
|-----------|-------------|--------|
| Bet9ja | API (aiohttp) | Active |
| SportyBet | Playwright (browser) | Active |
| MSport | Playwright (browser) | Active |
| YaJuego | REST API | Active |
| Betfair | REST API | Paused |
| Betking | Playwright (browser) | Paused |
| Betano | Playwright (browser) | Paused |

## Key Features

### Odds Comparison Grid
The main dashboard displays a table of upcoming matches with odds from each bookmaker in columns. Users can see at a glance which bookmaker offers the best price for any selection.

### Supported Markets
- **1X2** — Home Win (1), Draw (X), Away Win (2)
- **Over/Under** — Over 2.5 goals, Under 2.5 goals
- **Double Chance** — 1X, X2, 12

### League Filtering
Users can filter matches by league to focus on the competitions they care about.

### Date Range Filtering
Matches are shown for the next 2-7 days depending on bookmaker availability. Users can filter by date range.

### Auto-Refresh
Odds are automatically refreshed every 5 minutes to keep prices current. The dashboard shows a progress indicator during refresh cycles.

### Accumulator Builder
Users can select multiple odds to build accumulators (parlays) and see the combined potential payout.

### Authentication
The dashboard requires login. Two user accounts exist:
- `admin` — Full access
- `vinz` — Standard access

## Deployment

- **Platform**: Railway (EU West — Amsterdam)
- **Auto-deploy**: Pushes to `main` branch trigger automatic deployment
- **Container**: Docker with Playwright browsers pre-installed
- **Storage**: Ephemeral (SQLite DB resets on each deploy) — historical odds do not persist

## Business Priorities

1. **Odds coverage** — All bookmakers should load correctly with 95%+ match coverage
2. **Accuracy** — Odds displayed must match the actual bookmaker website
3. **Focus leagues** — Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League
4. **Time horizon** — Next 7 days of matches
5. **Market priority** — 1X2 first, then Over/Under and Double Chance

## Known Limitations

- Railway has no persistent storage — odds history resets on each deployment
- Playwright scrapers run sequentially (not in parallel) due to resource constraints
- Some bookmakers may be slow to respond, leading to timeout-based gaps
- Betking and Betano scrapers are currently paused due to site changes
# Odds Dashboard — Product Overview

## What It Is

The Odds Dashboard is a real-time sports betting odds comparison tool focused on the **Nigerian market**. It scrapes odds from multiple Nigerian bookmakers and presents them side-by-side so users can instantly spot the best available price for any match.

## Problem It Solves

Nigerian bettors typically check each bookmaker's website individually to compare odds — a slow, manual process. The Odds Dashboard automates this by collecting odds from all major bookmakers in one place, saving time and helping users find the best value.

## Target Users

- Sports bettors in Nigeria who want to compare odds across bookmakers
- Users interested in 1X2 (match result), Over/Under, and Double Chance markets
- Focus on major European football leagues (Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League)

## Active Bookmakers

| Bookmaker | Scraper Type | Status |
|-----------|-------------|--------|
| Bet9ja | API (aiohttp) | Active |
| SportyBet | Playwright (browser) | Active |
| MSport | Playwright (browser) | Active |
| Betgr8 | Playwright (browser) | Active |
| Betking | Playwright (browser) | Paused |
| Betano | Playwright (browser) | Paused |

## Key Features

### Odds Comparison Grid
The main dashboard displays a table of upcoming matches with odds from each bookmaker in columns. Users can see at a glance which bookmaker offers the best price for any selection.

### Supported Markets
- **1X2** — Home Win (1), Draw (X), Away Win (2)
- **Over/Under** — Over 2.5 goals, Under 2.5 goals
- **Double Chance** — 1X, X2, 12

### League Filtering
Users can filter matches by league to focus on the competitions they care about.

### Date Range Filtering
Matches are shown for the next 2-7 days depending on bookmaker availability. Users can filter by date range.

### Auto-Refresh
Odds are automatically refreshed every 5 minutes to keep prices current. The dashboard shows a progress indicator during refresh cycles.

### Accumulator Builder
Users can select multiple odds to build accumulators (parlays) and see the combined potential payout.

### Authentication
The dashboard requires login. Two user accounts exist:
- `admin` — Full access
- `vinz` — Standard access

## Deployment

- **Platform**: Railway (EU West — Amsterdam)
- **Auto-deploy**: Pushes to `main` branch trigger automatic deployment
- **Container**: Docker with Playwright browsers pre-installed
- **Storage**: Ephemeral (SQLite DB resets on each deploy) — historical odds do not persist

## Business Priorities

1. **Odds coverage** — All bookmakers should load correctly with 95%+ match coverage
2. **Accuracy** — Odds displayed must match the actual bookmaker website
3. **Focus leagues** — Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League
4. **Time horizon** — Next 7 days of matches
5. **Market priority** — 1X2 first, then Over/Under and Double Chance

## Known Limitations

- Railway has no persistent storage — odds history resets on each deployment
- Playwright scrapers run sequentially (not in parallel) due to resource constraints
- Some bookmakers may be slow to respond, leading to timeout-based gaps
- Betking and Betano scrapers are currently paused due to site changes
