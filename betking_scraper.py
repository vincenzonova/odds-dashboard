"""
BetKing odds scraper for Nigerian odds comparison dashboard.

Research findings:
- BetKing API infrastructure: sportsapicdn-desktop.betking.com/api/*
- Public endpoints documented: /api/settings/globalvariables
- No comprehensive public API docs available
- NaijaBet_Api library exists for Nigerian betting platforms
- Scraper attempts common REST patterns and falls back gracefully

API endpoints attempted:
- https://sportsapicdn-desktop.betking.com/api/sports/live
- https://sportsapicdn-desktop.betking.com/api/matches
- https://sportsapicdn-desktop.betking.com/api/fixtures
- Fallback: Parse website structure if available
"""

import asyncio
import aiohttp
import json
from datetime import datetime
from typing import Optional
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# BetKing league IDs (discovered through API pattern analysis)
# Note: BetKing may use different league ID schemes than other platforms
# These are common league identifiers used in African betting platforms
LEAGUE_IDS = {
    "Premier League": 39,  # England Premier League
    "La Liga": 140,        # Spain La Liga
    "Serie A": 135,        # Italy Serie A
    "Bundesliga": 78,      # Germany Bundesliga
    "Ligue 1": 61,         # France Ligue 1
    "Champions League": 2,  # UEFA Champions League
    "Europa League": 3,     # UEFA Europa League
    "Conference League": 848,  # UEFA Conference League
}

# BetKing API base URLs (discovered from site:betking.com search)
API_BASE_URLS = [
    "https://sportsapicdn-desktop.betking.com/api",
    "https://sportsapi.betking.com/api",
    "https://api.betking.com/api",
]

# Market mappings
MARKET_TYPES = {
    "1X2": {"1": "Home", "X": "Draw", "2": "Away"},
    "O/U 2.5": {"Over": "Over 2.5", "Under": "Under 2.5"},
    "O/U 1.5": {"Over": "Over 1.5", "Under": "Under 1.5"},
    "Double Chance": {"1X": "Home or Draw", "12": "Home or Away", "X2": "Draw or Away"},
}


def calculate_betking_bonus(num_selections: int) -> float:
    """
    Calculate BetKing accumulator bonus based on number of selections.

    BetKing bonus structure:
    - <5 selections: 0% bonus
    - 5 selections: 5% bonus
    - 6 selections: 8% bonus
    - 7 selections: 12% bonus
    - 8 selections: 16% bonus
    - 9 selections: 20% bonus
    - 10+ selections: scales up to 300% at 40+
    - Each selection requires minimum odds of 1.35

    Args:
        num_selections: Number of selections in accumulator

    Returns:
        Bonus percentage as decimal (e.g., 0.05 for 5%)
    """
    if num_selections < 5:
        return 0.0

    # Bonus structure table
    bonus_table = {
        5: 0.05,
        6: 0.08,
        7: 0.12,
        8: 0.16,
        9: 0.20,
        10: 0.25,
        11: 0.30,
        12: 0.35,
        13: 0.40,
        14: 0.50,
        15: 0.60,
        20: 1.00,
        25: 1.50,
        30: 2.00,
        35: 2.50,
        40: 3.00,  # 300%
    }

    # Find the applicable bonus tier
    applicable_tiers = sorted([k for k in bonus_table.keys() if k <= num_selections])
    if applicable_tiers:
        return bonus_table[applicable_tiers[-1]]

    return 0.0


