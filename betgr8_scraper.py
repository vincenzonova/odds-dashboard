"""
Betgr8 Scraper — uses Playwright to load the site and intercept API/DOM odds.

The Betgr8 site uses the "Nazgul" platform (single-spa + Svelte sportsbook).
The sportsbook makes API calls to ng.api.betgr8.com for odds data.

This scraper:
1. Loads the Betgr8 football page in Playwright
2. Intercepts API responses containing odds data
3. Parses the responses to extract 1X2, O/U 2.5, O/U 1.5, and Double Chance
4. Falls back to DOM extraction if API interception fails

Extracts:
- 1X2 odds
- Over/Under 2.5
- Over/Under 1.5
- Double Chance
"""

import asyncio
import json
import re
from playwright.async_api import async_playwright


BETGR8_BASE = "https://betgr8.com/ng/sport/football"

LEAGUE_URLS = {
    "Premier League": f"{BETGR8_BASE}/england/premier-league",
    "La Liga": f"{BETGR8_BASE}/spain/la-liga",
    "Serie A": f"{BETGR8_BASE}/italy/serie-a",
    "Bundesliga": f"{BETGR8_BASE}/germany/bundesliga",
    "Ligue 1": f"{BETGR8_BASE}/france/ligue-1",
    "Champions League": f"{BETGR8_BASE}/champions-league",
    "Europa League": f"{BETGR8_BASE}/europa-league",
}

# -- JS to extract odds from the rendered DOM --
JS_EXTRACT_EVENTS = """
() => {
    const events = [];
    const rows = document.querySelectorAll(
        '.event-row, .match-row, .prematch-event, [data-event-id], .event-item'
    );
    for (const row of rows) {
        const teams = row.querySelectorAll(
            '.team-name, .participant-name, .event-name span, .competitor'
        );
        const home = teams[0]?.textContent?.trim() || '';
        const away = teams[1]?.textContent?.trim() || '';
        if (!home || !away) continue;

        const oddsEls = row.querySelectorAll(
            '.odd-value, .odds-value, .outcome-odds, .market-odds button, [data-odd]'
        );
        const odds = [...oddsEls].map(o =>
            o.textContent?.trim() || o.getAttribute('data-odd') || ''
        ).filter(o => o && !isNaN(parseFloat(o)));

        events.push({ home, away, odds });
    }
    return events;
}
"""


def _parse_api_events(api_data, league_name: str) -> list:
    """Parse events from various Nazgul API response formats."""
    results = []
    events_list = []

    if isinstance(api_data, list):
        events_list = api_data
    elif isinstance(api_data, dict):
        # Common Nazgul response patterns
        for key in ["events", "matches", "items", "result"]:
            candidate = api_data.get(key, [])
            if isinstance(candidate, list) and candidate:
                events_list = candidate
                break
        # Nested data.events
        if not events_list and isinstance(api_data.get("data"), dict):
            events_list = api_data["data"].get("events", [])
        # Nested competitions
        if not events_list:
            for comp in api_data.get("competitions", api_data.get("categories", [])):
                if isinstance(comp, dict):
                    events_list.extend(comp.get("events", comp.get("matches", [])))

    for ev in events_list:
        if not isinstance(ev, dict):
            continue
        home, away = _extract_team_names(ev)
        if not home or not away:
            continue

        event_name = f"{home} - {away}"
        odds = {}
        _extract_all_markets(ev, odds)

        if odds:
            results.append({
                "event_id": str(ev.get("id", ev.get("eventId", event_name))),
                "event": event_name,
                "league": league_name,
                "odds": odds,
            })

    return results


