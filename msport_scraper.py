"""
MSport Scraper - uses Playwright to render the page and extract odds from DOM.

MSport's website is accessible without VPN from Amsterdam.
Uses tournament-specific URLs to filter by league, bypassing MSport's 50-event DOM cap
on the generic Soccer page.

Each target league has a Sportradar tournament ID that MSport uses for filtering.

Multi-pass extraction per date:
  Pass 1: Default page  -> 1X2 (first market) + O/U with nearest line (second market)
  Pass 2: Click line dropdown -> select "2.5" -> re-extract O/U 2.5
  Pass 3: Click line dropdown -> select "1.5" -> re-extract O/U 1.5
  Pass 4: Navigate to &mId=10 URL -> extract Double Chance (second market becomes DC)

DOM structure:
  - League headers: .m-tournament > .m-tournament--title ("Country - League Name")
  - Match elements: .m-event within .m-tournament
  - Team names: .m-server-name-wrapper (first = home, second = away)
  - Markets: .m-market (first = 1X2 with 3 .m-outcome, second = O/U or DC with 2-3 .m-outcome)
  - O/U line: .m-market span (contains "2.5" or "1.5" etc)
  - O/U line dropdown: .select-box in date-group header (click to open, select specific line)
  - Odds values: .m-outcome > .odds
  - Best Odds: .odds may contain .reference-odds child element to remove
"""

import asyncio
from datetime import datetime, timedelta
from playwright.async_api import async_playwright

MSPORT_BASE = "https://www.msport.com/ng/web/sports/list/Soccer"

# Sportradar tournament IDs used by MSport for URL filtering
TOURNAMENT_IDS = {
    "Premier League": "sr:tournament:17",
    "La Liga": "sr:tournament:8",
    "Serie A": "sr:tournament:23",
    "Bundesliga": "sr:tournament:35",
    "Ligue 1": "sr:tournament:34",
    "Champions League": "sr:tournament:7",
    "Europa League": "sr:tournament:679",
    "Conference League": "sr:tournament:34480",
}

TOURNAMENT_FILTER = ",".join(TOURNAMENT_IDS.values())

# Map MSport league names (from DOM) to our standard names
LEAGUE_MAP = {
    "England - Premier League": "Premier League",
    "Spain - LaLiga": "La Liga",
    "Spain - La Liga": "La Liga",
    "Italy - Serie A": "Serie A",
    "Germany - Bundesliga": "Bundesliga",
    "France - Ligue 1": "Ligue 1",
    "International Clubs - UEFA Champions League": "Champions League",
    "International Clubs - Champions League": "Champions League",
    "International Clubs - UEFA Europa League": "Europa League",
    "International Clubs - Europa League": "Europa League",
    "International Clubs - UEFA Europa Conference League": "Conference League",
    "International Clubs - UEFA Conference League": "Conference League",
    "International Clubs - Conference League": "Conference League",
    "Europe - Champions League": "Champions League",
    "Europe - UEFA Champions League": "Champions League",
    "Europe - Europa League": "Europa League",
    "Europe - UEFA Europa League": "Europa League",
    "Europe - Conference League": "Conference League",
    "Europe - UEFA Europa Conference League": "Conference League",
    "Europe - UEFA Conference League": "Conference League",
}

# ---------------------------------------------------------------------------
# JavaScript extraction snippets
# ---------------------------------------------------------------------------

