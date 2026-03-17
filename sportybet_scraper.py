"""
SportyBet Scraper v4 - Pure API (aiohttp, no Playwright).

Calls SportyBet's REST API directly with aiohttp:
  1. pcEvents endpoint for each league (gets 1X2)
  2. pcEventDetail per event for DC + O/U enrichment (concurrent)

No browser needed â fast, lightweight, ~10-15s total.
"""

import asyncio
import aiohttp
import json
import time
from difflib import SequenceMatcher


SPORTYBET_API = "https://www.sportybet.com/api/ng/factsCenter"

# Tournament IDs for each league
TOURNAMENT_IDS = {
    "Premier League": "sr:tournament:17",
    "La Liga":        "sr:tournament:8",
    "Serie A":        "sr:tournament:23",
    "Bundesliga":     "sr:tournament:35",
    "Ligue 1":        "sr:tournament:34",
    "Champions League":"sr:tournament:7",
    "Europa League":  "sr:tournament:679",
    "Conference League":"sr:tournament:17015",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.sportybet.com/ng/sport/football",
    "Origin": "https://www.sportybet.com",
    "sec-ch-ua": '"Chromium";v="120", "Google Chrome";v="120"',
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
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
    "real oviedo": "oviedo",
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
    "sunderland afc": "sunderland",
    "brighton & hove albion": "brighton",
    "brighton hove": "brighton",
    "fc torino": "torino",
    "us lecce": "lecce",
    "hellas verona": "verona",
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


def _parse_event_markets(markets_data) -> dict:
    """Parse market data from API response format.

    Each market has:
    - id "1" = 1X2
    - id "18" = Over/Under (with specifier like "total=2.5")
    - id "10" = Double Chance
    """
    odds = {}

    # Normalize to list of market objects
    if isinstance(markets_data, dict):
        market_list = []
        for mid, mdata in markets_data.items():
            if isinstance(mdata, dict):
                mdata["_mid"] = str(mid)
                market_list.append(mdata)
            elif isinstance(mdata, list):
                for item in mdata:
                    if isinstance(item, dict):
                        item["_mid"] = str(mid)
                        market_list.append(item)
        markets_data = market_list

    if not isinstance(markets_data, list):
        return odds

    for market in markets_data:
        if not isinstance(market, dict):
            continue

        market_id = str(market.get("id", market.get("marketId", market.get("_mid", ""))))
        outcomes = market.get("outcomes", [])

        if isinstance(outcomes, dict):
            outcomes = list(outcomes.values())

        if not outcomes:
            continue

        # 1X2 (market ID "1")
        if market_id == "1":
            odds_1x2 = {}
            for o in outcomes:
                if not isinstance(o, dict):
                    continue
                oid = str(o.get("id", o.get("outcomeId", "")))
                oval = o.get("odds", o.get("formattedOdds", ""))
                desc = o.get("desc", "")
                if oid == "1" or desc == "1":
                    odds_1x2["1"] = str(oval)
                elif oid == "2" or desc == "X":
                    odds_1x2["X"] = str(oval)
                elif oid == "3" or desc == "2":
                    odds_1x2["2"] = str(oval)
            if len(odds_1x2) == 3:
                odds["1X2"] = odds_1x2

        # Over/Under (market ID "18")
        elif market_id == "18":
            specifier = market.get("specifier", "")
            over_val = None
            under_val = None
            for o in outcomes:
                if not isinstance(o, dict):
                    continue
                desc = str(o.get("desc", "")).lower()
                oval = o.get("odds", o.get("formattedOdds", ""))
                if desc.startswith("over"):
                    over_val = str(oval)
                elif desc.startswith("under"):
                    under_val = str(oval)
            if over_val and under_val:
                if "2.5" in specifier:
                    odds["O/U 2.5"] = {"Over": over_val, "Under": under_val}
                elif "1.5" in specifier:
                    odds["O/U 1.5"] = {"Over": over_val, "Under": under_val}
                elif "3.5" in specifier:
                    odds["O/U 3.5"] = {"Over": over_val, "Under": under_val}

        # Double Chance (market ID "10")
        elif market_id == "10":
            dc = {}
            for o in outcomes:
                if not isinstance(o, dict):
                    continue
                oid = str(o.get("id", o.get("outcomeId", "")))
                oval = o.get("odds", o.get("formattedOdds", ""))
                desc = o.get("desc", "")
                if oid == "9" or desc == "1X":
                    dc["1X"] = str(oval)
                elif oid == "10" or desc == "12":
                    dc["12"] = str(oval)
                elif oid == "11" or desc == "X2":
                    dc["X2"] = str(oval)
            if len(dc) == 3:
                odds["Double Chance"] = dc

    return odds


def _parse_api_events(data: dict) -> list[dict]:
    """Parse events from SportyBet API response JSON."""
    events = []

    if not isinstance(data, dict):
        return events

    inner = data.get("data", data)
    if isinstance(inner, dict):
        raw_events = inner.get("events", [])

        if not raw_events:
            tournaments = inner.get("tournaments", [])
            if isinstance(tournaments, list):
                for t in tournaments:
                    if isinstance(t, dict):
                        raw_events.extend(t.get("events", []))

        for e in raw_events:
            if not isinstance(e, dict):
                continue
            home = e.get("homeTeamName", e.get("home", ""))
            away = e.get("awayTeamName", e.get("away", ""))
            if not home or not away:
                continue

            event_id = str(e.get("eventId", e.get("id", "")))
            markets = e.get("markets", e.get("market", []))
            odds = _parse_event_markets(markets)
            if odds and "1X2" in odds:
                events.append({
                    "home": home,
                    "away": away,
                    "event_id": event_id,
                    "odds": odds,
                })

    return events


async def _fetch_league_events(session: aiohttp.ClientSession, league_name: str,
                                tournament_id: str) -> list[dict]:
    """Fetch events for a single league via pcEvents API."""
    tid_encoded = tournament_id.replace(":", "%3A")
    url = (
        f"{SPORTYBET_API}/pcEvents"
        f"?_t={int(time.time() * 1000)}"
        f"&sportId=sr%3Asport%3A1"
        f"&tournamentId={tid_encoded}"
        f"&marketId=1%2C10%2C18"
        f"&pageSize=100&pageNum=1"
    )

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                print(f"  [SportyBet] {league_name}: HTTP {resp.status}")
                return []
            data = await resp.json()

            biz_code = data.get("bizCode")
            if biz_code and biz_code != 10000:
                print(f"  [SportyBet] {league_name}: bizCode={biz_code}")
                return []

            events = _parse_api_events(data)
            if events:
                # Check if we got more than just 1X2
                has_extra = any(
                    "Double Chance" in e["odds"] or "O/U 2.5" in e["odds"]
                    for e in events[:5]
                )
                market_info = "with DC/O/U" if has_extra else "1X2 only"
                print(f"  [SportyBet] {league_name}: {len(events)} events ({market_info})")
            else:
                print(f"  [SportyBet] {league_name}: 0 events from pcEvents")
            return events

    except asyncio.TimeoutError:
        print(f"  [SportyBet] {league_name}: timeout")
        return []
    except Exception as e:
        print(f"  [SportyBet] {league_name} error: {e}")
        return []


async def _enrich_event(session: aiohttp.ClientSession, event: dict) -> dict:
    """Enrich a single event with DC/O/U via pcEventDetail API."""
    event_id = event.get("event_id", "")
    if not event_id:
        return event

    # Skip if already has all markets
    if "Double Chance" in event["odds"] and "O/U 2.5" in event["odds"]:
        return event

    url = (
        f"{SPORTYBET_API}/pcEventDetail"
        f"?_t={int(time.time() * 1000)}"
        f"&eventId={event_id}"
        f"&marketId=1%2C10%2C18"
    )

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return event
            data = await resp.json()

            if not isinstance(data, dict) or data.get("bizCode", 10000) != 10000:
                return event

            inner = data.get("data", data)
            if isinstance(inner, dict):
                markets = inner.get("markets", inner.get("market", []))
                enriched = _parse_event_markets(markets)
                for k, v in enriched.items():
                    if k not in event["odds"]:
                        event["odds"][k] = v

    except Exception:
        pass

    return event


async def scrape_sportybet(max_matches: int = 50, days: int = 7) -> list[dict]:
    """Main entry point â scrape all leagues via pure API calls."""
    start_time = time.time()
    results = []
    seen = set()

    async with aiohttp.ClientSession(headers=HEADERS) as session:
        # Step 1: Hit the main page to establish cookies/session
        try:
            async with session.get(
                "https://www.sportybet.com/ng/sport/football",
                timeout=aiohttp.ClientTimeout(total=10),
            ):
                pass
            print("  [SportyBet] Session initialized")
        except Exception as e:
            print(f"  [SportyBet] Session init warning: {e}")

        # Step 2: Fetch ALL leagues concurrently
        league_tasks = []
        for league_name, tournament_id in TOURNAMENT_IDS.items():
            league_tasks.append(
                _fetch_league_events(session, league_name, tournament_id)
            )

        league_results = await asyncio.gather(*league_tasks, return_exceptions=True)

        # Collect all events
        all_events = []
        for i, (league_name, _) in enumerate(TOURNAMENT_IDS.items()):
            if isinstance(league_results[i], list):
                for event in league_results[i]:
                    home = event["home"]
                    away = event["away"]
                    key = f"{home}-{away}"
                    if key not in seen and len(all_events) < max_matches:
                        seen.add(key)
                        event["league"] = league_name
                        all_events.append(event)

        print(f"  [SportyBet] Total events from pcEvents: {len(all_events)}")

        # Step 3: Check if events need enrichment (only have 1X2)
        needs_enrichment = [
            e for e in all_events
            if "Double Chance" not in e["odds"] or "O/U 2.5" not in e["odds"]
        ]

        if needs_enrichment:
            print(f"  [SportyBet] Enriching {len(needs_enrichment)} events with DC/O/U...")

            # Enrich in batches of 10 to avoid hammering the API
            BATCH_SIZE = 10
            enriched_count = 0
            for i in range(0, len(needs_enrichment), BATCH_SIZE):
                batch = needs_enrichment[i:i + BATCH_SIZE]
                enrich_tasks = [_enrich_event(session, e) for e in batch]
                await asyncio.gather(*enrich_tasks, return_exceptions=True)
                for e in batch:
                    if "Double Chance" in e["odds"] or "O/U 2.5" in e["odds"]:
                        enriched_count += 1

            print(f"  [SportyBet] Enriched {enriched_count}/{len(needs_enrichment)} events")

        # Build final results
        for event in all_events:
            results.append({
                "event_id": f"{event['home']}-{event['away']}",
                "event": f"{event['home']} - {event['away']}",
                "league": event["league"],
                "odds": event["odds"],
            })

    elapsed = time.time() - start_time
    print(f"  [SportyBet] Done â {len(results)} matches in {elapsed:.1f}s")
    return results


if __name__ == "__main__":
    data = asyncio.run(scrape_sportybet(max_matches=10))
    print(json.dumps(data, indent=2))
