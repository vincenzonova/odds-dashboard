"""
SportyBet Scraper v2 - Vuex Store extraction (replaces DOM-clicking approach).
Still uses Playwright to navigate (needed for auth cookies), but extracts ALL
odds data from window.v_store (Vue/Vuex) in a single page.evaluate() per league.

Speed improvement: ~10-30s per league instead of ~40-60s (no dropdown clicking).

Extracts:
  - 1X2 odds        (market ID "1")
  - Over/Under 2.5   (market ID "18", specifier "total=2.5")
  - Over/Under 1.5   (market ID "18", specifier "total=1.5")
  - Double Chance     (market ID "10")
"""

import asyncio
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
}

# Tournament IDs matching each URL (extracted from URL path)
TOURNAMENT_IDS = {
    "Premier League": "sr:tournament:17",
    "La Liga":        "sr:tournament:8",
    "Serie A":        "sr:tournament:23",
    "Bundesliga":     "sr:tournament:35",
    "Ligue 1":        "sr:tournament:34",
    "Champions League":"sr:tournament:7",
    "Europa League":  "sr:tournament:679",
}


# -- Single JS evaluation to extract ALL odds from Vuex store --
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
      const result = {
        eventId: e.eventId,
        home: e.homeTeamName,
        away: e.awayTeamName,
        estimateStartTime: e.estimateStartTime,
        odds: {}
      };

      // 1X2 (market "1")
      if (m["1"] && m["1"].outcomes) {
        const o = m["1"].outcomes;
        if (o["1"] && o["2"] && o["3"]) {
          result.odds["1X2"] = {
            "1": o["1"].odds,
            "X": o["2"].odds,
            "2": o["3"].odds
          };
        }
      }

      // Over/Under (market "18") - extract both 2.5 and 1.5
      if (m["18"]) {
        const ouMarkets = Object.values(m["18"]);
        for (const ou of ouMarkets) {
          if (!ou.outcomes) continue;
          const vals = Object.values(ou.outcomes);
          const overEntry = vals.find(v => v.desc && v.desc.startsWith("Over"));
          const underEntry = vals.find(v => v.desc && v.desc.startsWith("Under"));
          if (!overEntry || !underEntry) continue;

          if (ou.specifier === "total=2.5") {
            result.odds["O/U 2.5"] = { Over: overEntry.odds, Under: underEntry.odds };
          } else if (ou.specifier === "total=1.5") {
            result.odds["O/U 1.5"] = { Over: overEntry.odds, Under: underEntry.odds };
          }
        }
      }

      // Double Chance (market "10")
      if (m["10"] && m["10"].outcomes) {
        const o = m["10"].outcomes;
        if (o["9"] && o["10"] && o["11"]) {
          result.odds["Double Chance"] = {
            "1X": o["9"].odds,
            "12": o["10"].odds,
            "X2": o["11"].odds
          };
        }
      }

      return result;
    });

    return {ok: true, count: events.length, events: events};
  } catch (err) {
    return {error: err.message};
  }
}
"""

# -- Fallback: DOM extraction (used if Vuex store not available) --
JS_EXTRACT_DOM_FALLBACK = """
() => {
  const rows = document.querySelectorAll('.match-row');
  const matches = [];
  for (const row of rows) {
    const home = row.querySelector('.home-team')?.textContent?.trim() || '';
    const away = row.querySelector('.away-team')?.textContent?.trim() || '';
    const oddsEls = [...row.querySelectorAll('.m-outcome-odds')];
    const odds = oddsEls.map(o => o.textContent.trim());
    const spread = row.querySelector('.af-select-input')?.textContent?.trim() || '';
    if (home && away && odds.length >= 3) {
      matches.push({ home, away, odds, spread });
    }
  }
  return matches;
}
"""


# -- Team name normalization (same as v1) --
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
    """
    Match two event names by checking BOTH teams individually.
    Both home and away must match above threshold.
    """
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


def _build_odds_dict_from_dom(main_data: dict) -> dict:
    """Build odds dict from DOM fallback data."""
    odds_list = main_data["odds"]
    spread = main_data.get("spread", "")
    result = {}
    if len(odds_list) >= 3:
        result["1X2"] = {"1": odds_list[0], "X": odds_list[1], "2": odds_list[2]}
    if len(odds_list) >= 5 and spread.strip() == "2.5":
        result["O/U 2.5"] = {"Over": odds_list[3], "Under": odds_list[4]}
    return result


async def _scrape_league_vuex(page, league_name: str, url: str, tournament_id: str,
                               seen: set, max_matches: int, current_count: int) -> list[dict]:
    """Scrape a single league using Vuex store extraction (fast path).

    Instead of clicking dropdowns and tabs in the DOM, we extract ALL odds
    data from the Vue/Vuex store in a single page.evaluate() call.
    This gives us 1X2, O/U 1.5, O/U 2.5, and Double Chance simultaneously.
    """
    results = []
    print(f"  [SportyBet] Loading {league_name}...")

    await page.goto(url, wait_until="domcontentloaded", timeout=30000)

    # Wait for Vuex store to be populated with event data
    try:
        await page.wait_for_function(
            """(tid) => {
                try {
                    const m = window.v_store.state.eventList.sport.map[tid];
                    return m && m.events && Object.keys(m.events).length > 0;
                } catch(e) { return false; }
            }""",
            tournament_id,
            timeout=15000,
        )
    except Exception:
        print(f"  [SportyBet] {league_name}: Vuex store not ready, falling back to DOM")
        return await _scrape_league_dom_fallback(page, league_name, seen, max_matches, current_count)

    # Extract all data from Vuex store in one call
    data = await page.evaluate(JS_EXTRACT_VUEX, tournament_id)

    if not data or data.get("error"):
        print(f"  [SportyBet] {league_name}: Vuex extraction failed ({data}), falling back to DOM")
        return await _scrape_league_dom_fallback(page, league_name, seen, max_matches, current_count)

    for event in data.get("events", []):
        if current_count + len(results) >= max_matches:
            break

        home = event.get("home", "")
        away = event.get("away", "")
        key = f"{home}-{away}"
        if key in seen:
            continue
        seen.add(key)

        odds = event.get("odds", {})
        if not odds or "1X2" not in odds:
            continue

        results.append({
            "event_id": key,
            "event": f"{home} - {away}",
            "league": league_name,
            "odds": odds,
        })

    print(f"  [SportyBet] {league_name}: +{len(results)} matches (Vuex store, instant)")
    return results


async def _scrape_league_dom_fallback(page, league_name: str, seen: set,
                                       max_matches: int, current_count: int) -> list[dict]:
    """DOM fallback - simplified version without dropdown clicking.
    Used only when Vuex store is not available (e.g. site structure changed).
    Gets 1X2 and O/U 2.5 (if default spread) but skips O/U 1.5 and DC for speed.
    """
    results = []
    try:
        await page.wait_for_selector(".match-row", timeout=15000)
        await page.wait_for_timeout(1000)
    except Exception:
        print(f"  [SportyBet] {league_name}: no match rows found")
        return results

    raw = await page.evaluate(JS_EXTRACT_DOM_FALLBACK)
    for m in raw:
        if current_count + len(results) >= max_matches:
            break
        key = f"{m['home']}-{m['away']}"
        if key in seen:
            continue
        seen.add(key)
        odds = _build_odds_dict_from_dom(m)
        if odds:
            results.append({
                "event_id": key,
                "event": f"{m['home']} - {m['away']}",
                "league": league_name,
                "odds": odds,
            })

    print(f"  [SportyBet] {league_name}: +{len(results)} matches (DOM fallback)")
    return results


async def scrape_sportybet(max_matches: int = 50, days: int = 7) -> list[dict]:
    results = []
    seen = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page()
        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,woff,woff2,svg}",
            lambda r: r.abort(),
        )

        for league_name, url in TOURNAMENT_URLS.items():
            if len(results) >= max_matches:
                break
            try:
                tournament_id = TOURNAMENT_IDS[league_name]
                league_matches = await _scrape_league_vuex(
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
    import json
    data = asyncio.run(scrape_sportybet(max_matches=10))
    print(json.dumps(data, indent=2))
