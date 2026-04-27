"""
Betfair Exchange Scraper - Direct Betfair API (free delayed data).

Uses Betfair's official Exchange API directly:
  1. Login via /api/login (username + password + app key)
  2. listMarketCatalogue to find football events
  3. listMarketBook to get back/lay prices

Free delayed key: unlimited requests, 1-180s delay (fine for comparison).
"""

import logging
import asyncio
import aiohttp
import os
import time
from difflib import SequenceMatcher


# Betfair credentials from environment variables
BETFAIR_USERNAME = os.getenv("BETFAIR_USERNAME", "")
BETFAIR_PASSWORD = os.getenv("BETFAIR_PASSWORD", "")
BETFAIR_APP_KEY = os.getenv("BETFAIR_APP_KEY", "")

BETFAIR_LOGIN_URL = "https://identitysso-cert.betfair.com/api/login"
BETFAIR_LOGIN_URL_NOCERT = "https://identitysso.betfair.com/api/login"
BETFAIR_API_URL = "https://api.betfair.com/exchange/betting/rest/v1.0"

# Football event type ID
FOOTBALL_EVENT_TYPE_ID = "1"

# Competition IDs for major leagues
COMPETITION_IDS = {
    "Premier League": "10932509",
    "La Liga": "117",
    "Serie A": "81",
    "Bundesliga": "59",
    "Ligue 1": "55",
    "Champions League": "228",
    "Europa League": "2005",
    "Conference League": "12801",
}

# Market type keys
MARKET_1X2 = "MATCH_ODDS"
MARKET_OU25 = "OVER_UNDER_25"
MARKET_OU15 = "OVER_UNDER_15"
MARKET_OU35 = "OVER_UNDER_35"

# -- Team name normalization --
TEAM_ALIASES = {
    "atl. madrid": "atletico madrid",
    "atl madrid": "atletico madrid",
    "atletico madrid": "atletico madrid",
    "atletico de madrid": "atletico madrid",
    "club atletico de madrid": "atletico madrid",
    "man utd": "manchester utd",
    "man united": "manchester utd",
    "manchester united": "manchester utd",
    "man city": "manchester city",
    "spurs": "tottenham",
    "tottenham hotspur": "tottenham",
    "wolves": "wolverhampton",
    "wolverhampton wanderers": "wolverhampton",
    "wolverhampton wanderers fc": "wolverhampton",
    "newcastle utd": "newcastle",
    "newcastle united": "newcastle",
    "west ham utd": "west ham",
    "west ham united": "west ham",
    "nott forest": "nottingham forest",
    "nott'm forest": "nottingham forest",
    "nottm forest": "nottingham forest",
    "crystal palace fc": "crystal palace",
    "inter milan": "inter",
    "inter milano": "inter",
    "internazionale": "inter",
    "fc internazionale milano": "inter",
    "ac milan": "milan",
    "ac milano": "milan",
    "as roma": "roma",
    "ss lazio": "lazio",
    "ssc napoli": "napoli",
    "atalanta bc": "atalanta",
    "real sociedad": "r. sociedad",
    "celta vigo": "celta",
    "rc celta": "celta",
    "rayo vallecano": "rayo",
    "real betis": "betis",
    "fc barcelona": "barcelona",
    "real madrid cf": "real madrid",
    "bayern munich": "bayern",
    "bayern munchen": "bayern",
    "fc bayern munich": "bayern",
    "borussia dortmund": "dortmund",
    "borussia monchengladbach": "gladbach",
    "rb leipzig": "leipzig",
    "paris saint-germain": "psg",
    "paris saint germain": "psg",
    "olympique marseille": "marseille",
    "olympique de marseille": "marseille",
    "olympique lyon": "lyon",
    "olympique lyonnais": "lyon",
    "as monaco": "monaco",
    "brighton and hove albion": "brighton",
    "brighton & hove albion": "brighton",
    "afc bournemouth": "bournemouth",
}


def _normalize_team(name: str) -> str:
    n = name.lower().strip()
    for suffix in [" fc", " cf", " sc", " ssc", " bc", " afc"]:
        if n.endswith(suffix):
            n = n[:-len(suffix)].strip()
    return TEAM_ALIASES.get(n, n)


