import asyncio
import aiohttp
import json
import logging
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass


logger = logging.getLogger(__name__)


LEAGUE_IDS = {
    "Premier League": "pl",
    "La Liga": "la_liga",
    "Serie A": "serie_a",
    "Bundesliga": "bundesliga",
    "Ligue 1": "ligue_1",
    "Champions League": "champions_league",
    "Europa League": "europa_league",
    "Conference League": "conference_league",
}


def calculate_msport_bonus(num_selections: int) -> float:
    """
    Calculate the msport bonus multiplier based on number of selections.

    Args:
        num_selections: Number of selections in the accumulator

    Returns:
        Bonus multiplier as decimal
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


@dataclass
class Match:
    """Data class representing a match."""
    match_id: str
    home_team: str
    away_team: str
    league: str
    kickoff_time: datetime
    odds_1: float
    odds_x: float
    odds_2: float


class MSportScraper:
    """Scraper for msport football/soccer data."""

    def __init__(self, session: Optional[aiohttp.ClientSession] = None):
        """
        Initialize the MSportScraper.

        Args:
            session: Optional aiohttp ClientSession for making requests
        """
        self.session = session
        self.base_url = "https://www.msport.com/api"  # Placeholder - needs discovery
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

    async def _fetch_url(self, url: str) -> Optional[Dict]:
        """
        Fetch content from a URL.

        Args:
            url: URL to fetch

        Returns:
            JSON response or None if request fails
        """
        try:
            async with self.session.get(url, headers=self.headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.warning(f"Failed to fetch {url}: status {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    async def get_matches_by_league(self, league: str) -> List[Dict]:
        """
        Get matches for a specific league.

        Args:
            league: League name from LEAGUE_IDS

        Returns:
            List of match dictionaries
        """
        if league not in LEAGUE_IDS:
            logger.warning(f"Unknown league: {league}")
            return []

        league_id = LEAGUE_IDS[league]
        # Placeholder endpoint - needs discovery
        url = f"{self.base_url}/matches?league_id={league_id}"

        matches = []
        data = await self._fetch_url(url)

        if data and "matches" in data:
            for match in data["matches"]:
                matches.append({
                    "match_id": match.get("id"),
                    "home_team": match.get("home_team"),
                    "away_team": match.get("away_team"),
                    "league": league,
                    "kickoff_time": match.get("kickoff_time"),
                    "odds_1": float(match.get("odds_1", 0.0)),
                    "odds_x": float(match.get("odds_x", 0.0)),
                    "odds_2": float(match.get("odds_2", 0.0)),
                })

        return matches

    async def get_all_matches(self, max_matches: int = 50) -> List[Dict]:
        """
        Get matches from all available leagues.

        Args:
            max_matches: Maximum number of matches to retrieve

        Returns:
            List of match dictionaries
        """
        all_matches = []

        for league in LEAGUE_IDS.keys():
            if len(all_matches) >= max_matches:
                break

            league_matches = await self.get_matches_by_league(league)
            remaining_slots = max_matches - len(all_matches)
            all_matches.extend(league_matches[:remaining_slots])

        return all_matches

    async def get_match_details(self, match_id: str) -> Optional[Dict]:
        """
        Get detailed information for a specific match.

        Args:
            match_id: ID of the match

        Returns:
            Match details dictionary or None
        """
        # Placeholder endpoint - needs discovery
        url = f"{self.base_url}/matches/{match_id}"

        return await self._fetch_url(url)

    async def get_live_odds(self, match_id: str) -> Optional[Dict]:
        """
        Get live odds for a specific match.

        Args:
            match_id: ID of the match

        Returns:
            Odds dictionary or None
        """
        # Placeholder endpoint - needs discovery
        url = f"{self.base_url}/matches/{match_id}/odds"

        return await self._fetch_url(url)


async def scrape_msport(max_matches: int = 50) -> List[dict]:
    """
    Main entry point for scraping msport data.

    Args:
        max_matches: Maximum number of matches to retrieve

    Returns:
        List of match dictionaries
    """
    async with aiohttp.ClientSession() as session:
        scraper = MSportScraper(session=session)
        matches = await scraper.get_all_matches(max_matches=max_matches)
        return matches


async def main():
    """Main execution function."""
    try:
        matches = await scrape_msport(max_matches=50)
        logger.info(f"Retrieved {len(matches)} matches")

        # Example: calculate bonus for different accumulator sizes
        for num_selections in [3, 4, 7, 10, 20, 30]:
            bonus = calculate_msport_bonus(num_selections)
            logger.info(f"Bonus for {num_selections} selections: {bonus:.2f}")

    except Exception as e:
        logger.error(f"Error in main: {e}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    asyncio.run(main())
