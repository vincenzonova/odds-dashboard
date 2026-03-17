"""
MSport Scraper v2 - API response interception (replaces multi-pass DOM scraping).

Still uses Playwright to navigate (needed for cookies/headers), but intercepts the
JSON API response from /api/ng/facts-center/query/frontend/sports-matches-list
instead of scraping the DOM.

Speed improvement: ~5-10s per date instead of ~60-120s (no dropdown clicks, no
extra page loads for O/U line switches or Double Chance).

All market data (1X2, O/U 1.5, O/U 2.5, Double Chance) comes in a SINGLE API
response per date.

API details:
  - Endpoint: POST /api/ng/facts-center/query/frontend/sports-matches-list
  - Query params: sportId, timeslot, date, tournamentIds (optional)
  - Required headers: operid, deviceid, clientid, platform, apilevel, etc.
  - Body: {} (empty JSON)
  - Response: { data: { tournaments: [...], events: [...] } }

Market IDs (same as SportyBet):
  - id=1  -> 1X2: outcomes 1=Home, 2=Draw, 3=Away
  - id=18 -> O/U: specifier "total=2.5", "total=1.5", etc.
  - id=10 -> DC:  outcomes 9=1X, 10=12, 11=X2
"""

import asyncio
import json as json_module
from datetime import datetime, timedelta
from playwright.async_api import async_playwright


MSPORT_BASE = "https://www.msport.com/ng/web/sports/list/Soccer"

# Sportradar tournament IDs used by MSport for URL filtering
TOURNAMENT_IDS = {
    "Premier League": "sr:tournament:17",
    "La Liga": "sr:tournament:8",
    "Serie A": "sr:tournament:23",
    "Bundesliga": "sr:tournament:35",
    "Ligue 1": "sr:tournament:34",
    "Champions League": "sr:tournament:7",
    "Europa League": "sr:tournament:679",
    "Conference League": "sr:tournament:34480",
}

TOURNAMENT_FILTER = ",".join(TOURNAMENT_IDS.values())

# Map MSport API tournament names to our standard names
# The API returns tournament names like "UEFA Champions League", "Premier League", etc.
TOURNAMENT_NAME_MAP = {
    "premier league": "Premier League",
    "laliga": "La Liga",
    "la liga": "La Liga",
    "serie a": "Serie A",
    "bundesliga": "Bundesliga",
    "ligue 1": "Ligue 1",
    "uefa champions league": "Champions League",
    "champions league": "Champions League",
    "uefa europa league": "Europa League",
    "europa league": "Europa League",
    "uefa europa conference league": "Conference League",
    "europa conference league": "Conference League",
    "conference league": "Conference League",
}

# Map tournament IDs to standard league names (more reliable than name matching)
TOURNAMENT_ID_MAP = {
    "sr:tournament:17": "Premier League",
    "sr:tournament:8": "La Liga",
    "sr:tournament:23": "Serie A",
    "sr:tournament:35": "Bundesliga",
    "sr:tournament:34": "Ligue 1",
    "sr:tournament:7": "Champions League",
    "sr:tournament:679": "Europa League",
    "sr:tournament:34480": "Conference League",
}


def calculate_msport_bonus(num_selections: int) -> float:
    """Calculate the msport bonus multiplier based on number of selections."""
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
    else:
        return 1.80


def _parse_api_response(data: dict) -> list:
    """Parse the MSport API response into our standard match format.

    API response structure:
      data.tournaments[] -> each has:
        - tournament (name), tournamentId
        - events[] -> each has:
          - homeTeam, awayTeam
          - markets[] -> each has:
            - id, name, specifiers
            - outcomes[] -> each has: description, odds, id
    """
    results = []
    tournaments = data.get("tournaments", [])

    for t in tournaments:
        tid = t.get("tournamentId", "")
        # Map tournament to our standard league name
        league = TOURNAMENT_ID_MAP.get(tid)
        if not league:
            # Try name-based matching as fallback
            tname = (t.get("tournament") or "").lower().strip()
            league = TOURNAMENT_NAME_MAP.get(tname)
        if not league:
            continue

        for event in t.get("events", []):
            home = event.get("homeTeam", "")
            away = event.get("awayTeam", "")
            if not home or not away:
                continue

            odds = {}
            markets = event.get("markets", [])

            for market in markets:
                mid = market.get("id")
                outcomes = market.get("outcomes", [])
                specifiers = market.get("specifiers", "")

                # 1X2 (market id=1)
                if mid == 1 and len(outcomes) >= 3:
                    odds_map = {}
                    for o in outcomes:
                        oid = str(o.get("id", ""))
                        oval = o.get("odds", "")
                        if oid == "1":
                            odds_map["1"] = oval
                        elif oid == "2":
                            odds_map["X"] = oval
                        elif oid == "3":
                            odds_map["2"] = oval
                    if "1" in odds_map and "X" in odds_map and "2" in odds_map:
                        odds["1X2"] = odds_map

                # Over/Under (market id=18)
                elif mid == 18 and len(outcomes) >= 2:
                    over_odds = None
                    under_odds = None
                    for o in outcomes:
                        desc = (o.get("description") or "").lower()
                        if "over" in desc:
                            over_odds = o.get("odds", "")
                        elif "under" in desc:
                            under_odds = o.get("odds", "")
                    if over_odds and under_odds:
                        if specifiers == "total=2.5":
                            odds["O/U 2.5"] = {"Over": over_odds, "Under": under_odds}
                        elif specifiers == "total=1.5":
                            odds["O/U 1.5"] = {"Over": over_odds, "Under": under_odds}

                # Double Chance (market id=10)
                elif mid == 10 and len(outcomes) >= 3:
                    dc_map = {}
                    for o in outcomes:
                        oid = str(o.get("id", ""))
                        oval = o.get("odds", "")
                        if oid == "9":
                            dc_map["1X"] = oval
                        elif oid == "10":
                            dc_map["12"] = oval
                        elif oid == "11":
                            dc_map["X2"] = oval
                    if "1X" in dc_map and "12" in dc_map and "X2" in dc_map:
                        odds["Double Chance"] = dc_map

            if odds and "1X2" in odds:
                results.append({
                    "event": f"{home} - {away}",
                    "league": league,
                    "odds": odds,
                })

    return results


