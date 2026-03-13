"""
Bet9ja Scraper — uses the sports.bet9ja.com JSON API.
No browser automation needed — just plain HTTP requests.
"""
import asyncio
import aiohttp

BET9JA_API = "https://sports.bet9ja.com/desktop/feapi/PalimpsestAjax/GetEventsInGroupV2"

# League name → Bet9ja GROUPID
LEAGUE_IDS = {
    "Premier League": 170880,
    "La Liga": 180928,
    "Serie A": 167856,
    "Bundesliga": 180923,
    "Ligue 1": 950503,
    "Champions League": 180931,
    "Europa League": 180933,
    "Conference League": 180935,
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

    return {
        "event_id": str(event.get("ID", name)),
        "event": name,
        "league": league_name,
        "odds": odds,
    }


async def scrape_bet9ja(max_matches: int = 50) -> list[dict]:
    """Fetch odds from sports.bet9ja.com JSON API."""
    results = []

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        # First hit the main page to get cookies/session
        try:
            async with session.get("https://sports.bet9ja.com", timeout=aiohttp.ClientTimeout(total=15)):
                pass
        except Exception as e:
            print(f"  [Bet9ja] Session init warning: {e}")

        for league_name, group_id in LEAGUE_IDS.items():
            if len(results) >= max_matches:
                break

            params = {
                "GROUPID": group_id,
                "DISP": 0,
                "GROUPMARKETID": 1,
                "matches": "true",
            }

            try:
                print(f"  [Bet9ja] Fetching {league_name} (GROUPID={group_id})...")
                async with session.get(
                    BET9JA_API,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        print(f"  [Bet9ja] {league_name}: HTTP {resp.status}")
                        continue

                    data = await resp.json()

                    if data.get("R") != "OK":
                        print(f"  [Bet9ja] {league_name}: API returned {data.get('R')}")
                        continue

                    events = data.get("D", {}).get("E", [])
                    added = 0
                    for ev in events:
                        parsed = _parse_event(ev, league_name)
                        if parsed:
                            results.append(parsed)
                            added += 1
                            if len(results) >= max_matches:
                                break

                    print(f"  [Bet9ja] {league_name}: +{added} matches")

            except asyncio.TimeoutError:
                print(f"  [Bet9ja] {league_name}: timeout")
                continue
            except Exception as e:
                print(f"  [Bet9ja] {league_name} error: {e}")
                continue

    print(f"  [Bet9ja] Done — {len(results)} matches total")
    return results


if __name__ == "__main__":
    import json
    data = asyncio.run(scrape_bet9ja(max_matches=10))
    print(json.dumps(data, indent=2))
