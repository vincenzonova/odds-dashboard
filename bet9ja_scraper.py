"""
Bet9ja Scraper
--------------
Uses Playwright (headless Chromium) to:
  1. Discover today's top matches from the Bet9ja homepage tabs
     (Premier League, Europa League, Serie A, LaLiga, etc.)
  2. For each match, extract 1X2, O/U 1.5, O/U 2.5, and BTTS odds
"""

import asyncio
import re
from playwright.async_api import async_playwright, Page

BET9JA_BASE = "https://web.bet9ja.com"

# Tab labels on the Bet9ja homepage → league names
LEAGUE_TABS = {
    "Premier League":           "England Premier League",
    "UEFA Europa ...":          "UEFA Europa League",
    "UEFA Confere...": "UEFA Conference League",
    "Serie A":                  "Italy Serie A",
    "LaLiga":                   "Spain LaLiga",
    "UEFA Champi...":           "UEFA Champions League",
    "Germany Bundesliga":       "Bundesliga",
    "France Ligue 1":           "Ligue 1",
}

# Markets to extract per match
MARKETS_TO_FETCH = [
    ("1X2",    "1"),
    ("1X2",    "X"),
    ("1X2",    "2"),
    ("O/U 2.5","Over"),
    ("O/U 2.5","Under"),
    ("O/U 1.5","Over"),
    ("GG/NG",  "GG"),
]

JS_EXTRACT_ODDS = """
() => {
    const result = {};
    const items = document.querySelectorAll('.SEItem.ng-scope');
    for (const item of items) {
        const lines = item.innerText.trim().split('\\n').map(l => l.trim()).filter(Boolean);
        const market = lines[0];
        if (!market) continue;
        result[market] = {};
        for (const odd of item.querySelectorAll('.SEOdd')) {
            const sign  = odd.querySelector('.SEOddsTQ')?.innerText?.trim();
            const value = odd.querySelector('.SEOddLnk')?.innerText?.trim();
            if (sign && value) result[market][sign] = value;
        }
    }
    return result;
}
"""

JS_GET_SUBEVENT_LINKS = """
() => {
    const links = document.querySelectorAll('a[href*="SubEventDetail"]');
    return [...new Set(
        Array.from(links)
            .map(a => a.href)
            .filter(h => h.includes('SubEventID='))
    )].map(href => ({
        href,
        id: href.split('SubEventID=')[1]?.split('&')[0],
        text: document.querySelector(`a[href="${href.replace(location.origin,'')}"]`)?.innerText?.trim() || ''
    }));
}
"""


async def get_match_odds(page: Page, subevent_id: str) -> dict:
    """Navigate to a match detail page and return all odds."""
    url = f"{BET9JA_BASE}/Sport/SubEventDetail?SubEventID={subevent_id}"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_selector(".SEItem.ng-scope", timeout=12000)
        return await page.evaluate(JS_EXTRACT_ODDS)
    except Exception as e:
        print(f"  [Bet9ja] Error fetching SubEventID={subevent_id}: {e}")
        return {}


async def discover_top_matches(page: Page) -> list[dict]:
    """
    Visit Bet9ja homepage and collect today's featured matches
    across all major league tabs. Returns list of match dicts.
    """
    matches = []
    seen_ids = set()

    await page.goto(f"{BET9JA_BASE}/Sport/", wait_until="domcontentloaded", timeout=20000)
    await page.wait_for_selector(".TopBet, [class*='TopBet'], a[href*='SubEventDetail']", timeout=10000)

    # Get all visible tab buttons in the TOP BETS section
    tab_buttons = await page.query_selector_all(".TopBetGroup a, .TopBetTabGroup a, a[class*='tab'], .bet-tab")
    if not tab_buttons:
        tab_buttons = await page.query_selector_all("td a[href='#'], .tab-link, [class*='league-tab']")

    # Also collect from the currently visible default tab
    links_data = await page.evaluate(JS_GET_SUBEVENT_LINKS)
    for item in links_data:
        sid = item.get("id")
        if sid and sid not in seen_ids:
            seen_ids.add(sid)
            matches.append({
                "subevent_id": sid,
                "event": item.get("text", ""),
                "league": "Featured",
                "href": item.get("href", ""),
            })

    # Click each tab and collect matches
    for tab_text, league_name in LEAGUE_TABS.items():
        try:
            tab = await page.query_selector(f"text='{tab_text}'")
            if not tab:
                tab = await page.query_selector(f"a:has-text('{tab_text[:8]}')")
            if tab:
                await tab.click()
                await page.wait_for_timeout(800)
                links_data = await page.evaluate(JS_GET_SUBEVENT_LINKS)
                for item in links_data:
                    sid = item.get("id")
                    if sid and sid not in seen_ids:
                        seen_ids.add(sid)
                        matches.append({
                            "subevent_id": sid,
                            "event": item.get("text", ""),
                            "league": league_name,
                            "href": item.get("href", ""),
                        })
        except Exception as e:
            print(f"  [Bet9ja] Could not click tab '{tab_text}': {e}")
            continue

    print(f"  [Bet9ja] Discovered {len(matches)} featured matches")
    return matches


async def scrape_bet9ja(max_matches: int = 40) -> list[dict]:
    """
    Main entry point. Returns list of match odds dicts:
    {
      subevent_id, event, league,
      odds: { "1X2": {"1": "1.50", "X": "4.00", "2": "6.00"}, "O/U 2.5": {...}, ... }
    }
    """
    results = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = await browser.new_page()

        # Suppress images/fonts for speed
        await page.route("**/*.{png,jpg,jpeg,gif,webp,woff,woff2,svg}", lambda r: r.abort())

        print("  [Bet9ja] Discovering top matches...")
        matches = await discover_top_matches(page)
        matches = matches[:max_matches]

        for i, match in enumerate(matches):
            sid = match["subevent_id"]
            print(f"  [Bet9ja] ({i+1}/{len(matches)}) {match['event'] or sid}")
            odds = await get_match_odds(page, sid)
            if odds:
                results.append({
                    "subevent_id": sid,
                    "event":  match["event"],
                    "league": match["league"],
                    "odds":   odds,
                })

        await browser.close()

    print(f"  [Bet9ja] Done — {len(results)} matches with odds")
    return results


if __name__ == "__main__":
    import json
    data = asyncio.run(scrape_bet9ja(max_matches=5))
    print(json.dumps(data, indent=2))
