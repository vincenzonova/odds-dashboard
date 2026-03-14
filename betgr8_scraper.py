"""
Betgr8 Scraper — uses Playwright to intercept API responses from ng.api.betgr8.com
and scrapes sports odds.

The Betgr8 website (betgr8.com/ng) uses a Nazgul API to fetch sports/events data.
The scraper intercepts these API calls and parses the responses to extract match odds.

Extracts:
  • 1X2 odds (match winner)
  • Over/Under markets (various spreads)
  • Double Chance and other market types
"""
import asyncio
import json
import logging
from playwright.async_api import async_playwright
from typing import Any, Dict, List, Optional

# ─────────────────────────────────────────────────────────────────────────────
# LOGGING CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
LEAGUE_URLS = {
    "Premier League": "https://betgr8.com/ng/sport/football/england/premier-league",
    "La Liga": "https://betgr8.com/ng/sport/football/spain/la-liga",
    "Serie A": "https://betgr8.com/ng/sport/football/italy/serie-a",
    "Bundesliga": "https://betgr8.com/ng/sport/football/germany/bundesliga",
    "Ligue 1": "https://betgr8.com/ng/sport/football/france/ligue-1",
    "Champions League": "https://betgr8.com/ng/sport/football/champions-league",
    "Europa League": "https://betgr8.com/ng/sport/football/europa-league",
}

# Target API patterns to intercept (skip modals, latest-winners, etc)
RELEVANT_API_PATTERNS = [
    "sb/pal/sports",
    "sportsbook",
]

# ─────────────────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS FOR PARSING
# ─────────────────────────────────────────────────────────────────────────────

def _log_api_response_summary(url: str, data: Any, response_num: int = None) -> None:
    """
    Log a summary of an API response for debugging.
    Shows URL, top-level keys (if dict), length (if list), and first 300 chars.
    """
    prefix = f"[Response #{response_num}]" if response_num else "[Response]"
    logger.debug(f"{prefix} URL: {url}")

    if isinstance(data, dict):
        keys = list(data.keys())
        logger.debug(f"{prefix} Type: dict | Keys: {keys}")
        json_str = json.dumps(data)[:300]
        logger.debug(f"{prefix} Content (first 300 chars): {json_str}")
    elif isinstance(data, list):
        logger.debug(f"{prefix} Type: list | Length: {len(data)}")
        if data and isinstance(data[0], dict):
            logger.debug(f"{prefix} First item keys: {list(data[0].keys())}")
        json_str = json.dumps(data)[:300]
        logger.debug(f"{prefix} Content (first 300 chars): {json_str}")
    else:
        logger.debug(f"{prefix} Type: {type(data).__name__}")


def _find_arrays_recursively(obj: Any, target_depth: int = 5, current_depth: int = 0) -> List[tuple]:
    """
    Recursively search through a nested structure and find all arrays/lists.
    Returns list of (path, array, array_length) tuples.
    """
    results = []

    if current_depth > target_depth:
        return results

    if isinstance(obj, list):
        results.append(("", obj, len(obj)))

    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, list):
                results.append((key, value, len(value)))
            elif isinstance(value, dict):
                nested = _find_arrays_recursively(value, target_depth, current_depth + 1)
                for path, arr, length in nested:
                    full_path = f"{key}.{path}" if path else key
                    results.append((full_path, arr, length))

    return results

def _is_match_like(obj: Any) -> bool:
    """
    Check if an object looks like a match/event entry.
    Should have participant/team info and odds-like data.
    """
    if not isinstance(obj, dict):
        return False

    match_indicators = [
        "name", "title", "event", "match",
        "competitor", "participants", "competitors",
        "teams", "home", "away",
        "odds", "markets", "outcomes", "selections",
        "id", "eventId", "matchId", "pk",
    ]

    keys = set(obj.keys())
    count = sum(1 for ind in match_indicators if ind in keys)
    return count >= 2