def _extract_team_names(ev: dict) -> tuple:
    """Extract home and away team names from event dict."""
    home = ""
    away = ""

    # Try nested team objects
    for h_key in ["homeTeam", "home", "team1"]:
        obj = ev.get(h_key)
        if isinstance(obj, dict):
            home = obj.get("name", obj.get("title", ""))
            break
        elif isinstance(obj, str) and obj:
            home = obj
            break

    for a_key in ["awayTeam", "away", "team2"]:
        obj = ev.get(a_key)
        if isinstance(obj, dict):
            away = obj.get("name", obj.get("title", ""))
            break
        elif isinstance(obj, str) and obj:
            away = obj
            break

    # Try competitors array
    if not home or not away:
        comps = ev.get("competitors", [])
        if len(comps) >= 2:
            home = comps[0].get("name", "") if isinstance(comps[0], dict) else str(comps[0])
            away = comps[1].get("name", "") if isinstance(comps[1], dict) else str(comps[1])

    # Try event name splitting
    if not home or not away:
        event_name = ev.get("name", ev.get("eventName", ""))
        if " - " in event_name:
            parts = event_name.split(" - ", 1)
            home, away = parts[0].strip(), parts[1].strip()
        elif " vs " in event_name.lower():
            parts = event_name.lower().split(" vs ", 1)
            home, away = parts[0].strip(), parts[1].strip()

    return home, away


def _extract_all_markets(ev: dict, odds: dict):
    """Extract all market odds from event data."""
    markets = ev.get("markets", ev.get("odds", ev.get("betOptions", [])))

    if isinstance(markets, list):
        for mkt in markets:
            if not isinstance(mkt, dict):
                continue
            mkt_name = (
                mkt.get("name", "") or mkt.get("marketName", "") or
                mkt.get("type", "") or mkt.get("marketType", "")
            ).lower()
            outcomes = mkt.get("outcomes", mkt.get("selections", mkt.get("odds", [])))
            if isinstance(outcomes, list):
                _process_market(mkt_name, mkt, outcomes, odds)
    elif isinstance(markets, dict):
        for mkt_key, mkt_data in markets.items():
            if isinstance(mkt_data, dict):
                mkt_name = mkt_data.get("name", mkt_key).lower()
                outcomes = mkt_data.get("outcomes", mkt_data.get("selections", []))
                if isinstance(outcomes, list):
                    _process_market(mkt_name, mkt_data, outcomes, odds)


def _process_market(mkt_name: str, mkt: dict, outcomes: list, odds: dict):
    """Process a single market and add odds to the odds dict."""
    # 1X2 / Match Result
    if any(k in mkt_name for k in ["1x2", "match result", "full time result", "3way", "3-way", "three way"]):
        for out in outcomes:
            if not isinstance(out, dict):
                continue
            name = (out.get("name", "") or out.get("label", "") or out.get("type", "")).strip()
            val = out.get("odds", out.get("price", out.get("value", "")))
            if not val:
                continue
            val_str = str(val)
            if name in ("1", "Home", "W1", "home"):
                odds.setdefault("1X2", {})["1"] = val_str
            elif name in ("X", "Draw", "draw"):
                odds.setdefault("1X2", {})["X"] = val_str
            elif name in ("2", "Away", "W2", "away"):
                odds.setdefault("1X2", {})["2"] = val_str

    # Over/Under
    elif any(k in mkt_name for k in ["over/under", "over under", "total", "o/u"]):
        spread = str(mkt.get("spread", mkt.get("line", mkt.get("handicap",
                     mkt.get("total", ""))))).strip()
        for out in outcomes:
            if not isinstance(out, dict):
                continue
            name = (out.get("name", "") or out.get("label", "") or out.get("type", "")).lower().strip()
            val = out.get("odds", out.get("price", out.get("value", "")))
            if not val:
                continue
            val_str = str(val)
            # Try to detect spread from outcome name
            out_spread = spread
            if not out_spread or out_spread in ("None", ""):
                m = re.search(r"(\d+\.?\d*)", name)
                if m:
                    out_spread = m.group(1)
            if out_spread == "2.5":
                if "over" in name or name == "o":
                    odds.setdefault("O/U 2.5", {})["Over"] = val_str
                elif "under" in name or name == "u":
                    odds.setdefault("O/U 2.5", {})["Under"] = val_str
            elif out_spread == "1.5":
                if "over" in name or name == "o":
                    odds.setdefault("O/U 1.5", {})["Over"] = val_str
                elif "under" in name or name == "u":
                    odds.setdefault("O/U 1.5", {})["Under"] = val_str

    # Double Chance
    elif "double chance" in mkt_name:
        for out in outcomes:
            if not isinstance(out, dict):
                continue
            name = (out.get("name", "") or out.get("label", "") or out.get("type", "")).strip()
            val = out.get("odds", out.get("price", out.get("value", "")))
            if not val:
                continue
            val_str = str(val)
            if name in ("1X", "Home or Draw", "1x"):
                odds.setdefault("Double Chance", {})["1X"] = val_str
            elif name in ("12", "Home or Away", "1 or 2"):
                odds.setdefault("Double Chance", {})["12"] = val_str
            elif name in ("X2", "Draw or Away", "x2"):
                odds.setdefault("Double Chance", {})["X2"] = val_str


