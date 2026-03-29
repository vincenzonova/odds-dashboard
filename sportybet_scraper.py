""" 
SportyBet Scraper - uses Playwright to render the page and extract odds from DOM.
Needed because SportyBet's API requires session cookies set by their JS framework.
Extracts:
  - 1X2 odds (from the default "3 Way & O/U" tab)
  - Over/Under 2.5 (only when the displayed spread is actually 2.5)
  - Over/Under 1.5 (by clicking spread dropdown to select 1.5)
  - Double Chance (by clicking the "Double Chance" tab)
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
    "Conference League":f"{SPORTYBET_BASE}/sr:category:393/sr:tournament:34480",
}


# -- JS extraction for "3 Way & O/U" tab --
# Returns 1X2 odds + O/U odds + current spread per match
JS_EXTRACT_MAIN = """
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


# -- JS: click a specific row's spread dropdown and select a target value --
# Takes [rowIndex, targetSpread] - clicks the dropdown, picks the target, returns new O/U odds
JS_CLICK_SPREAD_VALUE = """
([rowIndex, targetSpread]) => {
  return new Promise((resolve) => {
    const rows = document.querySelectorAll('.match-row');
    if (rowIndex >= rows.length) { resolve(null); return; }
    const row = rows[rowIndex];

    const selectTitle = row.querySelector('.af-select-title') || row.querySelector('.af-select');
    if (!selectTitle) { resolve(null); return; }
    selectTitle.click();

    setTimeout(() => {
      const openList = document.querySelector('.af-select-list.af-select-list-open');
      if (!openList) { resolve(null); return; }
      const items = [...openList.querySelectorAll('.af-select-item')];
      const target = items.find(i => i.textContent.trim() === targetSpread);
      if (!target) {
        document.body.click();
        resolve(null);
        return;
      }
      target.click();

      setTimeout(() => {
        const oddsEls = [...row.querySelectorAll('.m-outcome-odds')];
        const odds = oddsEls.map(o => o.textContent.trim());
        const newSpread = row.querySelector('.af-select-input')?.textContent?.trim() || '';
        resolve({ odds, spread: newSpread });
      }, 800);
    }, 500);
  });
}
"""


# -- JS extraction for "Double Chance" tab --
# Returns 3 odds: 1X, 12, X2
JS_EXTRACT_DC = """
() => {
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
}
"""


def _build_odds_dict(main_data: dict) -> dict:
    """Build odds dict from 3 Way & O/U tab data (includes spread check)."""
    odds_list = main_data["odds"]
    spread = main_data.get("spread", "")
    result = {}
    if len(odds_list) >= 3:
        result["1X2"] = {"1": odds_list[0], "X": odds_list[1], "2": odds_list[2]}
    # Only include O/U if spread is exactly 2.5
    if len(odds_list) >= 5 and spread.strip() == "2.5":
        result["O/U 2.5"] = {"Over": odds_list[3], "Under": odds_list[4]}
    return result


def _add_dc_odds(existing_odds: dict, dc_odds_list: list[str]) -> dict:
    """Add Double Chance odds to an existing odds dict."""
    if len(dc_odds_list) >= 3:
        existing_odds["Double Chance"] = {
            "1X": dc_odds_list[0],
            "12": dc_odds_list[1],
            "X2": dc_odds_list[2],
        }
    return existing_odds


# -- Team name normalization --
# Common abbreviations/aliases between Bet9ja and SportyBet
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
    # Remove common suffixes
    for suffix in [" fc", " cf", " sc", " ssc", " bc", " afc"]:
        if n.endswith(suffix):
            n = n[:-len(suffix)].strip()
    # Check aliases
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
    # Check if one contains the other
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
    # Try direct match (home-home, away-away)
    home_sim = _team_similarity(home_a, home_b)
    away_sim = _team_similarity(away_a, away_b) if away_a and away_b else 0
    if home_sim >= threshold and away_sim >= threshold:
        return True
    # Try swapped match (home-away, away-home) - sometimes order differs
    home_sim2 = _team_similarity(home_a, away_b) if away_b else 0
    away_sim2 = _team_similarity(away_a, home_b) if away_a else 0
    if home_sim2 >= threshold and away_sim2 >= threshold:
        return True
    return False


async def _click_spread_for_value(page, dom_row_idx: int, target: str):
    """Click a row's spread dropdown and select the target value. Returns O/U odds dict or None."""
    try:
        result = await page.evaluate(JS_CLICK_SPREAD_VALUE, [dom_row_idx, target])
        if result and result.get("spread", "").strip() == target:
            odds_list = result["odds"]
            if len(odds_list) >= 5:
                return {"Over": odds_list[3], "Under": odds_list[4]}
        return None
    except Exception:
        return None


