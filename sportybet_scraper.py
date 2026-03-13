"""
SportyBet Scraper — uses Playwright to render the page and extract odds from DOM.
Needed because SportyBet's API requires session cookies set by their JS framework.
"""
import asyncio
from playwright.async_api import async_playwright
from difflib import SequenceMatcher

SPORTYBET_BASE = "https://www.sportybet.com/ng/sport/football"

# Top leagues with their SportyBet tournament paths
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
    """Convert [1, X, 2, Over, Under] list into structured odds dict."""
    result = {}
    if len(odds_list) >= 3:
        result["1X2"] = {"1": odds_list[0], "X": odds_list[1], "2": odds_list[2]}
    if len(odds_list) >= 5:
        result["O/U 2.5"] = {"Over": odds_list[3], "Under": odds_list[4]}
    return result


async def scrape_sportybet(max_matches: int = 50) -> list[dict]:
    """Scrape SportyBet odds using Playwright headless browser."""
    results = []
    seen = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page()
        await page.route("**/*.{png,jpg,jpeg,gif,webp,woff,woff2,svg}", lambda r: r.abort())

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


def fuzzy_match(name_a: str, name_b: str, threshold: float = 0.55) -> bool:
    a = name_a.lower().strip()
    b = name_b.lower().strip()
    return SequenceMatcher(None, a, b).ratio() >= threshold


if __name__ == "__main__":
    import json
    data = asyncio.run(scrape_sportybet(max_matches=10))
    print(json.dumps(data, indent=2))