def _parse_api_events(api_data: Any, league_name: str) -> List[dict]:
    """
    Parse API response to extract match events and their odds.
    Tries multiple parsing strategies:
    1. Look for common top-level keys: sports, events, matches, competitions
    2. Look for nested structures like data.sports[].categories[].events[]
    3. Recursively search for arrays containing match-like objects
    """
    matches = []

    if not isinstance(api_data, dict):
        logger.warning(f"[Parser] API data is not a dict: {type(api_data).__name__}")
        return matches

    logger.debug(f"[Parser] Attempting to parse API response for {league_name}")

    # Strategy 1: Check for direct top-level keys
    direct_keys = ["sports", "events", "matches", "items", "competitions", "leagues"]
    for key in direct_keys:
        if key in api_data and isinstance(api_data[key], list):
            logger.debug(f"[Parser] Found top-level '{key}' array with {len(api_data[key])} items")
            matches.extend(_parse_event_array(api_data[key], key, league_name))
            if matches:
                return matches

    # Strategy 2: Look for nested structures
    nested_paths = [
        ("data", ["sports", "events", "matches"]),
        ("data", ["competitions", "events"]),
        ("data", ["leagues", "matches"]),
        ("data", ["categories", "events"]),
        ("result", ["sports", "events"]),
        ("payload", ["events"]),
        ("body", ["events", "matches"]),
    ]

    for root_key, subkeys in nested_paths:
        if root_key not in api_data:
            continue

        current = api_data[root_key]
        full_path = root_key

        for subkey in subkeys:
            if isinstance(current, dict) and subkey in current:
                current = current[subkey]
                full_path = f"{full_path}.{subkey}"
            elif isinstance(current, list):
                found_in_list = False
                for item in current:
                    if isinstance(item, dict) and subkey in item:
                        current = item[subkey]
                        full_path = f"{full_path}[].{subkey}"
                        found_in_list = True
                        break
                if not found_in_list:
                    break
            else:
                break

        if isinstance(current, list) and current:
            logger.debug(f"[Parser] Found nested path '{full_path}' with {len(current)} items")
            matches.extend(_parse_event_array(current, full_path, league_name))
            if matches:
                return matches

    # Strategy 3: Recursively find all arrays and check for match-like objects
    logger.debug(f"[Parser] Attempting recursive search for match-like arrays")
    arrays = _find_arrays_recursively(api_data, target_depth=5)
    arrays.sort(key=lambda x: x[2], reverse=True)

    for path, arr, length in arrays[:10]:
        if length < 1:
            continue

        match_count = sum(1 for item in arr[:5] if _is_match_like(item))

        if match_count >= 2:
            logger.debug(f"[Parser] Found match-like array at path '{path}' ({length} items, {match_count}/5 look like matches)")
            matches.extend(_parse_event_array(arr, path, league_name))
            if matches:
                return matches
        else:
            logger.debug(f"[Parser] Array at path '{path}' ({length} items) doesn't look like matches")

    logger.warning(f"[Parser] Could not find any event arrays in API response for {league_name}")
    return matches


def _parse_event_array(events_array: List[Any], source_path: str, league_name: str) -> List[dict]:
    matches = []
    logger.debug(f"[Parser] Parsing event array from '{source_path}' ({len(events_array)} items)")

    for event_idx, event in enumerate(events_array):
        if not isinstance(event, dict):
            continue

        event_name = None
        for name_key in ["name", "title", "event", "description"]:
            if name_key in event and isinstance(event[name_key], str):
                event_name = event[name_key]
                break

        if not event_name:
            logger.debug(f"[Parser] Event #{event_idx} has no recognizable name field. Keys: {list(event.keys())[:10]}")
            continue

        markets = _extract_markets_from_event(event, event_name)

        if markets:
            match_entry = {
                "event": event_name,
                "league": league_name,
                "markets": markets,
            }
            matches.append(match_entry)
            logger.debug(f"[Parser] Extracted match: {event_name} with {len(markets)} markets")
        else:
            logger.debug(f"[Parser] Event '{event_name}' has no extractable markets")

    logger.info(f"[Parser] Successfully parsed {len(matches)} matches from '{source_path}'")
    return matches


def _extract_markets_from_event(event: dict, event_name: str) -> dict:
    markets = {}
    market_keys = ["markets", "odds", "selections", "outcomes", "betting_markets"]

    for key in market_keys:
        if key not in event:
            continue

        market_data = event[key]

        if isinstance(market_data, dict):
            _parse_market_dict(market_data, markets, event_name)
        elif isinstance(market_data, list):
            _parse_market_list(market_data, markets, event_name)

    return markets


def _parse_market_dict(market_dict: dict, target_markets: dict, event_name: str) -> None:
    for market_name, market_value in market_dict.items():
        if isinstance(market_value, dict):
            if market_value:
                target_markets[market_name] = market_value
                logger.debug(f"  Market '{market_name}': {market_value}")
        elif isinstance(market_value, list):
            extracted = _extract_odds_from_list(market_value)
            if extracted:
                target_markets[market_name] = extracted


def _parse_market_list(market_list: list, target_markets: dict, event_name: str) -> None:
    for market_obj in market_list:
        if not isinstance(market_obj, dict):
            continue

        market_name = None
        for name_key in ["name", "type", "marketType"]:
            if name_key in market_obj:
                market_name = market_obj[name_key]
                break

        if not market_name:
            continue

        odds = None
        for odds_key in ["odds", "outcomes", "selections", "choices"]:
            if odds_key in market_obj:
                odds_data = market_obj[odds_key]
                if isinstance(odds_data, dict):
                    odds = odds_data
                    break
                elif isinstance(odds_data, list):
                    odds = _extract_odds_from_list(odds_data)
                    break

        if odds:
            target_markets[market_name] = odds


