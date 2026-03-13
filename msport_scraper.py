"""
MSport Scraper - uses Playwright to render the page and extract odds from DOM.
MSport's website is accessible without VPN from Amsterdam.

Extracts:
- 1X2 odds (first market on each event)
- Over/Under 2.5 (second market - only when the displayed line is 2.5)

DOM structure:
- League headers: .m-tournament > .m-tournament--title ("Country - League Name")
- Match elements: .m-event within .m-tournament
- Team names: .m-server-name-wrapper (first = home, second = away)
- Markets: .m-market (first = 1X2 with 3 .m-outcome, second = O/U with 2 .m-outcome)
- O/U line: .m-market span (contains "2.5" or "3.5" etc - the nearest line)
- Odds values: .m-outcome > .odds
"""

import asyncio
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

MSPORT_BASE = "https://www.msport.com/ng/web/sports/list/Soccer"

# Map MSport league names (from DOM) to our standard names
# MSport uses both "Europe -" and "International Clubs -" prefixes
LEAGUE_MAP = {
    # England
    "England - Premier League": "Premier League",
    # Spain
    "Spain - LaLiga": "La Liga",
    "Spain - La Liga": "La Liga",
    # Italy
    "Italy - Serie A": "Serie A",
    # Germany
    "Germany - Bundesliga": "Bundesliga",
    # France
    "France - Ligue 1": "Ligue 1",
    # European competitions - "International Clubs" prefix (current MSport format)
    "International Clubs - UEFA Champions League": "Champions League",
    "International Clubs - Champions League": "Champions League",
    "International Clubs - UEFA Europa League": "Europa League",
    "International Clubs - Europa League": "Europa League",
    "International Clubs - UEFA Europa Conference League": "Conference League",
    "International Clubs - Conference League": "Conference League",
    # European competitions - "Europe" prefix (legacy / fallback)
    "Europe - Champions League": "Champions League",
    "Europe - UEFA Champions League": "Champions League",
    "Europe - Europa League": "Europa League",
    "Europe - UEFA Europa League": "Europa League",
    "Europe - Conference League": "Conference League",
    "Europe - UEFA Europa Conference League": "Conference League",
}

# JS to extract all matches from the page, including O/U line value
JS_EXTRACT_ALL = """
() => {
    const tournaments = document.querySelectorAll('.m-tournament');
    const results = [];

    for (const t of tournaments) {
        const titleEl = t.querySelector('.m-tournament--title');
        const league = titleEl ? titleEl.textContent.replace(/\\s+/g, ' ').trim() : '';

        const events = t.querySelectorAll('.m-event');
        for (const ev of events) {
            const nameWrappers = ev.querySelectorAll('.m-server-name-wrapper');
            const teams = [...nameWrappers].map(n => n.textContent.trim());
            if (teams.length < 2 || !teams[0] || !teams[1]) continue;

            const markets = ev.querySelectorAll('.m-market');
            const marketData = [];
            let ouLine = null;

            for (let i = 0; i < markets.length; i++) {
                const mkt = markets[i];
                const outcomes = mkt.querySelectorAll('.m-outcome');
                const odds = [...outcomes].map(o => {
                    const oddsEl = o.querySelector('.odds');
                    return oddsEl ? oddsEl.textContent.trim() : null;
                }).filter(Boolean);
                marketData.push(odds);

                // Second market is O/U - read the line value from the span
                if (i === 1) {
                    const lineSpan = mkt.querySelector('span');
                    if (lineSpan) {
                        ouLine = lineSpan.textContent.trim();
                    }
                }
            }

            results.push({
                league: league,
                home: teams[0],
                away: teams[1],
                markets: marketData,
                ouLine: ouLine
            });
        }
    }
    return results;
}
"""


