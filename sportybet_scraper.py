"""
SportyBet Scraper v3 - API response interception (replaces Vuex + DOM fallback).

Uses Playwright to navigate league pages but intercepts the API responses that
SportyBet's frontend makes to load event data. This gives us ALL market data
(1X2, O/U 2.5, O/U 1.5, Double Chance) from the JSON response directly,
without relying on Vuex store availability or DOM scraping.

Works reliably in headless mode on Railway.

Speed: ~5-15s per league (page load + API capture, no DOM interaction needed).
"""

import asyncio
import json
from playwright.async_api import async_playwright
from difflib import SequenceMatcher


SPORTYBET_BASE = "https://www.sportybet.com/ng/sport/football"

TOURNAMENT_URLS = {
    "Premier League": f"{SPORTYBET_BASE}/sr:category:1/sr:tournament:17",
    "La Liga":        f"{SPORTYBET_BASE}/sr:category:32/sr:tournament:8",
    "Serie A":        f"{SPORTYBET_BASE}/sr:category:31/sr:tournament:23",
    "Bundesliga":     f"{SPORTYBET_BASE}/sr:category:30/sr:tournament:35",
    "Ligue 1":        f"{SPORTYBET_BASE}/sr:category:7/sr:tournament:34",
    "Champions League":f"{SPORTYBET_BASE}/sr:category:393/sr:tournament:7",
    "Europa League":  f"{SPORTYBET_BASE}/sr:category:393/sr:tournament:679",
    "Conference League":f"{SPORTYBET_BASE}/sr:category:393/sr:tournament:17015",
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
    """Parse market data from API response or Vuex store format.

    SportyBet API returns markets as either:
    - A list of market objects (API response format)
    - A dict keyed by market ID (Vuex store format)

    Each market has:
    - id/marketId "1" = 1X2
    - id/marketId "18" = Over/Under (with specifier like "total=2.5")
    - id/marketId "10" = Double Chance
    """
    odds = {}

    # Normalize to list of market objects
    if isinstance(markets_data, dict):
        # Vuex store format: {marketId: {outcomes: {...}}}
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

        # Normalize outcomes to a list
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
    """Parse events from SportyBet API response JSON.

    Expected structure:
    {
        "bizCode": 10000,
        "data": {
            "events": [...] or "tournaments": [{"events": [...]}]
        }
    }
    """
    events = []

    if not isinstance(data, dict):
        return events

    # Try direct data.events
    inner = data.get("data", data)
    if isinstance(inner, dict):
        raw_events = inner.get("events", [])

        # Also check tournaments[].events pattern
        if not raw_events:
            tournaments = inner.get("tournaments", [])
            if isinstance(tournaments, list):
                for t in tournaments:
                    if isinstance(t, dict):
                        raw_events.extend(t.get("events", []))

        # Also check sport.map pattern (Vuex-like)
        if not raw_events:
            sport = inner.get("sport", {})
            if isinstance(sport, dict):
                sport_map = sport.get("map", {})
                for tid, tdata in sport_map.items():
                    if isinstance(tdata, dict) and "events" in tdata:
                        evts = tdata["events"]
                        if isinstance(evts, dict):
                            raw_events.extend(evts.values())
                        elif isinstance(evts, list):
                            raw_events.extend(evts)

        for e in raw_events:
            if not isinstance(e, dict):
                continue
            home = e.get("homeTeamName", e.get("home", ""))
            away = e.get("awayTeamName", e.get("away", ""))
            if not home or not away:
                continue

            markets = e.get("markets", e.get("market", []))
            odds = _parse_event_markets(markets)
            if odds and "1X2" in odds:
                events.append({
                    "home": home,
                    "away": away,
                    "odds": odds,
                })

    return events


# -- JS for Vuex store extraction (fast path, may not work in headless) --
JS_EXTRACT_VUEX = """
(tournamentId) => {
  try {
    const store = window.v_store;
    if (!store || !store.state || !store.state.eventList) return {error: 'no store'};
    const sportMap = store.state.eventList.sport;
    if (!sportMap || !sportMap.map) return {error: 'no sport map'};
    const tournament = sportMap.map[tournamentId];
    if (!tournament || !tournament.events) return {error: 'no tournament', id: tournamentId};

    const events = Object.values(tournament.events).map(e => {
      const m = e.markets || {};
      return {
        home: e.homeTeamName,
        away: e.awayTeamName,
        markets: m,
      };
    });
    return {ok: true, count: events.length, events: events};
  } catch (err) {
    return {error: err.message};
  }
}
"""

# Tournament IDs matching each URL
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


async def _scrape_league(page, league_name: str, url: str, tournament_id: str,
                         seen: set, max_matches: int, current_count: int) -> list[dict]:
    """Scrape a single league using API response interception with Vuex fallback.

    Strategy:
    1. Set up response listener to capture API responses
    2. Navigate to the league page
    3. Try to parse captured API responses for all market data
    4. If API capture fails, try Vuex store extraction
    5. If Vuex fails, use DOM fallback (1X2 only)
    """
    results = []
    captured_responses = []

    # Set up response listener before navigation
    async def on_response(response):
        url_str = response.url
        # Capture any API response that contains event/match data
        if "factsCenter" in url_str or "events" in url_str.lower():
            if response.status == 200:
                try:
                    body = await response.text()
                    data = json.loads(body)
                    captured_responses.append(data)
                except Exception:
                    pass

    page.on("response", on_response)

    print(f"  [SportyBet] Loading {league_name}...")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        # Wait for API responses to arrive
        await page.wait_for_timeout(5000)
    except Exception as e:
        print(f"  [SportyBet] {league_name}: navigation error: {e}")
        page.remove_listener("response", on_response)
        return results

    # Remove listener now that we've captured responses
    page.remove_listener("response", on_response)

    # Strategy 1: Parse captured API responses
    api_events = []
    for resp_data in captured_responses:
        parsed = _parse_api_events(resp_data)
        api_events.extend(parsed)

    if api_events:
        for event in api_events:
            if current_count + len(results) >= max_matches:
                break
            home = event["home"]
            away = event["away"]
            key = f"{home}-{away}"
            if key in seen:
                continue
            seen.add(key)
            results.append({
                "event_id": key,
                "event": f"{home} - {away}",
                "league": league_name,
                "odds": event["odds"],
            })
        print(f"  [SportyBet] {league_name}: +{len(results)} matches (API interception)")
        return results

    # Strategy 2: Try Vuex store extraction
    try:
        await page.wait_for_function(
            """(tid) => {
                try {
                    const m = window.v_store.state.eventList.sport.map[tid];
                    return m && m.events && Object.keys(m.events).length > 0;
                } catch(e) { return false; }
            }""",
            tournament_id,
            timeout=8000,
        )
        vuex_data = await page.evaluate(JS_EXTRACT_VUEX, tournament_id)
        if vuex_data and vuex_data.get("ok"):
            for event in vuex_data.get("events", []):
                if current_count + len(results) >= max_matches:
                    break
                home = event.get("home", "")
                away = event.get("away", "")
                key = f"{home}-{away}"
                if key in seen:
                    continue
                seen.add(key)
                markets = event.get("markets", {})
                odds = _parse_event_markets(markets)
                if odds and "1X2" in odds:
                    results.append({
                        "event_id": key,
                        "event": f"{home} - {away}",
                        "league": league_name,
                        "odds": odds,
                    })
            print(f"  [SportyBet] {league_name}: +{len(results)} matches (Vuex store)")
            return results
    except Exception:
        pass

    # Strategy 3: DOM fallback (1X2 only)
    print(f"  [SportyBet] {league_name}: API + Vuex failed, using DOM fallback")
    try:
        await page.wait_for_selector(".match-row", timeout=10000)
        await page.wait_for_timeout(1000)
        raw = await page.evaluate("""() => {
            const rows = document.querySelectorAll('.match-row');
            const matches = [];
            for (const row of rows) {
                const home = row.querySelector('.home-team')?.textContent?.trim() || '';
                const away = row.querySelector('.away-team')?.textContent?.trim() || '';
                const oddsEls = [...row.querySelectorAll('.m-outcome-odds')];
                const odds = oddsEls.map(o => o.textContent.trim());
                if (home && away && odds.length >= 3) {
                    matches.push({ home, away, odds });
                }
            }
            return matches;
        }""")
        for m in raw:
            if current_count + len(results) >= max_matches:
                break
            key = f"{m['home']}-{m['away']}"
            if key in seen:
                continue
            seen.add(key)
            odds = {"1X2": {"1": m["odds"][0], "X": m["odds"][1], "2": m["odds"][2]}}
            results.append({
                "event_id": key,
                "event": f"{m['home']} - {m['away']}",
                "league": league_name,
                "odds": odds,
            })
        print(f"  [SportyBet] {league_name}: +{len(results)} matches (DOM fallback)")
    except Exception as e:
        print(f"  [SportyBet] {league_name}: all methods failed: {e}")

    return results


async def scrape_sportybet(max_matches: int = 50, days: int = 7) -> list[dict]:
    """Main entry point - scrape all configured leagues."""
    results = []
    seen = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page()
        # Block images/fonts for speed
        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,woff,woff2,svg}",
            lambda r: r.abort(),
        )

        for league_name, url in TOURNAMENT_URLS.items():
            if len(results) >= max_matches:
                break
            try:
                tournament_id = TOURNAMENT_IDS[league_name]
                league_matches = await _scrape_league(
                    page, league_name, url, tournament_id,
                    seen, max_matches, len(results),
                )
                results.extend(league_matches)
            except Exception as e:
                print(f"  [SportyBet] {league_name} error: {e}")
                continue

        await browser.close()

    print(f"  [SportyBet] Done - {len(results)} matches total")
    return results


if __name__ == "__main__":
    data = asyncio.run(scrape_sportybet(max_matches=10))
    print(json.dumps(data, indent=2))