# Extract all matches: teams, league, 1X2 (first market), second market odds + line
JS_EXTRACT_ALL = """
() => {
    const tournaments = document.querySelectorAll('.m-tournament');
    const results = [];
    for (const t of tournaments) {
        const titleEl = t.querySelector('.m-tournament--title');
        const league = titleEl ? titleEl.textContent.replace(/\\s+/g, ' ').trim() : '';
        const events = t.querySelectorAll('.m-event');
        for (const ev of events) {
            const nameWrappers = ev.querySelectorAll('.m-server-name-wrapper');
            const teams = [...nameWrappers].map(n => n.textContent.trim());
            if (teams.length < 2 || !teams[0] || !teams[1]) continue;

            const markets = ev.querySelectorAll('.m-market');
            const marketData = [];
            let ouLine = null;
            for (let i = 0; i < markets.length; i++) {
                const mkt = markets[i];
                const outcomes = mkt.querySelectorAll('.m-outcome');
                const odds = [...outcomes].map(o => {
                    const oddsEl = o.querySelector('.odds');
                    if (!oddsEl) return null;
                    const clone = oddsEl.cloneNode(true);
                    const ref = clone.querySelector('.reference-odds');
                    if (ref) ref.remove();
                    return clone.textContent.trim();
                }).filter(Boolean);
                marketData.push(odds);
                if (i === 1) {
                    const lineSpan = mkt.querySelector('span');
                    if (lineSpan) { ouLine = lineSpan.textContent.trim(); }
                }
            }
            results.push({
                league: league,
                home: teams[0],
                away: teams[1],
                markets: marketData,
                ouLine: ouLine
            });
        }
    }
    return results;
}
"""

# Extract ONLY the second-market odds per match (used after switching O/U line or DC)
JS_EXTRACT_SECOND_MARKET = """
() => {
    const tournaments = document.querySelectorAll('.m-tournament');
    const results = [];
    for (const t of tournaments) {
        const titleEl = t.querySelector('.m-tournament--title');
        const league = titleEl ? titleEl.textContent.replace(/\\s+/g, ' ').trim() : '';
        const events = t.querySelectorAll('.m-event');
        for (const ev of events) {
            const nameWrappers = ev.querySelectorAll('.m-server-name-wrapper');
            const teams = [...nameWrappers].map(n => n.textContent.trim());
            if (teams.length < 2 || !teams[0] || !teams[1]) continue;

            const markets = ev.querySelectorAll('.m-market');
            if (markets.length < 2) {
                results.push({league, home: teams[0], away: teams[1], odds: [], line: null});
                continue;
            }

            const mkt = markets[1];
            const outcomes = mkt.querySelectorAll('.m-outcome');
            const odds = [...outcomes].map(o => {
                const oddsEl = o.querySelector('.odds');
                if (!oddsEl) return null;
                const clone = oddsEl.cloneNode(true);
                const ref = clone.querySelector('.reference-odds');
                if (ref) ref.remove();
                return clone.textContent.trim();
            }).filter(Boolean);

            let line = null;
            const lineSpan = mkt.querySelector('span');
            if (lineSpan) { line = lineSpan.textContent.trim(); }

            results.push({ league, home: teams[0], away: teams[1], odds, line });
        }
    }
    return results;
}
"""


def calculate_msport_bonus(num_selections: int) -> float:
    """Calculate the msport bonus multiplier based on number of selections."""
    if num_selections < 4:
        return 0.0
    elif 4 <= num_selections <= 5:
        return 0.05
    elif 6 <= num_selections <= 7:
        return 0.10
    elif 8 <= num_selections <= 9:
        return 0.15
    elif 10 <= num_selections <= 14:
        return 0.33
    elif 15 <= num_selections <= 19:
        return 0.50
    elif 20 <= num_selections <= 24:
        return 0.80
    elif 25 <= num_selections <= 29:
        return 1.30
    else:
        return 1.80


def _normalize_league(msport_league: str) -> str:
    """Convert MSport league name to our standard name. Returns None if not a target league."""
    return LEAGUE_MAP.get(msport_league)


def _clean_odds(val: str) -> str:
    """Clean odds value: handle newlines from MSport 'Best Odds' feature."""
    if not val or not isinstance(val, str):
        return val
    return val.split('\n')[0].strip()


