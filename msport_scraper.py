"""
MSport (msport.com) odds scraper for Nigerian odds comparison dashboard.

MSport is one of Africa's largest sports betting platforms with a focus on the Nigerian market.
This scraper extracts football odds for the major leagues and competitions.

NOTE: MSport does not publicly document its API endpoints. This scraper uses patterns
discovered through network inspection. The endpoints below are placeholders that need to be
verified by observing network requests via browser DevTools.
"""

import asyncio
import aiohttp
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# League IDs - PLACEHOLDER: These need to be discovered from MSport's API
# Typically found by inspecting network requests on the website
LEAGUE_IDS = {
    "Premier League": "1",  # English Premier League
    "La Liga": "2",  # Spanish La Liga
    "Serie A": "3",  # Italian Serie A
    "Bundesliga": "4",  # German Bundesliga
    "Ligue 1": "5",  # French Ligue 1
    "Champions League": "39",  # UEFA Champions League
    "Europa League": "40",  # UEFA Europa League
    "Conference League": "94",  # UEFA Conference League
}

# Common market IDs used by many betting platforms
# These are placeholders - MSport's actual IDs may differ
MARKET_TYPES = {
    "1X2": "1",  # Win/Draw/Loss
    "O/U 2.5": "2",  # Over/Under 2.5 goals
    "O/U 1.5": "3",  # Over/Under 1.5 goals
    "Double Chance": "4",  # Double chance betting
}


@dataclass
class MSportOdds:
    """Data class for MSport odds"""
    event_id: str
    event: str
    league: str
    odds: Dict[str, Dict[str, str]]
    start_time: str
    bookmaker: str = "MSport"

    def to_dict(self) -> dict:
        return asdict(self)


def calculate_msport_bonus(num_selections: int) -> float:
    """
    Calculate MSport accumulator bonus percentage based on number of selections.

    MSport bonus structure:
    - 1-3 folds: 0% (no bonus)
    - 4-5 folds: 5%
    - 6-7 folds: 10%
    - 8-9 folds: 15%
    - 10 folds: 33%
    - 15 folds: 50%
    - 20 folds: 80%
    - 25 folds: 130%
    - 30+ folds: 180% (max)

    Minimum odds per selection: 1.20

    Args:
        num_selections: Number of selections in the accumulator

    Returns:
        Bonus percentage as decimal (e.g., 0.05 for 5%)
    """
    if num_selections < 4:
        return 0.0
    elif num_selections == 4:
        return 0.05
    elif num_selections <= 5:
        return 0.05
    elif num_selections <= 7:
        return 0.10
    elif num_selections <= 9:
        return 0.15
    elif num_selections == 10:
        return 0.33
    elif num_selections <= 14:
        return 0.33
    elif num_selections <= 19:
        return 0.50
    elif num_selections <= 24:
        return 0.80
    elif num_selections <= 29:
        return 1.30
    else:  # 30+
        return 1.80


