"""
Bet9ja Scraper — extracts odds directly from the homepage Top Bets section.
Uses Playwright headless Chromium to render the AngularJS page.
"""
import asyncio
from playwright.async_api import async_playwright

BET9JA_URL = "https://web.bet9ja.com/Sport/"

# Map sign names to market buckets
SIGN_TO_MARKET = {
    "1": "1X2", "X": "1X2", "2": "1X2",
    "1X": "Double Chance", "12": "Double Chance", "X2": "Double Chance",
    "Over": "O/U 2.5", "Under": "O/U 2.5",
}

JS_EXTRACT = """
() => {
    const matches = [];
    const links = document.querySelectorAll('a[is-link-subevent]');
    for (const link of links) {
        const name = link.innerText.trim();
        const sid = (link.href.match(/SubEventID=(\d+)/) || [])[1] || '';
        const row = link.parentElement?.parentElement;
        if (!row) continue;
        const rawOdds = {};
        for (const item of row.querySelectorAll('.odd')) {
            const sign = item.querySelector('.type')?.innerText?.trim();
            const val  = item.querySelector('.QuotaValore')?.innerText?.trim();
            if (sign && val) rawOdds[sign] = val;
        }
        matches.push({ name, sid, rawOdds });
    }
    return matches;
}
"""


def _bucket_odds(raw: dict) -> dict:
    """Sort raw sign→value pairs into market buckets."""
    buckets = {}
    for sign, val in raw.items():
        market = SIGN_TO_MARKET.get(sign)
        if not market:
            continue
        buckets.setdefault(market, {})[sign] = val
    return buckets


async def scrape_bet9ja(max_matches: int = 50) -> list[dict]:
    results = []
    seen_ids = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page()
        await page.route("**/*.{png,jpg,jpeg,gif,webp,woff,woff2,svg}", lambda r: r.abort())

        print("  [Bet9ja] Loading homepage...")
        await page.goto(BET9JA_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_selector("a[is-link-subevent]", timeout=15000)

        # Discover league tabs
        tabs = await page.query_selector_all('[ng-repeat="evento in getEvents()"]')
        print(f"  [Bet9ja] Found {len(tabs)} league tabs")

        for i, tab in enumerate(tabs):
            if len(results) >= max_matches:
                break
            try:
                league = (await tab.inner_text()).strip().replace("\n", " ")
                await tab.click()
                await page.wait_for_timeout(900)
                await page.wait_for_selector("a[is-link-subevent]", timeout=8000)
            except Exception as e:
                print(f"  [Bet9ja] Tab {i} error: {e}")
                continue

            raw_matches = await page.evaluate(JS_EXTRACT)
            added = 0
            for m in raw_matches:
                if m["sid"] in seen_ids or not m["name"]:
                    continue
                seen_ids.add(m["sid"])
                odds = _bucket_odds(m["rawOdds"])
                if odds:
                    results.append({
                        "subevent_id": m["sid"],
                        "event": m["name"],
                        "league": league,
                        "odds": odds,
                    })
                    added += 1
                if len(results) >= max_matches:
                    break
            print(f"  [Bet9ja] {league}: +{added} matches")

        await browser.close()

    print(f"  [Bet9ja] Done — {len(results)} matches total")
    return results


if __name__ == "__main__":
    import json
    data = asyncio.run(scrape_bet9ja(max_matches=10))
    print(json.dumps(data, indent=2))
