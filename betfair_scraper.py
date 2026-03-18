"""
Betfair Exchange Scraper - via The Odds API (free tier).

Uses the-odds-api.com to fetch Betfair Exchange back odds for football.
Free tier: 500 requests/month. Each league fetch = 1 request.
We fetch 8 leagues per refresh = 8 requests per refresh.

Markets: h2h (1X2), h2h_lay (lay odds), totals (O/U)
"""

import asyncio
import aiohttp
import os
import time
from difflib import SequenceMatcher


# API key from environment variable
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports"

# Sport keys for each league
# The Odds API uses specific sport keys for each competition
SPORT_KEYS = {
    "Premier League":    "soccer_epl",
    "La Liga":           "soccer_spain_la_liga",
    "Serie A":           "soccer_italy_serie_a",
    "Bundesliga":        "soccer_germany_bundesliga",
    "Ligue 1":           "soccer_france_ligue_one",
    "Champions League":  "soccer_uefa_champs_league",
    "Europa League":     "soccer_uefa_europa_league",
    "Conference League": "soccer_uefa_europa_conference_league",
}

HEADERS = {
    "User-Agent": "OddsDashboard/1.0",
    "Accept": "application/json",
}

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
    "leeds utd": "leeds",
    "leeds united": "leeds",
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
    "napoli ssc": "napoli",
    "ssc napoli": "napoli",
    "atalanta bc": "atalanta",
    "real sociedad": "r. sociedad",
    "r sociedad": "r. sociedad",
    "celta vigo": "celta",
    "rc celta": "celta",
    "rayo vallecano": "rayo",
    "real betis": "betis",
    "fc barcelona": "barcelona",
    "real madrid cf": "real madrid",
    "bayern munich": "bayern",
    "bayern munchen": "bayern",
    "fc bayern munich": "bayern",
    "b. dortmund": "dortmund",
    "borussia dortmund": "dortmund",
    "b. monchengladbach": "gladbach",
    "b. m'gladbach": "gladbach",
    "borussia m'gladbach": "gladbach",
    "borussia monchengladbach": "gladbach",
    "rb leipzig": "leipzig",
    "paris sg": "psg",
    "paris saint-germain": "psg",
    "paris saint germain": "psg",
    "olympique marseille": "marseille",
    "ol. marseille": "marseille",
    "olympique de marseille": "marseille",
    "olympique lyon": "lyon",
    "olympique lyonnais": "lyon",
    "ol. lyon": "lyon",
    "as monaco": "monaco",
    "brighton & hove albion": "brighton",
    "brighton hove": "brighton",
    "brighton and hove albion": "brighton",
    "afc bournemouth": "bournemouth",
}


def _normalize_team(name: str) -> str:
    """Normalize a team name for matching."""
    n = name.lower().strip()
    for suffix in [" fc", " cf", " sc", " ssc", " bc", " afc"]:
        if n.endswith(suffix):
            n = n[:-len(suffix)].strip()
    return TEAM_ALIASES.get(n, n)


def _split_teams(event_name: str) -> tuple[str, str]:
    """Split 'Home - Away' into normalized (home, away) tuple."""
    parts = event_name.split(" - ", 1)
    if len(parts) == 2:
        return _normalize_team(parts[0]), _normalize_team(parts[1])
    return _normalize_team(event_name), ""


def _team_similarity(a: str, b: str) -> float:
    """Compare two normalized team names."""
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.85
    return SequenceMatcher(None, a, b).ratio()


def fuzzy_match(name_a: str, name_b: str, threshold: float = 0.70) -> bool:
    """Match two event names by checking BOTH teams individually."""
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