class MSportScraper:
    """
    Scraper for MSport football odds.

    IMPORTANT: MSport's actual API endpoints need to be discovered by:
    1. Opening https://www.msport.com/ng/sport/football in a browser
    2. Opening Chrome DevTools > Network tab
    3. Looking for XHR/Fetch requests to find the actual API URLs
    4. Common patterns: /api/v1/sports, /api/fixtures, /api/odds, /api/matches
    """

    # Placeholder API endpoints - MUST be updated with actual endpoints
    BASE_URLS = {
        "main": "https://www.msport.com/api",
        "odds": "https://api.msport.com/api/v1",
        "fixtures": "https://api.msport.com/api/v1/fixtures",
    }

    def __init__(self, timeout: int = 10):
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: Optional[aiohttp.ClientSession] = None
        self.min_odds = 1.20  # MSport's minimum odds per selection

    async def __aenter__(self):
       """Async context manager entry"""
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept": "application/json",
            "Referer": "https://www.msport.com/ng/sport/football",
        }
        self.session = aiohttp.ClientSession(timeout=self.timeout, headers=headers)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
       """Async context manager exit"""
        if self.session:
            await self.session.close()

    async def _fetch(url: str, params: Dict[str, Any] = None) -> Optional[Dict]:
        """
        Fetch data from URL with error handling.

        Args:
            url: URL to fetch
            params: Query parameters

        Returns:
            Parsed JSON response or None on error
        """
        if not self.session:
            logger.error("Session not initialized. Use async with MSportScraper()...")
            return None

        try:
            logger.info(f"Fetching: {url}")
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 403:
                    logger.warning(
                        f"Access forbidden (403). This API may be geo-blocked "
                        f"or require authentication. URL: {url}"
                    )
                elif response.status == 404:
                    logger.warning(f"Endpoint not found (404): {url}")
                else:
                    logger.warning(
                        f"HTTP {response.status} from {url}. "
                        f"Response: {await response.text()}"
                    )
                return None
        except asyncio.TimeoutError:
            logger.error(f"Request timeout for {url}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"Network error fetching {url}: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response from {url}: {e}")
            return None

    async def _scrape_football_matches(
        self, league_id: str, league_name: str
    ) -> List[MSportOdds]:
        """
        Scrape football matches and odds for a specific league.

        ENDPOINT NOTE: The actual endpoint path needs to be discovered.
        Common patterns to check:
        - /api/v1/sports/{sport_id}/leagues/{league_id}/matches
        - /api/v1/fixtures?league={league_id}&sport=football
        - /api/matches?leagueId={league_id}
        - /api/v1/events?league_id={league_id}&status=upcoming

        Args:
            league_id: League identifier from LEAGUE_IDS
            league_name: Human-readable league name

        Returns:
            List of MSportOdds objects
        """
        odds_list = []

        # Placeholder endpoints - replace with actual discovered endpoints
        endpoints_to_try = [
            f"{self.BASE_URLS['fixtures']}?league_id={league_id}&sport=football&status=upcoming",
            f"{self.BASE_URLS['odds']}/matches?league={league_id}",
            f"{self.BASE_URLS['main']}/sports/1/leagues/{league_id}/matches",
        ]

        for endpoint in endpoints_to_try:
            logger.info(f"Trying endpoint: {endpoint}")
            data = await self._fetch(endpoint)

            if data:
                # Parse response based on actual data structure
                # This is a placeholder - adjust based on actual API response
                matches = self._parse_matches(data, league_name)
                odds_list.extend(matches)
                break  # Success - don't try other endpoints
            else:
                logger.info(f"Endpoint returned no data: {endpoint}")

        return odds_list

    def _parse_matches(self, data: Dict[str, Any], league_name: str) -> List[MSportOdds]:
        """
        Parse match data from API response.

        IMPORTANT: This parser needs to be adjusted based on actual MSport API response format.

        Typical structures seen:
        {
            "data": [
                {
                    "id": "match_id",
                    "home_team": "Team A",
                    "away_team": "TeaM  B "
              ick_off_time": "2026-03-15T15:00:00Z",
                    "odds": {
                      "1X2": [
                          {"type": "1", "value": "1.50"},
                          {"type": "X", "value": "3.40"},
                          {"type": "2", "value": "5.60"}
                      ]
                    }
                }
            ]
        }

        Args:
            data: Parsed JSON response from API
            league_name: League name for categorization

        Returns:
            List of MSportOdds objects
        """
        matches = []

        # Try common response structures
        matches_data = None
        if isinstance(data, dict):
            # Check for common wrapper keys
            for key in ["data", "matches", "fixtures", "events", "results"]:
                if key in data:
                    matches_data = data[key]
                    break

        if not matches_data:
            logger.warning(f"Could not find matches in response: {data.keys()}")
            return matches

        if not isinstance(matches_data, list):
            matches_data = [matches_data]

        for match in matches_data:
            try:
                # Extract match details - adjust field names based on actual API
                match_id = str(match.get("id") or match.get("match_id") or "")
                home = match.get("home_team", match.get("home", ""))
                away = match.get("away_team", match.get("away", ""))
                kick_off = match.get("kick_off_time", match.get("start_time", ""))

                if not match_id or not home or not away:                    logger.debug(f"Skipping incomplete match: {match}")
                    continue

                event_name = f"{home} - {away}"

                # Extract odds - adjust based on actual API structure
                odds = self._extract_odds(match.get("odds", {}))

                if odds:
                    msport_odds = MSportOdds(
                        event_id=match_id,
                        event=event_name,
                        league=league_name,
                        oddsOdds,
                        start_time=kick_off,
                    )
                    matches.append(msport_odds)

            except (KeyError, ValueError, TypeError) as e:
                logger.debug(f"Error parsing match {match.get('id')}: {e}")
                continue

        return matches

    def _extract_odds(self, odds_data: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
        """
        Extract odds from match odds data.

        Supports these market types:
        - 1X2: Home (1), Draw (X), Away (2)
        - O/U 2.5: Over 2.5 goals, Under 2.5 goals
        - O/U 1.5: Over 1.5 goals, Under 1.5 goals
        - Double Chance: 1X, 12, X2

        Args:
            odds_data: Raw odds data from API

        Returns:
            Structured odds dictionary
        """
        extracted = {}

        # 1X2 odds
        if "1X2" in odds_data or "match_odds" in odds_data:
            one_x_two = odds_data.get("1X2") or odds_data.get("match_odds", {})
            if isinstance(one_x_two, dict):
                extracted["1X2"] = {
                    "1": str(one_x_two.get("1") or one_x_two.get("home", "")),
                    "X": str(one_x_two.get("X") or one_x_two.get("draw", "")),
                    "2": str(one_x_two.get("2") or one_x_two.get("away", "")),
                }

        # Over/Under 2.5
        if "O/U 2.5" in odds_data or "goals_2_5" in odds_data:
            ou_2_5 = odds_data.get("O/U 2.5") or odds_data.get("goals_2_5", {})
            if isinstance(ou_2_5, dict):
                extracted["O/U 2.5"] = {
                    "Over": str(ou_2_5.get("Over") or ou_2_5.get("over", "")),
                    "Under": str(ou_2_5.get("Under") or ou_2_5.get("under", "")),
                }

        # Over/Under 1.5
        if "O/U 1.5" in odds_data or "goals_1_5" in odds_data:
            ou_1_5 = odds_data.get("O/U 1.5") or odds_data.get("goals_1_5", {})
            if isinstance(ou_1_5, dict):
                extracted["O/U 1.5"] = {
                    "Over": str(ou_1_5.get("Over") or ou_1_5.get("over", "")),
                    "Under": str(ou_1_5.get("Under") or ou_1_5.get("under", "")),
                }

        # Double Chance
        if "Double Chance" in odds_data or "double_chance" in odds_data:
            dc = odds_data.get("Double Chance") or odds_data.get("double_chance", {})
            if isinstance(dc, dict):
                extracted["Double Chance"] = {
                    "1X": str(dc.get("1X") or dc.get("12", "")),
                    "12": str(dc.get("12") or dc.get("12", "")),
                    "X2": str(dc.get("X2") or dc.get("x6", "")),
                }

        return extracted

    async def scrape_all_leagues(self, max_matches: int = 50) -> List[MSportOdds]:
        """
        Scrape football matches and odds from all configured leagues.

        Args:
            max_matches: Maximum number of total matches to return (across all leagues)

        Returns:
            List of MSportOdds objects
        """
        all_odds = []
        matches_per_league = max([max_matches // len(LEAGUE_IDS), 1]

        logger.info(f"Starting MSport scrape for {len(LEAGUE_IDS)} leagues")

        for league_name, league_id in LEAGUE_IDS.items():
            logger.info(f"Scraping {league_name} (ID: {league_id})")

            league_odds = await self._scrape_football_matches(league_id, league_name)

            # Limit matches per league
            league_odds = league_odds[:matches_per_league]
            all_odds.extend(league_odds)

            # Check if we've reached max_matches
            if len(all_odds) >= max_matches:
                all_odds = all_odds[:max_matches]
                break

            # Rate limiting - be respectful to the server
            await asyncio.sleep(1)

        logger.info(f"Completed MSport scrape: {len([all_odds])} matches found")
        return all_odds


async def scrape_msport(max_matches: int = 50) -> List[dict]:
    """
    Main entry point for scraping MSport odds,

    This function provides a simple async interface to scrape football odds from MSport.

    Args:
        max_matches: Maximum number of matches to scrape (default: 50)

    Returns:
        List of dictionaries containing match odds in the format:
        {
            "event_id): str,
            "event": "Home - Away",
            "league": "LeaM
ne Name",
            "odds": {
                "1X2": {"1": "1.50", "X": "3.40", "2": "5.60"},
                "O/U 2.5": {"Over": "1.80", "Under": "2.00"},
                "O/U 1.5": {"Over": "1.55", "Under": "2.30"},
                "Double Chance": {"1X": "1.35", "12": "2.10", "X2": "3.80"}
            },
            "start_time": "2026-03-15T15:00:00Z",
            "bookmaker": "MSport"
        }

    Example:
        >>> odds = await scrape_msport(max_matches=25)
        >>> for match in odds:
        ...     print(f"{match['event']} - {match['league']}")
        ...     print(f"  1X2: {match['odds'].get('1X2')}")
    """
    async with MSportScraper() as scraper:
        odds = await scraper.scrape_all_leagues(max_matches=max_matches)
        return [o.to_dict() for o in odds]


# ============================================================================
# DEVELOPMENT & TESTING NOTES
# ============================================================================
#
# To discover MSport's actual API endpoints:
#
# 1. Open https://www.msport.com/ng/sport/football in Chrome
# 2. Press F12 to open DevTools
# 3. Go to the Network tab
# 4. Filter by XHR/Fetch
# 5. Scroll the page and look at network requests
# 6. Look for URLs containing:
#    - /api/
#    - /fixtures
#    - /odds
#    - /sports
#    - /leagues
#    - /matches
#    - /events
#
# 7. Click on a request and check:
#    - Request URL and parameters
#    - Response format (JSON structure)
#    - Required headers (authorization, cookies, etc.)
#
# 8. Common MSport API patterns found in similar platforms:
#    - GET /api/v1/sports/football/leagues/{leagueId}/fixtures
#    - GET /api/v1/fixtures?sportId=1&leagueId={leagueId}&status=upcoming
#    - GET /api/v1/events?league={leagueId}&type=football&date_from=today
#
# 9. Update BASE_URLS and endpoint patterns in the scraper
# 10. Test with: python -m asyncio -c "from msport_scraper import scrape_msport; import asyncio; print(asyncio.run(scrape_msport(10)))"
#
# ============================================================================


if __name__ == "__main__":
    # Test the scraper
    print("MSport Scraper Test")
    print("=" * 50)

    async def test():
        try:
            logger.info("Attempting to scrape MSport...")
            odds = await scrape_msport(max_matches=10)

            if odds:
                logger.info(f"Successfully scraped {len(odds)} matches")
                for match in odds[:3]:  # Show first 3
                    print(f"\n{match['event']} ({match['league']})")
                    print(f"  Start: {match['start_time']}")
                    if match["odds"].get("1X2"):
                        print(f"  1X2: {match['odds']['1X2']}")
            else:
                logger.warning(
                    "No matches scraped. API endpoints may need discovery. "
                    "See development notes above."
                )
        except Exception as e:
            logger.error(f"Scrape failed: {e}", exc_info=True)

    asyncio.run(test())