def _build_match_dict(raw_match: dict, league_name: str) -> dict:
    """Build a match dict from raw extracted data (Pass 1: 1X2 + default O/U)."""
    home = raw_match["home"]
    away = raw_match["away"]
    markets = raw_match.get("markets", [])
    ou_line = raw_match.get("ouLine")
    odds = {}

    # First market = 1X2 (3 outcomes: 1, X, 2)
    if len(markets) >= 1 and len(markets[0]) >= 3:
        odds["1X2"] = {
            "1": _clean_odds(markets[0][0]),
            "X": _clean_odds(markets[0][1]),
            "2": _clean_odds(markets[0][2]),
        }

    # Second market = O/U - store with the actual line value
    if len(markets) >= 2 and len(markets[1]) >= 2 and ou_line:
        ou_key = f"O/U {ou_line}"
        odds[ou_key] = {
            "Over": _clean_odds(markets[1][0]),
            "Under": _clean_odds(markets[1][1]),
        }

    return {
        "event": f"{home} - {away}",
        "league": league_name,
        "odds": odds,
    }


async def _load_and_extract(page, url: str, date_str: str, timeout_ms: int = 25000) -> list:
    """Load a URL and extract raw matches. Returns empty list on failure."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        try:
            await page.wait_for_selector(".m-event", timeout=timeout_ms)
        except Exception:
            return []
        await page.wait_for_timeout(3000)
        raw_matches = await page.evaluate(JS_EXTRACT_ALL)
        return raw_matches
    except Exception as e:
        print(f"  [MSport] Error loading {url}: {e}")
        return []


async def _switch_ou_line(page, target_line: str) -> bool:
    """Click the O/U line dropdown in the header and select a specific line.

    The dropdown is a .select-box element in each date-group header.
    Clicking it reveals options (Near Odds, Far Odds, 0.5, 1.5, 2.5).
    Selecting one updates ALL match O/U odds on the current page.
    Returns True if successful.
    """
    try:
        # Click the first .select-box to open the line dropdown
        select_box = page.locator('.select-box').first
        await select_box.click(timeout=5000)
        await page.wait_for_timeout(800)

        # The dropdown options appear as list items or divs inside select-box
        # Try multiple selector strategies
        clicked = False

        # Strategy 1: Look for option items within the dropdown
        for selector in [
            f'.select-box li:has-text("{target_line}")',
            f'.select-box .select-option-item:has-text("{target_line}")',
            f'.select-box div:has-text("{target_line}")',
        ]:
            try:
                option = page.locator(selector).first
                if await option.count() > 0:
                    await option.click(timeout=3000)
                    clicked = True
                    break
            except Exception:
                continue

        # Strategy 2: Look for any newly-visible element with the target text
        if not clicked:
            try:
                # The dropdown may render as a portal/overlay outside .select-box
                option = page.get_by_text(target_line, exact=True).last
                await option.click(timeout=3000)
                clicked = True
            except Exception:
                pass

        if not clicked:
            print(f"  [MSport] Could not find dropdown option for {target_line}")
            # Close dropdown by clicking elsewhere
            await page.click('body', position={"x": 10, "y": 10})
            await page.wait_for_timeout(500)
            return False

        # Wait for odds to update in DOM
        await page.wait_for_timeout(2500)
        print(f"  [MSport] Switched O/U line to {target_line}")
        return True

    except Exception as e:
        print(f"  [MSport] Could not switch to O/U {target_line}: {e}")
        try:
            await page.click('body', position={"x": 10, "y": 10})
            await page.wait_for_timeout(500)
        except Exception:
            pass
        return False


async def _extract_ou_after_switch(page, target_line: str) -> list:
    """Extract O/U odds from the second market after switching the line.
    Returns list of dicts: {home, away, league, over, under}."""
    try:
        raw = await page.evaluate(JS_EXTRACT_SECOND_MARKET)
        results = []
        for m in raw:
            # Only include if the line matches what we requested
            if m.get("line") == target_line and len(m.get("odds", [])) >= 2:
                results.append({
                    "home": m["home"],
                    "away": m["away"],
                    "league": m["league"],
                    "over": _clean_odds(m["odds"][0]),
                    "under": _clean_odds(m["odds"][1]),
                })
        return results
    except Exception as e:
        print(f"  [MSport] Error extracting O/U {target_line}: {e}")
        return []


async def _extract_dc(page, url: str, date_str: str) -> list:
    """Navigate to &mId=10 URL and extract Double Chance from second market.
    DC has 3 outcomes: 1X, 12, X2."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        try:
            await page.wait_for_selector(".m-event", timeout=20000)
        except Exception:
            return []
        await page.wait_for_timeout(3000)

        raw = await page.evaluate(JS_EXTRACT_SECOND_MARKET)
        results = []
        for m in raw:
            # DC has 3 outcomes: 1X, 12, X2
            if len(m.get("odds", [])) >= 3:
                results.append({
                    "home": m["home"],
                    "away": m["away"],
                    "league": m["league"],
                    "1X": _clean_odds(m["odds"][0]),
                    "12": _clean_odds(m["odds"][1]),
                    "X2": _clean_odds(m["odds"][2]),
                })
        return results
    except Exception as e:
        print(f"  [MSport] Error extracting DC for {date_str}: {e}")
        return []