def calculate_msport_bonus(num_selections: int) -> float:
    """
    Calculate the msport bonus multiplier based on number of selections.
    """
    if num_selections < 4:
        return 0.0
    elif 4 <= num_selections <= 5:
        return 0.05
    elif 6 <= num_selections <= 7:
        return 0.10
    elif 8 <= num_selections <= 9:
        return 0.15
    elif 10 <= num_selections <= 14:
        return 0.33
    elif 15 <= num_selections <= 19:
        return 0.50
    elif 20 <= num_selections <= 24:
        return 0.80
    elif 25 <= num_selections <= 29:
        return 1.30
    else:  # 30+
        return 1.80


def _normalize_league(msport_league: str) -> str:
    """Convert MSport league name to our standard name. Returns None if not a target league."""
    return LEAGUE_MAP.get(msport_league)


def _build_match_dict(raw_match: dict, league_name: str) -> dict:
    """Build a match dict from raw extracted data."""
    home = raw_match["home"]
    away = raw_match["away"]
    markets = raw_match.get("markets", [])
    ou_line = raw_match.get("ouLine")

    odds = {}

    # First market = 1X2 (3 outcomes: 1, X, 2)
    if len(markets) >= 1 and len(markets[0]) >= 3:
        odds["1X2"] = {
            "1": markets[0][0],
            "X": markets[0][1],
            "2": markets[0][2],
        }

    # Second market = O/U - only use if line is 2.5
    if len(markets) >= 2 and len(markets[1]) >= 2:
        if ou_line == "2.5":
            odds["O/U 2.5"] = {
                "Over": markets[1][0],
                "Under": markets[1][1],
            }
        else:
            # Log when we skip non-2.5 lines for debugging
            pass

    return {
        "event": f"{home} - {away}",
        "league": league_name,
        "odds": odds,
    }


async def _scrape_date(page, date_str: str, seen: set, max_matches: int) -> list:
    """Scrape matches for a specific date."""
    url = f"{MSPORT_BASE}?d=d-{date_str}"
    results = []

    try:
        print(f"  [MSport] Loading {date_str}...")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for match elements to appear
        try:
            await page.wait_for_selector(".m-event", timeout=15000)
        except Exception:
            print(f"  [MSport] No matches found for {date_str}")
            return results

        # Extra wait for odds to populate
        await page.wait_for_timeout(3000)

        raw_matches = await page.evaluate(JS_EXTRACT_ALL)
        print(f"  [MSport] {date_str}: found {len(raw_matches)} total events on page")

        matched = 0
        skipped_league = 0
        skipped_ou = 0

        for raw in raw_matches:
            if len(results) >= max_matches:
                break

            # Filter to target leagues only
            league_name = _normalize_league(raw["league"])
            if league_name is None:
                skipped_league += 1
                continue

            key = f"{raw['home']}-{raw['away']}"
            if key in seen:
                continue
            seen.add(key)

            match_dict = _build_match_dict(raw, league_name)
            if match_dict["odds"]:  # Only add if we got some odds
                results.append(match_dict)
                matched += 1
                # Track O/U line info
                ou_line = raw.get("ouLine")
                if ou_line and ou_line != "2.5":
                    skipped_ou += 1

        print(f"  [MSport] {date_str}: {matched} matched, {skipped_league} skipped (wrong league), {skipped_ou} with non-2.5 O/U line")

    except Exception as e:
        print(f"  [MSport] Error scraping {date_str}: {e}")

    return results


async def scrape_msport(max_matches: int = 50) -> list:
    """
    Main entry point for scraping MSport data.
    Loads today + next 3 days to capture upcoming matches.
    """
    results = []
    seen = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page()

        # Block images/fonts for speed
        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,woff,woff2,svg}",
            lambda r: r.abort(),
        )

        # Scrape today + next 3 days
        today = datetime.now()
        for day_offset in range(4):
            if len(results) >= max_matches:
                break
            target_date = today + timedelta(days=day_offset)
            date_str = target_date.strftime("%Y-%m-%d")
            day_results = await _scrape_date(page, date_str, seen, max_matches - len(results))
            results.extend(day_results)

        await browser.close()

    print(f"  [MSport] Done - {len(results)} matches total")
    return results


async def main():
    """Main execution function."""
    import json
    matches = await scrape_msport(max_matches=100)
    print(json.dumps(matches, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