def _extract_odds_from_list(odds_list: list) -> dict:
    result = {}
    for item in odds_list:
        if isinstance(item, dict):
            name = item.get("name") or item.get("title") or item.get("outcome")
            odds = item.get("odds") or item.get("price") or item.get("value")
            if name and odds:
                result[str(name)] = str(odds)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# PLAYWRIGHT AUTOMATION
# ─────────────────────────────────────────────────────────────────────────────

async def _should_intercept_request(url: str) -> bool:
    url_lower = url.lower()
    for pattern in RELEVANT_API_PATTERNS:
        if pattern in url_lower:
            return True
    return False


async def _scrape_league(browser, league_name: str, url: str, seen: set,
                        max_matches: int, current_count: int) -> List[dict]:
    results = []
    captured_responses = {}
    response_counter = [0]

    page = await browser.new_page()

    async def handle_response(response):
        url = response.url
        if not await _should_intercept_request(url):
            return

        try:
            response_counter[0] += 1
            response_num = response_counter[0]

            try:
                body = await response.json()
            except:
                logger.debug(f"[Response #{response_num}] Could not parse JSON from {url}")
                return

            logger.debug(f"[Response #{response_num}] Captured: {url}")
            _log_api_response_summary(url, body, response_num)

            if url not in captured_responses:
                captured_responses[url] = body

        except Exception as e:
            logger.error(f"Error capturing response from {url}: {e}")

    page.on("response", handle_response)

    await page.route("**/*.{png,jpg,jpeg,gif,webp,woff,woff2,svg}",
                     lambda r: r.abort())

    logger.info(f"[Scraper] Loading {league_name} from {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
    except Exception as e:
        logger.error(f"[Scraper] Failed to load {league_name}: {e}")
        await page.close()
        return results

    try:
        page_content = await page.content()
        logger.debug(f"[Scraper] Page source captured ({len(page_content)} chars)")

        import re
        json_matches = re.findall(r'<script[^>]*>(.*?)</script>', page_content, re.DOTALL)
        for match in json_matches:
            if "{" in match and "}" in match:
                try:
                    data = json.loads(match)
                    if isinstance(data, (dict, list)):
                        logger.debug(f"[Scraper] Found embedded JSON in script tag")
                except:
                    pass
    except Exception as e:
        logger.debug(f"[Scraper] Could not capture page source: {e}")

    logger.info(f"[Scraper] Processing {len(captured_responses)} API responses for {league_name}")

    for url, api_data in captured_responses.items():
        try:
            events = _parse_api_events(api_data, league_name)

            for event in events:
                event_key = event["event"]
                if event_key not in seen:
                    seen.add(event_key)
                    results.append(event)
                    logger.info(f"[Scraper] + {event['event']} ({len(event['markets'])} markets)")

                    if current_count + len(results) >= max_matches:
                        break

        except Exception as e:
            logger.error(f"[Scraper] Error parsing API response from {url}: {e}")
            continue

    await page.close()
    logger.info(f"[Scraper] {league_name}: extracted {len(results)} matches")
    return results


async def scrape_betgr8(max_matches: int = 50) -> List[dict]:
    results = []
    seen = set()

    logger.info(f"Starting Betgr8 scraper (target: {max_matches} matches)")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        for league_name, url in LEAGUE_URLS.items():
            if len(results) >= max_matches:
                logger.info(f"Reached target of {max_matches} matches")
                break

            try:
                logger.info(f"{'=' * 60}")
                logger.info(f"Scraping: {league_name}")
                logger.info(f"{'=' * 60}")

                league_matches = await _scrape_league(
                    browser, league_name, url, seen, max_matches, len(results)
                )
                results.extend(league_matches)

            except Exception as e:
                logger.error(f"Fatal error scraping {league_name}: {e}", exc_info=True)
                continue

        await browser.close()

    logger.info(f"Scraping complete \u2014 {len(results)} matches total")
    return results


def format_output(matches: List[dict]) -> List[dict]:
    formatted = []
    for match in matches:
        formatted_match = {
            "event": match.get("event", ""),
            "league": match.get("league", ""),
            "markets": match.get("markets", {}),
        }
        formatted.append(formatted_match)
    return formatted


if __name__ == "__main__":
    data = asyncio.run(scrape_betgr8(max_matches=20))
    output = format_output(data)
    print(json.dumps(output, indent=2))
