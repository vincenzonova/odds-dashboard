"""
SportyBet Scraper — uses Playwright to render the page and extract odds from DOM.
Needed because SportyBet's API requires session cookies set by their JS framework.
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

JS_EXTRACT = """
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


def _build_odds_dict(odds_list: list[str]) -> dict:
    result = {}
    if len(odds_list) >= 3:
        result["1X2"] = {"1": odds_list[0], "X": odds_list[1], "2": odds_list[2]}
    if len(odds_list) >= 5:
        result["O/U 2.5"] = {"Over": odds_list[3], "Under": odds_list[4]}
    return result


# ── Team name normalization ──────────────────────────────────────────────────
# Common abbreviations/aliases between Bet9ja and SportyBet
TEAM_ALIASES = {
    "atl. madrid": "atletico madrid",
    "atl madrid": "atletico madrid",
    "atlético madrid": "atletico madrid",
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
    "bayern münchen": "bayern",
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

    # Try swapped match (home-away, away-home) — sometimes order differs
    home_sim2 = _team_similarity(home_a, away_b) if away_b else 0
    away_sim2 = _team_similarity(away_a, home_b) if away_a else 0

    if home_sim2 >= threshold and away_sim2 >= threshold:
        return True

    return False


async def scrape_sportybet(max_matches: int = 50) -> list[dict]:
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
                print(f"  [SportyBet] Loading {league_name}...")
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_selector(".match-row", timeout=15000)
                await page.wait_for_timeout(1000)
                raw = await page.evaluate(JS_EXTRACT)

                added = 0
                for m in raw:
                    key = f"{m['home']}-{m['away']}"
                    if key in seen:
                        continue
                    seen.add(key)
                    odds = _build_odds_dict(m["odds"])
                    if odds:
                        results.append({
                            "event_id": key,
                            "event": f"{m['home']} - {m['away']}",
                            "league": league_name,
                            "odds": odds,
                        })
                        added += 1
                    if len(results) >= max_matches:
                        break
                print(f"  [SportyBet] {league_name}: +{added} matches")
            except Exception as e:
                print(f"  [SportyBet] {league_name} error: {e}")
                continue

        await browser.close()

    print(f"  [SportyBet] Done — {len(results)} matches total")
    return results


if __name__ == "__main__":
    import json
    data = asyncio.run(scrape_sportybet(max_matches=10))
    print(json.dumps(data, indent=2))