async def _scrape_date(page, date_str: str, is_today: bool, seen: set, max_matches: int) -> list:
    """Scrape matches for a specific date with multi-pass extraction.

    Pass 1: Default page -> 1X2 + O/U (nearest line)
    Pass 2: Switch O/U line to 2.5 -> extract O/U 2.5
    Pass 3: Switch O/U line to 1.5 -> extract O/U 1.5
    Pass 4: Navigate to &mId=10 -> extract Double Chance
    """
    url = f"{MSPORT_BASE}?d=d-{date_str}&t={TOURNAMENT_FILTER}"
    results = []

    try:
        # ===== PASS 1: Default page -> 1X2 + default O/U =====
        print(f"  [MSport] Loading {date_str} (Pass 1: 1X2 + O/U)...")
        raw_matches = await _load_and_extract(page, url, date_str)

        # Retry strategy for today
        if not raw_matches and is_today:
            print(f"  [MSport] Retrying {date_str} without date parameter...")
            url_no_date = f"{MSPORT_BASE}?t={TOURNAMENT_FILTER}"
            raw_matches = await _load_and_extract(page, url_no_date, date_str, timeout_ms=30000)
            if raw_matches:
                url = url_no_date

        if not raw_matches and is_today:
            print(f"  [MSport] Retrying {date_str} with individual tournament URLs...")
            for league_name, tid in TOURNAMENT_IDS.items():
                url_single = f"{MSPORT_BASE}?d=d-{date_str}&t={tid}"
                single_matches = await _load_and_extract(page, url_single, date_str, timeout_ms=20000)
                if single_matches:
                    raw_matches.extend(single_matches)

        if not raw_matches:
            print(f"  [MSport] No matches found for {date_str}")
            return results

        print(f"  [MSport] {date_str}: found {len(raw_matches)} events")

        # Build match map keyed by "home-away" for merging across passes
        match_map = {}
        for raw in raw_matches:
            if len(match_map) >= max_matches:
                break
            league_name = _normalize_league(raw["league"])
            if league_name is None:
                continue
            key = f"{raw['home']}-{raw['away']}"
            if key in seen:
                continue
            seen.add(key)
            match_dict = _build_match_dict(raw, league_name)
            if match_dict["odds"]:
                match_map[key] = match_dict

        matched_1x2 = sum(1 for m in match_map.values() if "1X2" in m["odds"])
        print(f"  [MSport] {date_str} Pass 1: {matched_1x2} with 1X2")

        # ===== PASS 2: Switch to O/U 2.5 =====
        need_ou25 = [k for k, m in match_map.items() if "O/U 2.5" not in m["odds"]]
        if need_ou25:
            print(f"  [MSport] {date_str} Pass 2: Switching to O/U 2.5 ({len(need_ou25)} need it)...")
            if await _switch_ou_line(page, "2.5"):
                ou25_data = await _extract_ou_after_switch(page, "2.5")
                merged_25 = 0
                for od in ou25_data:
                    key = f"{od['home']}-{od['away']}"
                    if key in match_map and "O/U 2.5" not in match_map[key]["odds"]:
                        match_map[key]["odds"]["O/U 2.5"] = {
                            "Over": od["over"],
                            "Under": od["under"],
                        }
                        merged_25 += 1
                print(f"  [MSport] {date_str} Pass 2: merged O/U 2.5 for {merged_25} matches")
        else:
            print(f"  [MSport] {date_str} Pass 2: all matches already have O/U 2.5, skipping")

        # ===== PASS 3: Switch to O/U 1.5 =====
        need_ou15 = [k for k, m in match_map.items() if "O/U 1.5" not in m["odds"]]
        if need_ou15:
            print(f"  [MSport] {date_str} Pass 3: Switching to O/U 1.5 ({len(need_ou15)} need it)...")
            if await _switch_ou_line(page, "1.5"):
                ou15_data = await _extract_ou_after_switch(page, "1.5")
                merged_15 = 0
                for od in ou15_data:
                    key = f"{od['home']}-{od['away']}"
                    if key in match_map and "O/U 1.5" not in match_map[key]["odds"]:
                        match_map[key]["odds"]["O/U 1.5"] = {
                            "Over": od["over"],
                            "Under": od["under"],
                        }
                        merged_15 += 1
                print(f"  [MSport] {date_str} Pass 3: merged O/U 1.5 for {merged_15} matches")
        else:
            print(f"  [MSport] {date_str} Pass 3: all matches already have O/U 1.5, skipping")

        # ===== PASS 4: Double Chance via &mId=10 =====
        print(f"  [MSport] {date_str} Pass 4: Loading Double Chance (mId=10)...")
        dc_url = f"{url}&mId=10"
        dc_data = await _extract_dc(page, dc_url, date_str)
        merged_dc = 0
        for dc in dc_data:
            key = f"{dc['home']}-{dc['away']}"
            if key in match_map:
                match_map[key]["odds"]["DC"] = {
                    "1X": dc["1X"],
                    "12": dc["12"],
                    "X2": dc["X2"],
                }
                merged_dc += 1
        print(f"  [MSport] {date_str} Pass 4: merged DC for {merged_dc} matches")

        results = list(match_map.values())
        total_markets = sum(len(m["odds"]) for m in results)
        print(f"  [MSport] {date_str}: {len(results)} matches, {total_markets} total market slots")

    except Exception as e:
        print(f"  [MSport] Error scraping {date_str}: {e}")

    return results


async def scrape_msport(max_matches: int = 200) -> list:
    """Main entry point for scraping MSport data.

    Loads today + next 13 days (full week) to capture upcoming matches.
    Uses tournament-filtered URLs and multi-pass extraction for all markets.
    """
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

        # Pre-warm: load MSport homepage to set cookies/session
        try:
            await page.goto(MSPORT_BASE, wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
        except Exception:
            pass

        # Scrape today + next 6 days
        today = datetime.now()
        for day_offset in range(14):
            if len(results) >= max_matches:
                break
            target_date = today + timedelta(days=day_offset)
            date_str = target_date.strftime("%Y-%m-%d")
            is_today = (day_offset == 0)

            day_results = await _scrape_date(
                page, date_str, is_today, seen, max_matches - len(results)
            )
            results.extend(day_results)

        await browser.close()

    print(f"  [MSport] Done - {len(results)} matches total")
    return results


async def main():
    """Main execution function."""
    import json
    matches = await scrape_msport(max_matches=200)
    print(json.dumps(matches, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