async def _scrape_league(page, league_name: str, url: str, captured_responses: list) -> list:
    """Scrape a single league page."""
    results = []
    captured_responses.clear()

    try:
        print(f"  [Betgr8] Loading {league_name}...")
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for sportsbook to potentially load and make API calls
        await page.wait_for_timeout(8000)

        # Check if we captured any API responses
        if captured_responses:
            print(f"  [Betgr8] {league_name}: captured {len(captured_responses)} API responses")
            for resp_data in captured_responses:
                try:
                    parsed = _parse_api_events(resp_data, league_name)
                    results.extend(parsed)
                except Exception as e:
                    print(f"  [Betgr8] {league_name}: parse error: {e}")

        # Fallback: try DOM extraction if API gave nothing
        if not results:
            try:
                dom_events = await page.evaluate(JS_EXTRACT_EVENTS)
                if dom_events:
                    print(f"  [Betgr8] {league_name}: DOM found {len(dom_events)} events")
                    for ev in dom_events:
                        if len(ev.get("odds", [])) >= 3:
                            match_odds = {"1X2": {
                                "1": ev["odds"][0],
                                "X": ev["odds"][1],
                                "2": ev["odds"][2],
                            }}
                            results.append({
                                "event_id": f"{ev['home']}-{ev['away']}",
                                "event": f"{ev['home']} - {ev['away']}",
                                "league": league_name,
                                "odds": match_odds,
                            })
            except Exception as e:
                print(f"  [Betgr8] {league_name}: DOM extraction error: {e}")

        print(f"  [Betgr8] {league_name}: +{len(results)} matches")

    except Exception as e:
        print(f"  [Betgr8] {league_name} error: {e}")

    return results


async def scrape_betgr8(max_matches: int = 50) -> list:
    """Scrape odds from Betgr8 Nigeria using Playwright + API interception."""
    results = []
    captured_responses = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page()

        # Block heavy resources
        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,woff,woff2,svg}",
            lambda r: r.abort(),
        )

        # Intercept API responses from betgr8 API
        async def handle_response(response):
            url = response.url
            if "ng.api.betgr8.com" in url or "push.betgr8.com" in url:
                try:
                    content_type = response.headers.get("content-type", "")
                    if "json" in content_type:
                        body = await response.json()
                        captured_responses.append(body)
                        print(f"  [Betgr8] Captured API response: {url[:80]}")
                except Exception:
                    pass

        page.on("response", handle_response)

        for league_name, url in LEAGUE_URLS.items():
            if len(results) >= max_matches:
                break
            try:
                league_matches = await _scrape_league(
                    page, league_name, url, captured_responses
                )
                results.extend(league_matches)
            except Exception as e:
                print(f"  [Betgr8] {league_name} error: {e}")
                continue

        await browser.close()

    print(f"  [Betgr8] Done \u2014 {len(results)} matches total")
    return results


if __name__ == "__main__":
    data = asyncio.run(scrape_betgr8(max_matches=10))
    print(json.dumps(data, indent=2))
