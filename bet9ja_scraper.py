"""
Bet9ja Scraper — uses the sports.bet9ja.com JSON API.
No browser automation needed — just plain HTTP requests.
"""
import logging
import asyncio
import aiohttp
from datetime import datetime, timedelta

BET9JA_API = "https://sports.bet9ja.com/desktop/feapi/PalimpsestAjax/GetEventsInGroupV2"

# League name → Bet9ja GROUPID
LEAGUE_IDS = {
    "Premier League": 170880,
    "La Liga": 180928,
    "Serie A": 167856,
    "Bundesliga": 180923,
    "Ligue 1": 950503,
    "Champions League": 1185641,
    "Europa League": 1185689,
    "Conference League": 1946188,
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://sports.bet9ja.com/",
    "sec-ch-ua": '"Chromium";v="120", "Google Chrome";v="120"',
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

# Map API odds keys to our market/sign structure
ODDS_MAPPING = {
    "S_1X2_1":    ("1X2", "1"),
    "S_1X2_X":    ("1X2", "X"),
    "S_1X2_2":    ("1X2", "2"),
    "S_DC_1X":    ("Double Chance", "1X"),
    "S_DC_12":    ("Double Chance", "12"),
    "S_DC_X2":    ("Double Chance", "X2"),
    "S_OU@2.5_O": ("O/U 2.5", "Over"),
    "S_OU@2.5_U": ("O/U 2.5", "Under"),
    "S_OU@1.5_O": ("O/U 1.5", "Over"),
    "S_OU@1.5_U": ("O/U 1.5", "Under"),
}


def _parse_event(event: dict, league_name: str) -> dict | None:
    """Parse a single event from the API response into our format."""
    name = event.get("DS", "")
    if not name:
        return None

    raw_odds = event.get("O", {})
    odds = {}
    for api_key, (market, sign) in ODDS_MAPPING.items():
        val = raw_odds.get(api_key, "")
        if val:
            odds.setdefault(market, {})[sign] = str(val)

    if not odds:
        return None

    result = {
        "event_id": str(event.get("ID", name)),
        "event": name,
        "league": league_name,
        "odds": odds,
        "start_time": event.get("STARTDATE", ""),
    }
    # Extract start time - Bet9ja API uses DA for date string
    start_time = event.get("DA", event.get("DT", ""))
    if start_time:
        result["start_time"] = str(start_time)
    # Detect "Best Price" events (excluded from Multiple Boost bonus)
    is_bp = (
        event.get("BP", False) or event.get("IsBP", False)
        or event.get("BestPrice", False) or event.get("IsBestPrice", False)
        or event.get("PB", False)
    )
    tags = str(event.get("T", "")) + str(event.get("Tags", "")) + str(event.get("Labels", ""))
    if "bestprice" in tags.lower().replace(" ", "") or "best_price" in tags.lower():
        is_bp = True
    if is_bp:
        result["best_price"] = True

    return result


async def scrape_bet9ja(max_matches: int = 50, days: int = 2) -> list[dict]:
    """Fetch odds from sports.bet9ja.com JSON API."""
    results = []
    cutoff = datetime.now() + timedelta(days=days)  # Filter events within date range

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        # First hit the main page to get cookies/session
        try:
            async with session.get("https://sports.bet9ja.com", timeout=aiohttp.ClientTimeout(total=15)):
                pass
        except Exception as e:
            logger.info(f"  [Bet9ja] Session init warning: {e}")
        for league_name, group_id in LEAGUE_IDS.items():

            params = {
                "GROUPID": group_id,
                "DISP": 0,
                "GROUPMARKETID": 1,
                "matches": "true",
            }

            try:
                logger.info(f"  [Bet9ja] Fetching {league_name} (GROUPID={group_id})...")
                async with session.get(
                    BET9JA_API,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        logger.info(f"  [Bet9ja] {league_name}: HTTP {resp.status}")
                        continue

                    data = await resp.json()

                    if data.get("R") != "OK":
                        logger.info(f"  [Bet9ja] {league_name}: API returned {data.get('R')}")
                        continue

                    events = data.get("D", {}).get("E", [])
                    added = 0
                    if events:
                        logger.info(f"  [Bet9ja] Sample keys: {list(events[0].keys())}")
                        logger.info(f"  [Bet9ja] DA={events[0].get('DA','?')} BP={events[0].get('BP','?')}")
                    for ev in events:
                        parsed = _parse_event(ev, league_name)
                        # Filter by date range (lenient: keep events if date can't be parsed)
                        if parsed and parsed.get("start_time"):
                            try:
                                st = str(parsed["start_time"])
                                event_dt = None
                                for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%SZ"):
                                    try:
                                        event_dt = datetime.strptime(st[:19], fmt[:len(fmt)])
                                        break
                                    except ValueError:
                                        continue
                                if event_dt and event_dt > cutoff:
                                    parsed = None  # Beyond date range
                            except Exception:
                                pass  # Keep event if date parsing fails
                        if parsed:
                            results.append(parsed)
                            added += 1
   
                    logger.info(f"  [Bet9ja] {league_name}: +{added} matches")
            except asyncio.TimeoutError:
                logger.warning(f"  [Bet9ja] {league_name}: timeout")
                continue
            except Exception as e:
                logger.error(f"  [Bet9ja] {league_name} error: {e}")
                continue

    logger.info(f"  [Bet9ja] Done — {len(results)} matches total")
    return results[:max_matches]


if __name__ == "__main__":
    import json

logger = logging.getLogger(__name__)

    data = asyncio.run(scrape_bet9ja(max_matches=10))
    logger.info(json.dumps(data, indent=2))