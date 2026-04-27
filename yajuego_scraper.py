"""
YaJuego Scraper - Pure API (aiohttp, no Playwright).

Calls YaJuego's REST API directly:
  - GetEventsInCouponV2 endpoint per league
  - Returns 1X2, Double Chance, O/U 1.5, 2.5, 3.5 in a single call

No browser needed â fast, lightweight, ~5-10s total.
"""

import logging
import asyncio
import aiohttp
import time
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)



YAJUEGO_API = "https://sports.yajuego.co/desktop/feapi/PalimpsestAjax"

# League SCHID mapping
LEAGUE_IDS = {
    "Premier League": 790,
    "La Liga":        788,
    "Serie A":        791,
    "Bundesliga":     2081,
    "Ligue 1":        2062,
    "Champions League": 589,
    "Europa League":  590,
    "Conference League": 1501,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://sports.yajuego.co/",
    "Origin": "https://sports.yajuego.co",
}

# -- Team name normalization --
TEAM_ALIASES = {
    "atl. madrid": "atletico madrid",
    "atl madrid": "atletico madrid",
    "atletico madrid": "atletico madrid",
    "atletico de madrid": "atletico madrid",
    "man utd": "manchester utd",
    "man united": "manchester utd",
    "manchester united": "manchester utd",
    "man city": "manchester city",
    "spurs": "tottenham",
    "tottenham hotspur": "tottenham",
    "wolves": "wolverhampton",
    "wolverhampton wanderers": "wolverhampton",
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
    "ac milan": "milan",
    "ac milano": "milan",
    "as roma": "roma",
    "ss lazio": "lazio",
    "napoli ssc": "napoli",
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
    "b. dortmund": "dortmund",
    "borussia dortmund": "dortmund",
    "b. monchengladbach": "gladbach",
    "b. m'gladbach": "gladbach",
    "borussia m'gladbach": "gladbach",
    "rb leipzig": "leipzig",
    "paris sg": "psg",
    "paris saint-germain": "psg",
    "paris saint germain": "psg",
    "olympique marseille": "marseille",
    "ol. marseille": "marseille",
    "olympique lyon": "lyon",
    "ol. lyon": "lyon",
    "as monaco": "monaco",
    "brighton & hove albion": "brighton",
    "brighton hove": "brighton",
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
    # Try swapped
    home_sim2 = _team_similarity(home_a, away_b) if away_b else 0
    away_sim2 = _team_similarity(away_a, home_b) if away_a else 0
    if home_sim2 >= threshold and away_sim2 >= threshold:
        return True
    return False


def _parse_ds_field(ds: str) -> tuple[str, str]:
    """Parse YaJuego DS field like '|AFC Bournemouth||v||Manchester United|' into (home, away)."""
    parts = ds.split("|")
    # Filter out empty strings and 'v'
    teams = [p.strip() for p in parts if p.strip() and p.strip().lower() != "v"]
    if len(teams) >= 2:
        return teams[0], teams[1]
    return ds, ""


def _parse_event_odds(odds_data: dict) -> dict:
    """Parse odds from YaJuego event O field."""
    odds = {}

    # 1X2
    v1 = odds_data.get("S_1X2_1")
    vx = odds_data.get("S_1X2_X")
    v2 = odds_data.get("S_1X2_2")
    if v1 and vx and v2:
        odds["1X2"] = {"1": str(v1), "X": str(vx), "2": str(v2)}

    # Double Chance
    dc_1x = odds_data.get("S_DC_1X")
    dc_12 = odds_data.get("S_DC_12")
    dc_x2 = odds_data.get("S_DC_X2")
    if dc_1x and dc_12 and dc_x2:
        odds["Double Chance"] = {"1X": str(dc_1x), "12": str(dc_12), "X2": str(dc_x2)}

    # Over/Under 2.5
    ou25_o = odds_data.get("S_OU@2.5_O")
    ou25_u = odds_data.get("S_OU@2.5_U")
    if ou25_o and ou25_u:
        odds["O/U 2.5"] = {"Over": str(ou25_o), "Under": str(ou25_u)}

    # Over/Under 1.5
    ou15_o = odds_data.get("S_OU@1.5_O")
    ou15_u = odds_data.get("S_OU@1.5_U")
    if ou15_o and ou15_u:
        odds["O/U 1.5"] = {"Over": str(ou15_o), "Under": str(ou15_u)}

    # Over/Under 3.5
    ou35_o = odds_data.get("S_OU@3.5_O")
    ou35_u = odds_data.get("S_OU@3.5_U")
    if ou35_o and ou35_u:
        odds["O/U 3.5"] = {"Over": str(ou35_o), "Under": str(ou35_u)}

    return odds


async def _fetch_league(session: aiohttp.ClientSession, league_name: str,
                        schid: int) -> list[dict]:
    """Fetch events for a single league via GetEventsInCouponV2 API."""
    url = (
        f"{YAJUEGO_API}/GetEventsInCouponV2"
        f"?SCHID={schid}&DISP=0&MKEY=1"
    )

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                logger.info(f"  [YaJuego] {league_name}: HTTP {resp.status}")
                return []
            data = await resp.json()

            if data.get("R") != "OK":
                logger.info(f"  [YaJuego] {league_name}: R={data.get('R')}")
                return []

            groups = data.get("D", {}).get("G", {})
            events = []

            for gid, group in groups.items():
                raw_events = group.get("E", [])
                for ev in raw_events:
                    ds = ev.get("DS", "")
                    home, away = _parse_ds_field(ds)
                    if not home or not away:
                        continue

                    odds_data = ev.get("O", {})
                    odds = _parse_event_odds(odds_data)

                    if odds and "1X2" in odds:
                        events.append({
                            "home": home,
                            "away": away,
                            "odds": odds,
                        })

            if events:
                logger.info(f"  [YaJuego] {league_name}: {len(events)} events")
            else:
                logger.info(f"  [YaJuego] {league_name}: 0 events")
            return events

    except asyncio.TimeoutError:
        logger.warning(f"  [YaJuego] {league_name}: timeout")
        return []
    except Exception as e:
        logger.error(f"  [YaJuego] {league_name} error: {e}")
        return []


async def scrape_yajuego(max_matches: int = 50, days: int = 7) -> list[dict]:
    """Main entry point â scrape all leagues via pure API calls."""
    start_time = time.time()
    results = []
    seen = set()

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        # Fetch ALL leagues concurrently
        league_tasks = []
        for league_name, schid in LEAGUE_IDS.items():
            league_tasks.append(
                _fetch_league(session, league_name, schid)
            )

        league_results = await asyncio.gather(*league_tasks, return_exceptions=True)

        # Collect all events
        for i, (league_name, _) in enumerate(LEAGUE_IDS.items()):
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
    logger.info(f"  [YaJuego] Done â {len(results)} matches in {elapsed:.1f}s")
    return results


if __name__ == "__main__":
    import json
    data = asyncio.run(scrape_yajuego(max_matches=10))
    logger.info(json.dumps(data, indent=2))