def _split_teams(event_name: str) -> tuple[str, str]:
    parts = event_name.split(" - ", 1)
    if len(parts) == 2:
        return _normalize_team(parts[0]), _normalize_team(parts[1])
    parts = event_name.split(" v ", 1)
    if len(parts) == 2:
        return _normalize_team(parts[0]), _normalize_team(parts[1])
    return _normalize_team(event_name), ""


def _team_similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    return SequenceMatcher(None, a, b).ratio()


def fuzzy_match(name_a: str, name_b: str, threshold: float = 0.70) -> bool:
    home_a, away_a = _split_teams(name_a)
    home_b, away_b = _split_teams(name_b)
    if not home_a or not home_b:
        return False
    home_sim = _team_similarity(home_a, home_b)
    away_sim = _team_similarity(away_a, away_b) if away_a and away_b else 0
    if home_sim >= threshold and away_sim >= threshold:
        return True
    home_sim2 = _team_similarity(home_a, away_b) if away_b else 0
    away_sim2 = _team_similarity(away_a, home_b) if away_a else 0
    if home_sim2 >= threshold and away_sim2 >= threshold:
        return True
    return False


async def _betfair_login(session: aiohttp.ClientSession) -> str:
    """Login to Betfair and return session token (SSOID)."""
    headers = {
        "X-Application": BETFAIR_APP_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "username": BETFAIR_USERNAME,
        "password": BETFAIR_PASSWORD,
    }

    try:
        async with session.post(
            BETFAIR_LOGIN_URL_NOCERT,
            headers=headers,
            data=data,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            result = await resp.json()
            if result.get("status") == "SUCCESS":
                token = result.get("token", "")
                logger.info(f"  [Betfair] Login successful")
                return token
            else:
                error = result.get("error", "Unknown error")
                logger.error(f"  [Betfair] Login failed: {error}")
                return ""
    except Exception as e:
        logger.error(f"  [Betfair] Login error: {e}")
        return ""


async def _betfair_api_call(session: aiohttp.ClientSession, token: str,
                            method: str, params: dict) -> dict:
    """Make a Betfair Exchange API call."""
    headers = {
        "X-Application": BETFAIR_APP_KEY,
        "X-Authentication": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    url = f"{BETFAIR_API_URL}/{method}/"

    try:
        async with session.post(
            url,
            headers=headers,
            json={"filter": params} if method == "listMarketCatalogue" else params,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.info(f"  [Betfair] API {method}: HTTP {resp.status} - {text[:200]}")
                return {}
            return await resp.json()
    except Exception as e:
        logger.error(f"  [Betfair] API {method} error: {e}")
        return {}


async def _fetch_competition_markets(session: aiohttp.ClientSession, token: str,
                                     league_name: str, comp_id: str) -> list[dict]:
    """Fetch Match Odds markets for a competition."""
    params = {
        "eventTypeIds": [FOOTBALL_EVENT_TYPE_ID],
        "competitionIds": [comp_id],
        "marketTypeCodes": [MARKET_1X2],
        "maxResults": "100",
        "sort": "FIRST_TO_START",
    }

    # listMarketCatalogue needs special format
    headers = {
        "X-Application": BETFAIR_APP_KEY,
        "X-Authentication": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    body = {
        "filter": {
            "eventTypeIds": [FOOTBALL_EVENT_TYPE_ID],
            "competitionIds": [comp_id],
            "marketTypeCodes": [MARKET_1X2],
        },
        "maxResults": "100",
        "sort": "FIRST_TO_START",
        "marketProjection": ["EVENT", "RUNNER_DESCRIPTION", "COMPETITION"],
    }

    url = f"{BETFAIR_API_URL}/listMarketCatalogue/"

    try:
        async with session.post(
            url, headers=headers, json=body,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.info(f"  [Betfair] {league_name} catalogue: HTTP {resp.status}")
                return []
            markets = await resp.json()

            if not isinstance(markets, list) or not markets:
                logger.info(f"  [Betfair] {league_name}: 0 markets")
                return []

            # Now get prices for all these markets
            market_ids = [m["marketId"] for m in markets]

            price_body = {
                "marketIds": market_ids,
                "priceProjection": {
                    "priceData": ["EX_BEST_OFFERS"],
                },
            }

            url2 = f"{BETFAIR_API_URL}/listMarketBook/"
            async with session.post(
                url2, headers=headers, json=price_body,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp2:
                if resp2.status != 200:
                    logger.info(f"  [Betfair] {league_name} prices: HTTP {resp2.status}")
                    return []
                books = await resp2.json()

            # Build price lookup
            price_map = {}
            if isinstance(books, list):
                for book in books:
                    mid = book.get("marketId", "")
                    runners = book.get("runners", [])
                    price_map[mid] = runners

            # Parse events
            events = []
            for market in markets:
                mid = market.get("marketId", "")
                event_info = market.get("event", {})
                home_name = ""
                away_name = ""
                event_name = event_info.get("name", "")

                # Get runner names
                runners_desc = market.get("runners", [])
                runner_names = {}
                for r in runners_desc:
                    sid = r.get("selectionId")
                    rname = r.get("runnerName", "")
                    runner_names[sid] = rname
                    # Betfair uses "The Draw" for draw
                    if rname.lower() not in ["the draw", "draw"]:
                        if not home_name:
                            home_name = rname
                        else:
                            away_name = rname

                if not home_name or not away_name:
                    continue

                # Get prices
                runners_prices = price_map.get(mid, [])
                odds_1x2 = {}
                for rp in runners_prices:
                    sid = rp.get("selectionId")
                    rname = runner_names.get(sid, "")
                    back_prices = rp.get("ex", {}).get("availableToBack", [])
                    if back_prices:
                        best_back = back_prices[0].get("price")
                        if best_back:
                            if rname.lower() in ["the draw", "draw"]:
                                odds_1x2["X"] = str(best_back)
                            elif rname == home_name:
                                odds_1x2["1"] = str(best_back)
                            elif rname == away_name:
                                odds_1x2["2"] = str(best_back)

                if len(odds_1x2) == 3:
                    events.append({
                        "home": home_name,
                        "away": away_name,
                        "odds": {"1X2": odds_1x2},
                    })

            if events:
                logger.info(f"  [Betfair] {league_name}: {len(events)} events")
            else:
                logger.info(f"  [Betfair] {league_name}: 0 events")
            return events

    except asyncio.TimeoutError:
        logger.warning(f"  [Betfair] {league_name}: timeout")
        return []
    except Exception as e:
        logger.error(f"  [Betfair] {league_name} error: {e}")
        return []


async def scrape_betfair(max_matches: int = 50, days: int = 7) -> list[dict]:
    """Main entry point â scrape Betfair Exchange odds via direct API."""
    start_time = time.time()
    results = []
    seen = set()

    if not BETFAIR_USERNAME or not BETFAIR_PASSWORD or not BETFAIR_APP_KEY:
        logger.info("  [Betfair] Missing credentials (BETFAIR_USERNAME/PASSWORD/APP_KEY) â skipping")
        return results

    async with aiohttp.ClientSession() as session:
        # Step 1: Login
        token = await _betfair_login(session)
        if not token:
            return results

        # Step 2: Fetch all leagues concurrently
        league_tasks = []
        for league_name, comp_id in COMPETITION_IDS.items():
            league_tasks.append(
                _fetch_competition_markets(session, token, league_name, comp_id)
            )

        league_results = await asyncio.gather(*league_tasks, return_exceptions=True)

        # Collect all events
        for i, (league_name, _) in enumerate(COMPETITION_IDS.items()):
            if isinstance(league_results[i], list):
                for event in league_results[i]:
                    home = event["home"]
                    away = event["away"]
                    key = f"{home}-{away}"
                    if key not in seen and len(results) < max_matches:
                        seen.add(key)
                        results.append({
                            "event_id": key,
                            "event": f"{home} - {away}",
                            "league": league_name,
                            "odds": event["odds"],
                        })

    elapsed = time.time() - start_time
    logger.info(f"  [Betfair] Done â {len(results)} matches in {elapsed:.1f}s")
    return results


if __name__ == "__main__":
    import json

logger = logging.getLogger(__name__)

    data = asyncio.run(scrape_betfair(max_matches=10))
    logger.info(json.dumps(data, indent=2))