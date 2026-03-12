"""
SportyBet Scraper
-----------------
Uses SportyBet's public REST API to fetch odds.
Works automatically when the server is hosted in Nigeria or with a NG VPN.
Falls back gracefully when geo-blocked.
"""

import requests
from difflib import SequenceMatcher
import re

SPORTY_BASE = "https://www.sportybet.com/api/ng"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer":    "https://www.sportybet.com/ng/",
    "Accept":     "application/json",
}

# SportyBet tournament IDs for popular leagues
TOURNAMENT_IDS = {
    "England Premier League":    "sr:tournament:17",
    "UEFA Europa League":        "sr:tournament:679",
    "UEFA Conference League":    "sr:tournament:929",
    "Italy Serie A":             "sr:tournament:23",
    "Spain LaLiga":              "sr:tournament:8",
    "UEFA Champions League":     "sr:tournament:7",
    "Bundesliga":                "sr:tournament:35",
    "Ligue 1":                   "sr:tournament:34",
    "Featured":                  None,
}

MARKET_IDS = "1,18,29"

OUTCOME_MAP = {
    "1": "1",  "Home": "1",
    "X": "X",  "Draw": "X",
    "2": "2",  "Away": "2",
    "Over": "Over",
    "Under": "Under",
    "Yes": "GG",  "No": "NG",
}


def _similar(a: str, b: str) -> float:
    a = re.sub(r'[^a-z0-9 ]', '', a.lower())
    b = re.sub(r'[^a-z0-9 ]', '', b.lower())
    return SequenceMatcher(None, a, b).ratio()


def _parse_market_name(name: str) -> str:
    n = name.lower()
    if "match winner" in n or "1x2" in n or "full time" in n:
        return "1X2"
    if "over/under" in n or "total goals" in n:
        m = re.search(r'(\d+\.?\d*)', n)
        if m:
            val = m.group(1)
            if val == "1.5": return "O/U 1.5"
            if val == "2.5": return "O/U 2.5"
            if val == "3.5": return "O/U 3.5"
            return f"O/U {val}"
    if "both teams" in n or "btts" in n or "gg" in n:
        return "GG/NG"
    return name


def fetch_popular_events() -> list[dict]:
    try:
        r = requests.get(
            f"{SPORTY_BASE}/factsCenter/popularEvents",
            params={"sport": "sr:sport:1", "_t": "1"},
            headers=HEADERS, timeout=10
        )
        if r.status_code != 200:
            return []
        return r.json().get("data", {}).get("events", [])
    except Exception as e:
        print(f"  [SportyBet] Popular events error: {e}")
        return []


def fetch_tournament_events(tournament_id: str) -> list[dict]:
    try:
        r = requests.get(
            f"{SPORTY_BASE}/factsCenter/tourEvents",
            params={"tournamentId": tournament_id, "marketId": MARKET_IDS, "_t": "1"},
            headers=HEADERS, timeout=10
        )
        if r.status_code != 200:
            return []
        data = r.json().get("data", {})
        return data.get("events", []) or data.get("matches", [])
    except Exception as e:
        print(f"  [SportyBet] Tournament {tournament_id} error: {e}")
        return []


def fetch_match_odds(event_id: str) -> dict:
    try:
        r = requests.get(
            f"{SPORTY_BASE}/factsCenter/matchDetails",
            params={"matchId": event_id, "marketId": MARKET_IDS},
            headers=HEADERS, timeout=10
        )
        if r.status_code != 200:
            return {}
        data = r.json().get("data", {})
        markets_raw = data.get("markets", [])
    except Exception as e:
        print(f"  [SportyBet] Match {event_id} error: {e}")
        return {}

    odds = {}
    for market in markets_raw:
        mname = _parse_market_name(market.get("marketName", ""))
        if not mname:
            continue
        odds[mname] = {}
        for outcome in market.get("outcomes", []):
            raw_sign = outcome.get("outcomeName", "")
            sign = OUTCOME_MAP.get(raw_sign, raw_sign)
            val = outcome.get("odds") or outcome.get("probability")
            if sign and val:
                odds[mname][sign] = str(val)
    return odds


def _events_from_raw(raw_events: list) -> list[dict]:
    out = []
    for ev in raw_events:
        event_id = str(ev.get("eventId") or ev.get("matchId") or "")
        home = ev.get("homeTeamName") or ev.get("home", "")
        away = ev.get("awayTeamName") or ev.get("away", "")
        if not event_id or not home:
            continue
        name = f"{home} - {away}" if away else home
        tournament = ev.get("tournamentName") or ev.get("leagueName") or ""
        inline_odds = {}
        for market in ev.get("markets", []):
            mname = _parse_market_name(market.get("marketName", ""))
            inline_odds[mname] = {}
            for outcome in market.get("outcomes", []):
                sign = OUTCOME_MAP.get(outcome.get("outcomeName", ""), outcome.get("outcomeName", ""))
                val = outcome.get("odds")
                if sign and val:
                    inline_odds[mname][sign] = str(val)
        out.append({
            "event_id":   event_id,
            "event":      name,
            "league":     tournament,
            "odds":       inline_odds,
        })
    return out


def find_sportybet_match(target_event: str, sb_events: list[dict]) -> dict | None:
    best_score = 0.0
    best = None
    for ev in sb_events:
        score = _similar(target_event, ev["event"])
        if score > best_score:
            best_score = score
            best = ev
    if best_score >= 0.55:
        return best
    return None


def scrape_sportybet(bet9ja_matches: list[dict]) -> dict[str, dict]:
    print("  [SportyBet] Fetching featured events...")
    sb_events = []
    pop = fetch_popular_events()
    sb_events.extend(_events_from_raw(pop))
    for league, tid in TOURNAMENT_IDS.items():
        if tid is None:
            continue
        tour_events = fetch_tournament_events(tid)
        sb_events.extend(_events_from_raw(tour_events))
    if not sb_events:
        print("  [SportyBet] No events returned — geo-blocked or API changed.")
        return {}
    print(f"  [SportyBet] Got {len(sb_events)} events from API")
    results = {}
    for match in bet9ja_matches:
        event_name = match["event"]
        sb_match = find_sportybet_match(event_name, sb_events)
        if not sb_match:
            print(f"  [SportyBet] No match for: {event_name}")
            results[event_name] = {}
            continue
        odds = sb_match["odds"]
        if not odds.get("1X2"):
            odds = fetch_match_odds(sb_match["event_id"])
        print(f"  [SportyBet] Matched '{event_name}' → '{sb_match['event']}'")
        results[event_name] = odds
    return results


if __name__ == "__main__":
    import json
    test = [{"event": "Arsenal - Everton"}, {"event": "Napoli - Lecce"}]
    data = scrape_sportybet(test)
    print(json.dumps(data, indent=2))