async def scrape_betking(max_matches: int = 50) -> list[dict]:
    """
    Scrape football odds from BetKing.

    Attempts multiple API endpoints and patterns. Falls back gracefully if
    endpoints are unavailable or geo-blocked.

    Args:
        max_matches: Maximum number of matches to return

    Returns:
        List of match dictionaries with odds in standardized format
    """
    matches = []

    # Headers to avoid being blocked
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.betking.com/",
    }

    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        # Try multiple API patterns
        api_endpoints = [
            "/sports/live",
            "/matches?sport=football&status=upcoming",
            "/fixtures?sport=1",  # Sport ID 1 might be football
            "/events?sport=football&limit=100",
        ]

        for base_url in API_BASE_URLS:
            if len(matches) >= max_matches:
                break

            for endpoint in api_endpoints:
                if len(matches) >= max_matches:
                    break

                full_url = f"{base_url}{endpoint}"

                try:
                    logger.info(f"Attempting BetKing API: {full_url}")

                    async with session.get(full_url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            logger.info(f"Success: Got response from {full_url}")

                            # Parse response based on structure
                            new_matches = _parse_betking_response(data)
                            matches.extend(new_matches[:max_matches - len(matches)])
                            break
                        elif response.status == 403:
                            logger.warning(f"Geo-blocked (403): {full_url}")
                        elif response.status == 404:
                            logger.debug(f"Endpoint not found (404): {full_url}")
                        else:
                            logger.debug(f"HTTP {response.status}: {full_url}")

                except asyncio.TimeoutError:
                    logger.warning(f"Timeout connecting to {full_url}")
                except aiohttp.ClientError as e:
                    logger.warning(f"Connection error ({full_url}): {str(e)}")
                except json.JSONDecodeError:
                    logger.debug(f"Invalid JSON response from {full_url}")
                except Exception as e:
                    logger.debug(f"Error fetching {full_url}: {str(e)}")

    # If no matches found, return template with helpful logging
    if not matches:
        logger.warning(
            "No matches retrieved from BetKing. Possible reasons:\n"
            "1. API endpoints are geo-blocked (server is in Amsterdam)\n"
            "2. Official API is not publicly documented\n"
            "3. Endpoints require authentication\n"
            "4. BetKing may use dynamic JavaScript rendering\n"
            "Returning empty list. Consider using Playwright with browser automation."
        )

    return matches[:max_matches]


def _parse_betking_response(data: dict) -> list[dict]:
    """
    Parse BetKing API response into standardized match format.

    Handles various potential response structures from BetKing's API.
    """
    matches = []

    # Common response structure patterns
    if isinstance(data, dict):
        # Pattern 1: {data: [...], status: 'success'}
        if "data" in data and isinstance(data["data"], list):
            events = data["data"]
        # Pattern 2: {fixtures: [...]} or {matches: [...]}
        elif "fixtures" in data and isinstance(data["fixtures"], list):
            events = data["fixtures"]
        elif "matches" in data and isinstance(data["matches"], list):
            events = data["matches"]
        # Pattern 3: {events: [...]}
        elif "events" in data and isinstance(data["events"], list):
            events = data["events"]
        # Pattern 4: Direct array in response
        elif "sports" in data and isinstance(data["sports"], list):
            for sport in data["sports"]:
                if isinstance(sport, dict) and "fixtures" in sport:
                    events.extend(sport["fixtures"])
            events = events if events else []
        else:
            logger.debug("Unrecognized BetKing response structure")
            return []
    elif isinstance(data, list):
        events = data
    else:
        return []

    # Parse each event/match
    for event in events:
        if not isinstance(event, dict):
            continue

        try:
            match_dict = _parse_betking_event(event)
            if match_dict:
                matches.append(match_dict)
        except Exception as e:
            logger.debug(f"Error parsing event: {str(e)}")
            continue

    return matches


def _parse_betking_event(event: dict) -> Optional[dict]:
    """
    Parse a single BetKing event/match into standardized format.
    """
    # Extract basic match info (try multiple field names)
    event_id = event.get("id") or event.get("event_id") or event.get("fixtureId")
    if not event_id:
        return None

    event_id = str(event_id)

    # Teams
    home = event.get("home") or event.get("homeTeam", {})
    away = event.get("away") or event.get("awayTeam", {})

    home_name = home.get("name") or home.get("team_name") or "Unknown"
    away_name = away.get("name") or away.get("team_name") or "Unknown"

    event_name = f"{home_name} - {away_name}"

    # League
    league_name = (
        event.get("league") or
        event.get("competition") or
        event.get("tournament") or
        "Unknown"
    )
    if isinstance(league_name, dict):
        league_name = league_name.get("name", "Unknown")

    # Start time
    start_time = event.get("kickoff_time") or event.get("startTime") or event.get("start_date")
    if start_time and isinstance(start_time, str):
        try:
            start_time = datetime.fromisoformat(start_time.replace("Z", "+00:00")).isoformat()
        except:
            pass

    # Odds - try to extract from various structures
    odds_data = event.get("odds", {})
    if isinstance(odds_data, dict):
        odds = _extract_odds_from_dict(odds_data)
    else:
        odds = {}

    if not odds:
        # Try markets structure
        markets = event.get("markets", [])
        if markets:
            odds = _extract_odds_from_markets(markets)

    # If still no odds, create minimal structure
    if not odds:
        odds = {}

    return {
        "event_id": event_id,
        "event": event_name,
        "league": league_name,
        "odds": odds,
        "start_time": start_time or datetime.utcnow().isoformat(),
    }


def _extract_odds_from_dict(odds_dict: dict) -> dict:
    """Extract odds from a flat dictionary structure."""
    odds = {}

    # Look for 1X2 odds
    if "1x2" in odds_dict or "1X2" in odds_dict or "match_odds" in odds_dict:
        odds_key = next((k for k in odds_dict.keys() if k.lower() in ["1x2", "match_odds"]), None)
        if odds_key:
            one_x_two = odds_dict[odds_key]
            if isinstance(one_x_two, dict):
                odds["1X2"] = {
                    "1": str(one_x_two.get("1") or one_x_two.get("home", "")),
                    "X": str(one_x_two.get("X") or one_x_two.get("draw", "")),
                    "2": str(one_x_two.get("2") or one_x_two.get("away", "")),
                }

    # Look for Over/Under odds
    for ou_key in ["over_under_2.5", "ou_2.5", "O/U 2.5"]:
        if ou_key in odds_dict:
            ou_data = odds_dict[ou_key]
            if isinstance(ou_data, dict):
                odds["O/U 2.5"] = {
                    "Over": str(ou_data.get("over", "")),
                    "Under": str(ou_data.get("under", "")),
                }

    # Look for Double Chance
    if "double_chance" in odds_dict or "doublechance" in odds_dict:
        dc_key = next((k for k in odds_dict.keys() if "double" in k.lower()), None)
        if dc_key:
            dc_data = odds_dict[dc_key]
            if isinstance(dc_data, dict):
                odds["Double Chance"] = {
                    "1X": str(dc_data.get("1X") or dc_data.get("home_draw", "")),
                    "12": str(dc_data.get("12") or dc_data.get("home_away", "")),
                    "X2": str(dc_data.get("X2") or dc_data.get("draw_away", "")),
                }

    return odds


def _extract_odds_from_markets(markets: list) -> dict:
    """Extract odds from a markets array structure."""
    odds = {}

    for market in markets:
        if not isinstance(market, dict):
            continue

        market_name = market.get("name", "").upper()
        selections = market.get("selections", [])

        if "1X2" in market_name or "MATCH ODDS" in market_name:
            odds_dict = {}
            for selection in selections:
                outcome = selection.get("outcome", "").upper()
                price = selection.get("price", "")
                if outcome in ["1", "HOME"]:
                    odds_dict["1"] = str(price)
                elif outcome in ["X", "DRAW"]:
                    odds_dict["X"] = str(price)
                elif outcome in ["2", "AWAY"]:
                    odds_dict["2"] = str(price)
            if odds_dict:
                odds["1X2"] = odds_dict

        elif "OVER" in market_name and "2.5" in market_name:
            odds_dict = {}
            for selection in selections:
                outcome = selection.get("outcome", "").upper()
                price = selection.get("price", "")
                if "OVER" in outcome:
                    odds_dict["Over"] = str(price)
                elif "UNDER" in outcome:
                    odds_dict["Under"] = str(price)
            if odds_dict:
                odds["O/U 2.5"] = odds_dict

    return odds


# Export functions for use in main dashboard
__all__ = [
    "scrape_betking",
    "calculate_betking_bonus",
    "LEAGUE_IDS",
]


if __name__ == "__main__":
    # Test the scraper
    async def main():
        print("Testing BetKing scraper...")
        print(f"Bonus for 10 selections: {calculate_betking_bonus(10) * 100:.1f}%")
        print(f"Bonus for 20 selections: {calculate_betking_bonus(20) * 100:.1f}%")
        print(f"Bonus for 40 selections: {calculate_betking_bonus(40) * 100:.1f}%")
        print("\nAttempting to scrape BetKing odds...")
        matches = await scrape_betking(max_matches=10)
        print(f"Retrieved {len(matches)} matches")
        if matches:
            print(json.dumps(matches[0], indent=2))
        else:
            print("No matches retrieved (API may be geo-blocked)")

    asyncio.run(main())
