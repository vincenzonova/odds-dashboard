"""
SportyBet Scraper — fetches odds via the pcEvents POST API.
No browser needed; pure HTTP requests.
"""
import requests
from difflib import SequenceMatcher

SPORTYBET_BASE = "https://www.sportybet.com"

# Step 1: get popular tournament IDs
SPORT_LIST_URL = f"{SPORTYBET_BASE}/api/ng/factsCenter/popularAndSportList?sportId=sr:sport:1"

# Step 2: fetch events for each tournament
PC_EVENTS_URL = f"{SPORTYBET_BASE}/api/ng/factsCenter/pcEvents"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Referer": "https://www.sportybet.com/ng/",
    "Origin": "https://www.sportybet.com",
}

MARKET_IDS = {
    1: "1X2",
    18: "O/U 2.5",
    10: "Double Chance",
}

def _get_tournament_ids(limit: int = 12) -> list[str]:
    """Fetch popular tournament IDs from SportyBet."""
    try:
        r = requests.get(SPORT_LIST_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        tournaments = []
        for group in data.get("data", {}).get("popular", []):
            tid = group.get("id", "")
            if tid.startswith("sr:tournament:"):
                tournaments.append(tid)
            if len(tournaments) >= limit:
                break
        print(f"  [SportyBet] Found {len(tournaments)} tournaments")
        return tournaments
    except Exception as e:
        print(f"  [SportyBet] Error fetching tournament list: {e}")
        return [
            "sr:tournament:17",   # Premier League
            "sr:tournament:8",    # La Liga
            "sr:tournament:23",   # Serie A
            "sr:tournament:35",   # Bundesliga
            "sr:tournament:34",   # Ligue 1
        ]

def _fetch_tournament_events(tournament_id: str) -> list[dict]:
    """Fetch events for a single tournament using pcEvents POST."""
    payload = {
        "sportId": "sr:sport:1",
        "tournamentId": tournament_id,
    }
    try:
        r = requests.post(PC_EVENTS_URL, json=payload, headers=HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()

        if data.get("bizCode") != 10000:
            print(f"  [SportyBet] API error for {tournament_id}: {data.get('message')}")
            return []

        events = []
        for item in data.get("data", {}).get("events", []):
            event_name = item.get("homeTeamName", "") + " vs " + item.get("awayTeamName", "")
            event_id = item.get("eventId", "")
            league = item.get("tournamentName", "")

            odds = {}
            for market in item.get("markets", []):
                market_id = market.get("marketId")
                market_name = MARKET_IDS.get(market_id)
                if not market_name:
                    mn = market.get("name", "").lower()
                    if "1x2" in mn:
                        market_name = "1X2"
                    elif "over" in mn or "under" in mn:
                        market_name = "O/U 2.5"
                    elif "double" in mn:
                        market_name = "Double Chance"
                    else:
                        continue

                market_odds = {}
                for outcome in market.get("outcomes", []):
                    desc = outcome.get("desc", "")
                    odd_val = outcome.get("odds", "")
                    if desc and odd_val:
                        try:
                            if isinstance(odd_val, (int, float)):
                                odd_val = f"{odd_val / 100:.2f}" if odd_val > 50 else str(odd_val)
                            elif isinstance(odd_val, str) and odd_val.replace('.','',1).isdigit():
                                v = float(odd_val)
                                if v > 50:
                                    odd_val = f"{v / 100:.2f}"
                        except (ValueError, TypeError):
                            pass
                        market_odds[desc] = str(odd_val)

                if market_odds:
                    odds[market_name] = market_odds

            if odds:
                events.append({
                    "event_id": event_id,
                    "event": event_name,
                    "league": league,
                    "odds": odds,
                })

        return events

    except Exception as e:
        print(f"  [SportyBet] Error fetching {tournament_id}: {e}")
        return []

def scrape_sportybet(max_matches: int = 50) -> list[dict]:
    """Main entry point — fetch odds from SportyBet."""
    print("  [SportyBet] Starting scrape...")
    tournament_ids = _get_tournament_ids()
    results = []
    seen = set()

    for tid in tournament_ids:
        if len(results) >= max_matches:
            break
        events = _fetch_tournament_events(tid)
        for ev in events:
            eid = ev["event_id"]
            if eid in seen:
                continue
            seen.add(eid)
            results.append(ev)
            if len(results) >= max_matches:
                break
        print(f"  [SportyBet] {tid}: +{len(events)} events")

    print(f"  [SportyBet] Done — {len(results)} matches total")
    return results


def fuzzy_match(name_a: str, name_b: str, threshold: float = 0.55) -> bool:
    a = name_a.lower().strip()
    b = name_b.lower().strip()
    return SequenceMatcher(None, a, b).ratio() >= threshold


if __name__ == "__main__":
    import json
    data = scrape_sportybet(max_matches=10)
    print(json.dumps(data, indent=2))