async def _scrape_date_via_api(page, date_str: str, is_today: bool,
                                seen: set, max_matches: int) -> list:
    """Scrape matches for a specific date by intercepting the API response.

    Instead of DOM scraping with 4 passes, we:
    1. Set up a route handler to intercept the API response
    2. Navigate to the page (triggers the API call)
    3. Parse the JSON response directly

    All markets (1X2, O/U 1.5, O/U 2.5, DC) come in ONE response.
    """
    results = []
    api_data = {}
    api_captured = asyncio.Event()

    async def intercept_api(route):
        """Intercept the sports-matches-list API response."""
        nonlocal api_data
        try:
            response = await route.fetch()
            body = await response.body()
            json_data = json_module.loads(body)

            if json_data.get("bizCode") == 10000 and json_data.get("data"):
                api_data = json_data["data"]
                api_captured.set()

            # Continue the response to the page (so it renders normally)
            await route.fulfill(response=response)
        except Exception as e:
            print(f"  [MSport] API intercept error: {e}")
            await route.continue_()

    # Set up route interception for the API endpoint
    await page.route("**/api/ng/facts-center/query/frontend/sports-matches-list*",
                      intercept_api)

    try:
        # Navigate to the date page (this triggers the API call)
        url = f"{MSPORT_BASE}?d=d-{date_str}&t={TOURNAMENT_FILTER}"
        print(f"  [MSport] Loading {date_str} (API interception)...")

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for the API response to be captured
        try:
            await asyncio.wait_for(api_captured.wait(), timeout=15.0)
        except asyncio.TimeoutError:
            print(f"  [MSport] {date_str}: API response timeout")

            # Retry for today without date parameter
            if is_today and not api_data:
                api_captured.clear()
                url_no_date = f"{MSPORT_BASE}?t={TOURNAMENT_FILTER}"
                print(f"  [MSport] Retrying {date_str} without date param...")
                await page.goto(url_no_date, wait_until="domcontentloaded", timeout=30000)
                try:
                    await asyncio.wait_for(api_captured.wait(), timeout=15.0)
                except asyncio.TimeoutError:
                    pass

        if not api_data:
            print(f"  [MSport] {date_str}: no API data captured")
            return results

        # Parse the API response
        parsed = _parse_api_response(api_data)

        for match in parsed:
            if len(results) >= max_matches:
                break
            event_key = match["event"]
            if event_key in seen:
                continue
            seen.add(event_key)
            results.append(match)

        # Log summary
        n_1x2 = sum(1 for m in results if "1X2" in m["odds"])
        n_ou25 = sum(1 for m in results if "O/U 2.5" in m["odds"])
        n_ou15 = sum(1 for m in results if "O/U 1.5" in m["odds"])
        n_dc = sum(1 for m in results if "Double Chance" in m["odds"])
        print(f"  [MSport] {date_str}: {len(results)} matches "
              f"(1X2={n_1x2}, O/U2.5={n_ou25}, O/U1.5={n_ou15}, DC={n_dc}) [API, instant]")

    except Exception as e:
        print(f"  [MSport] Error scraping {date_str}: {e}")
    finally:
        # Remove the route handler to avoid interfering with next date
        await page.unroute("**/api/ng/facts-center/query/frontend/sports-matches-list*")

    return results


async def scrape_msport(max_matches: int = 200) -> list:
    """Main entry point for scraping MSport data.

    Loads today + next 6 days (full week) to capture upcoming matches.
    Uses API response interception — all markets in a single page load per date.
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

        # Pre-warm: load MSport homepage to set cookies/session
        try:
            await page.goto(MSPORT_BASE, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
        except Exception:
            pass

        # Scrape today + next 6 days
        today = datetime.now()
        for day_offset in range(7):
            if len(results) >= max_matches:
                break
            target_date = today + timedelta(days=day_offset)
            date_str = target_date.strftime("%Y-%m-%d")
            is_today = (day_offset == 0)

            day_results = await _scrape_date_via_api(
                page, date_str, is_today, seen, max_matches - len(results)
            )
            results.extend(day_results)

        await browser.close()

    print(f"  [MSport] Done - {len(results)} matches total")
    return results


async def main():
    """Main execution function."""
    matches = await scrape_msport(max_matches=200)
    print(json_module.dumps(matches, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
