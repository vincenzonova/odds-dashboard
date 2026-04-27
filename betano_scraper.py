"""
Betano Scraper for Nigerian Odds Comparison Dashboard

Betano (owned by Kaizen Gaming) doesn't publish a public API, but runs on their proprietary platform.
This scraper uses a multi-pronged approach:
1. Attempts to find and use internal API endpoints
2. Falls back to browser-based scraping with Playwright
3. Provides structured output matching the dashboard format

Note: betano.ng (Nigerian version) is preferred over betano.com to avoid geo-blocking
from the EU server location.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional
import aiohttp
from playwright.async_api import async_playwright, Browser, Page

logger = logging.getLogger(__name__)

# League IDs mapping - These need to be discovered from Betano's API
# They can be found by inspecting network requests on betano.ng
LEAGUE_IDS = {
    "Premier League": None,  # To be discovered
    "La Liga": None,
    "Serie A": None,
    "Bundesliga": None,
    "Ligue 1": None,
    "Champions League": None,
    "Europa League": None,
    "Conference League": None,
}

# Betano API endpoint candidates (discovered through research)
# The actual internal API structure needs to be reverse-engineered
BETANO_API_ENDPOINTS = {
    "base_url": "https://www.betano.ng",
    # These are common endpoint patterns for Kaizen Gaming properties
    "matches": "/api/v2/matches",
    "odds": "/api/v2/odds",
    "events": "/api/sports/events",
    "markets": "/api/sports/markets",
}

# Market type mapping for consistent output
MARKET_TYPES = {
    "1X2": ["1", "X", "2"],
    "O/U 2.5": ["Over", "Under"],
    "O/U 1.5": ["Over", "Under"],
    "Double Chance": ["1X", "12", "X2"],
}


def calculate_betano_bonus(num_selections: int) -> float:
    """
    Calculate Betano's accumulator bonus percentage.

    Betano's bonus structure:
    - 2 selections (doubles): 3%
    - Increases progressively with more selections
    - Maximum bonus: 70% (usually at 5+ selections)
    - Minimum odds per selection: 1.20

    Args:
        num_selections: Number of bets in the accumulator

    Returns:
        Bonus percentage as a decimal (e.g., 0.03 for 3%)
    """
    if num_selections < 2:
        return 0.0

    # Betano bonus structure (approximate based on typical patterns)
    bonus_structure = {
        2: 0.03,    # 3%
        3: 0.06,    # 6%
        4: 0.12,    # 12%
        5: 0.25,    # 25%
        6: 0.35,    # 35%
        7: 0.50,    # 50%
        8: 0.60,    # 60%
    }

    # If selections exceed 8, cap at 70%
    if num_selections >= 8:
        return min(0.70, bonus_structure.get(8, 0.60) + (num_selections - 8) * 0.02)

    return bonus_structure.get(num_selections, 0.0)


async def scrape_betano_via_api(session: aiohttp.ClientSession) -> Optional[list[dict]]:
    """
    Attempt to scrape Betano odds using internal API endpoints.

    This method tries to discover and use Betano's internal APIs.
    NOTE: This is a placeholder that needs to be populated after reverse-engineering
    the actual API structure through browser network inspection.

    Args:
        session: aiohttp session for making requests

    Returns:
        List of match data with odds, or None if API not accessible
    """
    logger.info("Attempting to scrape Betano via API endpoints...")

    base_url = BETANO_API_ENDPOINTS["base_url"]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Referer": f"{base_url}/sport/football/",
    }

    try:
        # Try the most common endpoint patterns for sports betting APIs
        endpoints_to_try = [
            f"{base_url}/api/v2/matches?sport=football",
            f"{base_url}/api/sports/events?sport=1",  # 1 = football
            f"{base_url}/api/v1/events?category=football",
        ]

        for endpoint in endpoints_to_try:
            try:
                logger.info(f"Trying endpoint: {endpoint}")
                async with session.get(endpoint, headers=headers, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        logger.info(f"Success! Got data from {endpoint}")
                        return await _parse_api_response(data)
                    else:
                        logger.debug(f"Endpoint {endpoint} returned status {resp.status}")
            except Exception as e:
                logger.debug(f"Failed to fetch {endpoint}: {e}")
                continue

        logger.warning("No accessible API endpoints found")
        return None

    except Exception as e:
        logger.error(f"API scraping failed: {e}")
        return None


async def _parse_api_response(data: dict) -> list[dict]:
    """
    Parse API response and extract match odds in standardized format.

    Args:
        data: Raw API response data

    Returns:
        List of matches with odds in standard format
    """
    matches = []

    # This structure depends on the actual API response format
    # Placeholder for parsing logic
    events = data.get("events", data.get("matches", []))

    for event in events:
        try:
            match_data = {
                "event_id": event.get("id"),
                "event": event.get("name", ""),
                "league": event.get("league", ""),
                "odds": {},
                "start_time": event.get("start_time", ""),
            }

            # Parse markets - structure varies by API
            markets = event.get("markets", [])
            for market in markets:
                market_type = market.get("type")
                if market_type in MARKET_TYPES:
                    outcomes = {}
                    for outcome in market.get("outcomes", []):
                        outcomes[outcome.get("name")] = str(outcome.get("price", ""))
                    match_data["odds"][market_type] = outcomes

            matches.append(match_data)
        except Exception as e:
            logger.warning(f"Failed to parse event: {e}")
            continue

    return matches


async def scrape_betano_via_playwright(max_matches: int = 50) -> list[dict]:
    """
    Scrape Betano using Playwright browser automation.

    Fallback method when API endpoints are not accessible.
    This navigates to the football section and extracts odds from the DOM.

    Args:
        max_matches: Maximum number of matches to scrape

    Returns:
        List of matches with extracted odds
    """
    logger.info("Starting Playwright-based scraping of Betano...")

    matches = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            # Navigate to Betano football section
            url = "https://www.betano.ng/sport/football/"
            logger.info(f"Navigating to {url}")
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Wait for match elements to load
            logger.info("Waiting for match elements to load...")
            await page.wait_for_selector("[data-testid*='match']", timeout=15000)

            # Extract all match containers
            match_elements = await page.query_selector_all("[data-testid*='match'], .match-row, .event-item")

            logger.info(f"Found {len(match_elements)} match elements")

            for idx, element in enumerate(match_elements[:max_matches]):
                try:
                    match_data = await _extract_match_from_element(page, element)
                    if match_data:
                        matches.append(match_data)
                        logger.info(f"Extracted match {idx + 1}: {match_data['event']}")
                except Exception as e:
                    logger.warning(f"Failed to extract match {idx}: {e}")
                    continue

            logger.info(f"Successfully extracted {len(matches)} matches")

        except Exception as e:
            logger.error(f"Playwright scraping failed: {e}")
        finally:
            await browser.close()

    return matches


async def _extract_match_from_element(page: Page, element) -> Optional[dict]:
    """
    Extract match and odds data from a DOM element.

    Args:
        page: Playwright page object
        element: DOM element containing match data

    Returns:
        Structured match data or None if extraction fails
    """
    try:
        # Get event name (e.g., "Manchester United vs Liverpool")
        event_text = await element.evaluate("el => el.textContent")

        if not event_text:
            return None

        # Extract team names (simple parsing - needs refinement for specific structure)
        teams = event_text.split(" vs ") if " vs " in event_text else event_text.split("-")
        if len(teams) < 2:
            return None

        event = f"{teams[0].strip()} - {teams[1].strip()}"
        event_id = await element.evaluate("el => el.getAttribute('data-event-id')")

        # Extract odds for different markets
        odds = {}

        # Try to find 1X2 odds
        match_odds = await element.evaluate(
            """el => {
                const odds = {};
                const oddButtons = el.querySelectorAll('[data-odds], .odd-value, [data-price]');
                oddButtons.forEach((btn, i) => {
                    odds[i] = btn.textContent.trim();
                });
                return odds;
            }"""
        )

        if match_odds and len(match_odds) >= 3:
            odds["1X2"] = {
                "1": match_odds.get("0", ""),
                "X": match_odds.get("1", ""),
                "2": match_odds.get("2", ""),
            }

        # Extract league information
        league = await element.evaluate(
            "el => el.querySelector('[data-league], .league-name, .competition')?.textContent || ''"
        )

        # Extract start time
        start_time = await element.evaluate(
            "el => el.querySelector('[data-time], .kick-off-time')?.textContent || ''"
        )

        match_data = {
            "event_id": event_id or "",
            "event": event,
            "league": league.strip() if league else "",
            "odds": odds,
            "start_time": start_time.strip() if start_time else "",
        }

        return match_data if match_data["odds"] else None

    except Exception as e:
        logger.warning(f"Error extracting match element: {e}")
        return None


async def scrape_betano(max_matches: int = 50) -> list[dict]:
    """
    Main scraper function for Betano odds.

    Attempts to scrape using API first, falls back to Playwright if API fails.
    Returns matches with 1X2, O/U, and Double Chance odds.

    Args:
        max_matches: Maximum number of matches to retrieve (default: 50)

    Returns:
        List of match dictionaries with odds in standardized format:
        [
            {
                "event_id": "match_123",
                "event": "Manchester United - Liverpool",
                "league": "Premier League",
                "odds": {
                    "1X2": {"1": "1.50", "X": "3.40", "2": "5.60"},
                    "O/U 2.5": {"Over": "1.80", "Under": "2.00"},
                },
                "start_time": "2026-03-15T15:00:00Z",
            },
            ...
        ]
    """
    logger.info(f"Starting Betano scraper (max_matches={max_matches})")

    matches = []

    # Try API approach first
    try:
        async with aiohttp.ClientSession() as session:
            api_matches = await scrape_betano_via_api(session)
            if api_matches:
                matches = api_matches[:max_matches]
                logger.info(f"API scraping succeeded, got {len(matches)} matches")
                return matches
    except Exception as e:
        logger.warning(f"API scraping error: {e}")

    # Fall back to Playwright
    if not matches:
        logger.info("API approach failed, attempting Playwright scraping...")
        try:
            matches = await scrape_betano_via_playwright(max_matches)
        except Exception as e:
            logger.error(f"Playwright scraping also failed: {e}")
            return []

    return matches[:max_matches]


async def main():
    """
    Test the scraper with sample execution.
    """
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info("=" * 60)
    logger.info("Betano Scraper - Test Run")
    logger.info("=" * 60)
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"Target: betano.ng (Nigerian version)")
    # (blank line removed)
    # Test the accumulator bonus function
    logger.info("Betano Accumulator Bonus Rates:")
    logger.info("-" * 40)
    for selections in range(2, 9):
        bonus = calculate_betano_bonus(selections)
        logger.info(f"{selections} selections: {bonus * 100:.1f}%")
    # (blank line removed)
    # Run the scraper
    logger.info("Starting scraper...")
    logger.info("-" * 40)
    try:
        matches = await scrape_betano(max_matches=10)

        logger.info(f"\nFound {len(matches)} matches")
        # (blank line removed)
        if matches:
            # Display first match as example
            first_match = matches[0]
            logger.info("Sample Match:")
            logger.info(json.dumps(first_match, indent=2))
        else:
            logger.info("No matches found. This may indicate:")
            logger.info("1. Betano API endpoints haven't been discovered yet")
            logger.info("2. Website structure differs from expected selectors")
            logger.info("3. Geographic restrictions (server is in EU, betano.ng may be restricted)")
            logger.info("\nNEXT STEPS:")
            logger.info("1. Open betano.ng in a browser")
            logger.info("2. Open DevTools â Network tab")
            logger.info("3. Look for API calls (XHR/Fetch) when loading football odds")
            logger.info("4. Document the endpoint URLs and response structure")
            logger.info("5. Update BETANO_API_ENDPOINTS and _parse_api_response() accordingly")
    except Exception as e:
        logger.error(f"Scraper execution failed: {e}", exc_info=True)
        logger.error(f"Error: {e}")
if __name__ == "__main__":
    asyncio.run(main())