async def _scrape_league(page, league_name: str, url: str, seen: set,
                         max_matches: int, current_count: int) -> list[dict]:
    """Scrape a single league: main tab (1X2 + O/U 2.5 + O/U 1.5) then Double Chance tab."""
    results = []
    print(f"  [SportyBet] Loading {league_name}...")

    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_selector(".match-row", timeout=15000)
    await page.wait_for_timeout(1000)

    # -- Step 1: Scrape "3 Way & O/U" tab (default) --
    raw_main = await page.evaluate(JS_EXTRACT_MAIN)

    # Build initial results with 1X2 + conditional O/U 2.5
    # Also track DOM row indices for dropdown interactions
    league_matches = []
    rows_needing_ou25 = []  # (match_index, dom_row_index) for rows where spread != 2.5
    all_dom_indices = []     # (match_index, dom_row_index) for ALL rows (for O/U 1.5)
    dom_index = 0

    for m in raw_main:
        key = f"{m['home']}-{m['away']}"
        if key in seen:
            dom_index += 1
            continue
        seen.add(key)

        odds = _build_odds_dict(m)
        if odds:
            spread = m.get("spread", "")
            match_idx = len(league_matches)
            league_matches.append({
                "event_id": key,
                "event": f"{m['home']} - {m['away']}",
                "league": league_name,
                "odds": odds,
            })

            # Track ALL rows for O/U 1.5 scraping
            all_dom_indices.append((match_idx, dom_index))

            # Track rows where spread != 2.5 but O/U odds exist (just wrong spread)
            if spread.strip() != "2.5" and len(m["odds"]) >= 5:
                rows_needing_ou25.append((match_idx, dom_index))

        dom_index += 1
        if current_count + len(league_matches) >= max_matches:
            break

    # -- Step 1b: Click dropdown to select 2.5 for rows with non-2.5 spread --
    if rows_needing_ou25:
        print(f"  [SportyBet] {league_name}: fixing O/U 2.5 spread for {len(rows_needing_ou25)} matches...")
        ou_fixed = 0
        for match_idx, dom_row_idx in rows_needing_ou25:
            ou_odds = await _click_spread_for_value(page, dom_row_idx, "2.5")
            if ou_odds:
                league_matches[match_idx]["odds"]["O/U 2.5"] = ou_odds
                ou_fixed += 1
            await page.wait_for_timeout(300)
        print(f"  [SportyBet] {league_name}: fixed O/U 2.5 for {ou_fixed}/{len(rows_needing_ou25)} matches")

    # -- Step 1c: Click dropdown to select 1.5 for ALL rows to get O/U 1.5 --
    if all_dom_indices:
        print(f"  [SportyBet] {league_name}: scraping O/U 1.5 for {len(all_dom_indices)} matches...")
        ou15_count = 0
        for match_idx, dom_row_idx in all_dom_indices:
            ou_odds = await _click_spread_for_value(page, dom_row_idx, "1.5")
            if ou_odds:
                league_matches[match_idx]["odds"]["O/U 1.5"] = ou_odds
                ou15_count += 1
            await page.wait_for_timeout(300)
        print(f"  [SportyBet] {league_name}: got O/U 1.5 for {ou15_count}/{len(all_dom_indices)} matches")

    # -- Step 2: Click "Double Chance" tab and scrape --
    try:
        dc_tab = page.locator('.market-item', has_text='Double Chance')
        if await dc_tab.count() > 0:
            await dc_tab.first.click()
            await page.wait_for_timeout(1500)  # wait for odds to update

            raw_dc = await page.evaluate(JS_EXTRACT_DC)

            # Build a lookup by home-away key
            dc_lookup = {}
            for m in raw_dc:
                key = f"{m['home']}-{m['away']}"
                dc_lookup[key] = m["odds"]

            # Merge DC odds into existing results
            dc_added = 0
            for match in league_matches:
                key = match["event_id"]
                if key in dc_lookup:
                    _add_dc_odds(match["odds"], dc_lookup[key])
                    dc_added += 1

            print(f"  [SportyBet] {league_name}: +{len(league_matches)} matches, {dc_added} with DC odds")
        else:
            print(f"  [SportyBet] {league_name}: +{len(league_matches)} matches (no DC tab found)")
    except Exception as e:
        print(f"  [SportyBet] {league_name}: +{len(league_matches)} matches (DC scrape failed: {e})")

    return league_matches


async def scrape_sportybet(max_matches: int = 50, days: int = 2) -> list[dict]:
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
                league_matches = await _scrape_league(
                    page, league_name, url, seen, max_matches, len(results)
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