def _parse_betfair_odds(bookmaker_data: dict) -> dict:
    """Parse odds from The Odds API bookmaker response for Betfair."""
    odds = {}

    for market in bookmaker_data.get("markets", []):
        key = market.get("key", "")
        outcomes = market.get("outcomes", [])

        if key == "h2h":
            # 1X2 market
            odds_1x2 = {}
            for o in outcomes:
                name = o.get("name", "")
                price = o.get("price")
                if price is None:
                    continue
                if name == "Draw":
                    odds_1x2["X"] = str(price)
                elif name == bookmaker_data.get("_home", ""):
                    odds_1x2["1"] = str(price)
                elif name == bookmaker_data.get("_away", ""):
                    odds_1x2["2"] = str(price)
                else:
                    # Try to match by position (first=home, last=away)
                    pass
            if len(odds_1x2) == 3:
                odds["1X2"] = odds_1x2

        elif key == "totals":
            # Over/Under market
            over_val = None
            under_val = None
            point = None
            for o in outcomes:
                name = o.get("name", "").lower()
                price = o.get("price")
                pt = o.get("point")
                if price is None:
                    continue
                if name == "over":
                    over_val = str(price)
                    point = pt
                elif name == "under":
                    under_val = str(price)
                    point = pt
            if over_val and under_val and point:
                point_str = str(point)
                if point_str == "2.5":
                    odds["O/U 2.5"] = {"Over": over_val, "Under": under_val}
                elif point_str == "1.5":
                    odds["O/U 1.5"] = {"Over": over_val, "Under": under_val}
                elif point_str == "3.5":
                    odds["O/U 3.5"] = {"Over": over_val, "Under": under_val}

    return odds


async def _fetch_league(session: aiohttp.ClientSession, league_name: str,
                        sport_key: str) -> list[dict]:
    """Fetch Betfair odds for a single league from The Odds API."""
    if not ODDS_API_KEY:
        print(f"  [Betfair] Skipping {league_name}: no ODDS_API_KEY set")
        return []

    url = (
        f"{ODDS_API_BASE}/{sport_key}/odds"
        f"?apiKey={ODDS_API_KEY}"
        f"&regions=uk"
        f"&markets=h2h,totals"
        f"&oddsFormat=decimal"
        f"&bookmakers=betfair_ex_uk"
    )

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status == 401:
                print(f"  [Betfair] {league_name}: Invalid API key")
                return []
            if resp.status == 429:
                print(f"  [Betfair] {league_name}: Rate limited")
                return []
            if resp.status == 422:
                # Sport key not found or no data
                print(f"  [Betfair] {league_name}: No data available (422)")
                return []
            if resp.status != 200:
                print(f"  [Betfair] {league_name}: HTTP {resp.status}")
                return []

            # Check remaining quota from headers
            remaining = resp.headers.get("x-requests-remaining", "?")
            used = resp.headers.get("x-requests-used", "?")

            data = await resp.json()
            events = []

            for event in data:
                home = event.get("home_team", "")
                away = event.get("away_team", "")
                if not home or not away:
                    continue

                # Find Betfair bookmaker data
                for bm in event.get("bookmakers", []):
                    if "betfair" in bm.get("key", "").lower():
                        # Attach home/away for name matching in parser
                        bm["_home"] = home
                        bm["_away"] = away
                        odds = _parse_betfair_odds(bm)
                        if odds and "1X2" in odds:
                            events.append({
                                "home": home,
                                "away": away,
                                "odds": odds,
                            })
                        break

            if events:
                print(f"  [Betfair] {league_name}: {len(events)} events (quota: {used}/{remaining})")
            else:
                print(f"  [Betfair] {league_name}: 0 events")
            return events

    except asyncio.TimeoutError:
        print(f"  [Betfair] {league_name}: timeout")
        return []
    except Exception as e:
        print(f"  [Betfair] {league_name} error: {e}")
        return []


async def scrape_betfair(max_matches: int = 50, days: int = 7) -> list[dict]:
    """Main entry point â scrape Betfair odds via The Odds API."""
    start_time = time.time()
    results = []
    seen = set()

    if not ODDS_API_KEY:
        print("  [Betfair] ODDS_API_KEY not set â skipping Betfair scraper")
        return results

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        # Fetch ALL leagues concurrently
        league_tasks = []
        for league_name, sport_key in SPORT_KEYS.items():
            league_tasks.append(
                _fetch_league(session, league_name, sport_key)
            )

        league_results = await asyncio.gather(*league_tasks, return_exceptions=True)

        # Collect all events
        for i, (league_name, _) in enumerate(SPORT_KEYS.items()):
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
    print(f"  [Betfair] Done â {len(results)} matches in {elapsed:.1f}s")
    return results


if __name__ == "__main__":
    import json
    data = asyncio.run(scrape_betfair(max_matches=10))
    print(json.dumps(data, indent=2))
