"""
Betgr8 Scraper — DOM-based extraction using Playwright.
Navigates to league competition pages, clicks through market tabs (1X2, Double Chance, Total),
and extracts match odds from the rendered DOM.

URL pattern: https://betgr8.com/ng/competition/{slug}/{id}/1
Market tabs change the URL suffix and query params.
"""
import asyncio
import json
import logging
import re
from playwright.async_api import async_playwright
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ─── CONFIGURATION ─────────────────────────────────────────────────────────────
LEAGUE_URLS = {
    "Premier League": "https://betgr8.com/ng/competition/premier-league/1/1",
    "La Liga": "https://betgr8.com/ng/competition/laliga/131/1",
    "Serie A": "https://betgr8.com/ng/competition/serie-a/7/1",
    "Bundesliga": "https://betgr8.com/ng/competition/bundesliga/206/1",
    "Ligue 1": "https://betgr8.com/ng/competition/ligue-1/8/1",
    "Champions League": "https://betgr8.com/ng/competition/uefa-champions-league/474/1",
    "Europa League": "https://betgr8.com/ng/competition/uefa-europa-league/475/1",
    "Conference League": "https://betgr8.com/ng/competition/uefa-europa-conference-league/476/1",
}

# Market tab URL suffixes (appended after the base league URL)
# 1X2 is the default view, Double Chance and Total require extra path + query
MARKET_TABS = {
    "1X2": "",                              # default
    "Double Chance": "/10?marketCategoryId=16",
    "Total": "/17?marketCategoryId=16",
}

WAIT_SECONDS = 5  # seconds to wait for WebSocket data to render


# ─── EXTRACTION HELPERS ────────────────────────────────────────────────────────

async def _extract_matches_from_tab(page, market_type: str) -> List[dict]:
    """
    Extract match data from the currently displayed market tab.
    Uses page.eval_on_selector_all to read match link elements.
    
    Each match <a> with class h-[66px] contains:
      - Team names (home/away in separate spans)
      - Odds values in button elements
    """
    try:
        # Wait for match links to appear
        await page.wait_for_selector('a[class*="h-[66px]"]', timeout=15000)
        await asyncio.sleep(2)  # extra settle time
    except Exception:
        logger.warning(f"[{market_type}] No match links found on page")
        return []

    # Extract data from all match link elements
    raw = await page.evaluate("""() => {
        const links = document.querySelectorAll('a[class*="h-[66px]"]');
        const results = [];
        links.forEach(a => {
            const text = a.innerText.trim();
            results.push({
                text: text,
                href: a.href
            });
        });
        return results;
    }""")

    matches = []
    for item in raw:
        text = item.get("text", "")
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        
        if market_type == "1X2":
            parsed = _parse_1x2_row(lines)
        elif market_type == "Double Chance":
            parsed = _parse_dc_row(lines)
        elif market_type == "Total":
            parsed = _parse_total_row(lines)
        else:
            parsed = None
            
        if parsed:
            matches.append(parsed)

    logger.info(f"[{market_type}] Extracted {len(matches)} matches")
    return matches


def _parse_1x2_row(lines: List[str]) -> Optional[dict]:
    """Parse a 1X2 market row. Lines typically contain:
    home_team, away_team, time, N Markets, ID: N, odd1, odd2, odd3
    """
    if len(lines) < 4:
        return None
    
    home = lines[0]
    away = lines[1]
    
    # Find the three odds values (last 3 numeric values)
    odds = []
    for line in reversed(lines):
        try:
            val = float(line)
            odds.insert(0, val)
        except (ValueError, TypeError):
            pass
        if len(odds) >= 3:
            break
    
    if len(odds) < 3:
        return None
    
    # Extract start_time from line 2 (e.g. "22:00", "16:00")
    start_time = ""
    if len(lines) > 2:
        candidate = lines[2]
        if re.match(r"^\d{1,2}:\d{2}$", candidate):
            start_time = candidate

    return {
        "home": home,
        "away": away,
        "start_time": start_time,
        "odds_1": odds[0],
        "odds_x": odds[1],
        "odds_2": odds[2],
    }


def _parse_dc_row(lines: List[str]) -> Optional[dict]:
    """Parse a Double Chance market row. Columns: 1X, 12, X2"""
    if len(lines) < 4:
        return None
    
    home = lines[0]
    away = lines[1]
    
    start_time = ""
    if len(lines) > 2:
        candidate = lines[2]
        if re.match(r"^\d{1,2}:\d{2}$", candidate):
            start_time = candidate
    
    odds = []
    for line in reversed(lines):
        try:
            val = float(line)
            odds.insert(0, val)
        except (ValueError, TypeError):
            pass
        if len(odds) >= 3:
            break
    
    if len(odds) < 3:
        return None
    
    return {
        "home": home,
        "away": away,
        "start_time": start_time,
        "odds_1x": odds[0],
        "odds_12": odds[1],
        "odds_x2": odds[2],
    }


def _parse_total_row(lines: List[str]) -> Optional[dict]:
    """Parse a Total (Over/Under) market row.
    
    Betgr8 rows on the Total tab look like:
      home, away, time_or_status, 'N Markets', 'ID: N', spread, over, [old_over], under
    The spread may include a dropdown char (e.g. '2.5 v').
    Old odds sometimes appear as an extra number under the current Over value.
    """
    if len(lines) < 4:
        return None
    
    home = lines[0]
    away = lines[1]
    
    start_time = ""
    if len(lines) > 2:
        candidate = lines[2]
        if re.match(r"^\d{1,2}:\d{2}$", candidate):
            start_time = candidate
    
    # Collect all numeric values and the spread
    spread = None
    numeric_vals = []
    
    for line in lines[2:]:  # skip home/away
        # Clean dropdown indicators
        clean = line.replace("\u2304", "").replace("\u25be", "").replace("\u02c5", "").strip()
        # Also handle "2.5 v" pattern
        clean = re.sub(r"\s*[v\u02c5]\s*$", "", clean).strip()
        try:
            val = float(clean)
            if val in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5):
                if spread is None:
                    spread = val
                # else ignore duplicate spread values
            elif 1.0 <= val <= 100.0:
                numeric_vals.append(val)
        except (ValueError, TypeError):
            pass
    
    if len(numeric_vals) < 2:
        return None
    
    # Take the FIRST and LAST of the odds -- if there are 3 values
    # (over, old_over, under), we want index 0 and index -1.
    # If exactly 2 values, it's simply over and under.
    over_odd = numeric_vals[0]
    under_odd = numeric_vals[-1]
    
    return {
        "home": home,
        "away": away,
        "start_time": start_time,
        "spread": spread or 2.5,
        "odds_over": over_odd,
        "odds_under": under_odd,
    }




async def _switch_goals_header(page, target_spread: str = "1.5") -> bool:
    """Switch ALL matches on the Total tab to a different spread using the
    global 'Goals' column-header dropdown.

    The Total tab has date-group headers (Today, Tomorrow, etc.) each with
    a 'Goals v' column label.  The FIRST one acts as a global switch --
    clicking it opens a dropdown with 0.5 / 1.5 / 2.5 / 3.5 / ... options.
    Selecting a value re-renders every match row with that spread.

    Returns True if the switch succeeded.
    """
    try:
        # Find the clickable Goals header -- it is a <div> with
        # class containing 'cursor-pointer' that wraps a <span> with
        # class 'text-black text-xs' whose text is 'Goals'.
        goals_header = await page.query_selector(
            'div.cursor-pointer span.text-black.text-xs'
        )
        if not goals_header:
            # Fallback: look for any element with text "Goals" that is
            # inside an element with cursor-pointer
            goals_header = await page.evaluate("""() => {
                const spans = document.querySelectorAll('span');
                for (const s of spans) {
                    if (s.innerText.trim() === 'Goals') {
                        const parent = s.closest('[class*="cursor-pointer"]');
                        if (parent) return true;
                    }
                }
                return false;
            }""")
            if goals_header:
                await page.click('div.cursor-pointer:has(span.text-xs)')
            else:
                logger.info(f"[Total {target_spread}] No Goals header dropdown found")
                return False
        else:
            await goals_header.click()

        await asyncio.sleep(1.5)

        # Now find and click the target spread option in the dropdown.
        # Options appear as child elements of a dropdown/popover that
        # just appeared.  Each option shows a spread value like "1.5".
        option = await page.evaluate("""(target) => {
            const els = document.querySelectorAll('div, li, span, button');
            for (const el of els) {
                const t = el.innerText.trim();
                if (t === target && el.offsetParent !== null) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.width < 200 && rect.height > 15 && rect.height < 60) {
                        el.click();
                        return true;
                    }
                }
            }
            return false;
        }""", target_spread)

        if not option:
            logger.info(f"[Total {target_spread}] Could not find '{target_spread}' in dropdown")
            await page.keyboard.press("Escape")
            return False

        await asyncio.sleep(WAIT_SECONDS)
        logger.info(f"[Total {target_spread}] Switched all matches to spread {target_spread}")
        return True

    except Exception as e:
        logger.warning(f"[Total {target_spread}] Goals header switch failed: {e}")
        return False


# ─── MAIN SCRAPING LOGIC ──────────────────────────────────────────────────────

async def _scrape_league(page, league_name: str, base_url: str, max_matches: int) -> List[dict]:
    """
    Scrape a single league: visit 1X2, Double Chance, and Total tabs.
    Merge odds by (home, away) team pair.
    """
    matches_by_key = {}
    
    for market_type, suffix in MARKET_TABS.items():
        url = base_url + suffix
        logger.info(f"[{league_name}] Navigating to {market_type}: {url}")
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(WAIT_SECONDS)
        except Exception as e:
            logger.error(f"[{league_name}] Failed to load {market_type}: {e}")
            continue
        
        tab_matches = await _extract_matches_from_tab(page, market_type)
        
        for m in tab_matches:
            key = (m["home"].lower().strip(), m["away"].lower().strip())
            
            if key not in matches_by_key:
                matches_by_key[key] = {
                    "event": f"{m['home']} - {m['away']}",
                    "league": league_name,
                    "start_time": m.get("start_time", ""),
                    "markets": {}
                }
            # Update start_time if we got one and don't have it yet
            if m.get("start_time") and not matches_by_key[key].get("start_time"):
                matches_by_key[key]["start_time"] = m["start_time"]
            
            entry = matches_by_key[key]
            
            if market_type == "1X2":
                entry["markets"]["1X2"] = {
                    "1": m["odds_1"],
                    "X": m["odds_x"],
                    "2": m["odds_2"],
                }
            elif market_type == "Double Chance":
                entry["markets"]["Double Chance"] = {
                    "1X": m["odds_1x"],
                    "12": m["odds_12"],
                    "X2": m["odds_x2"],
                }
            elif market_type == "Total":
                spread = m.get("spread", 2.5)
                key_name = f"O/U {spread:g}"
                entry["markets"][key_name] = {
                    "Over": m["odds_over"],
                    "Under": m["odds_under"],
                }

    # --- Extra passes: ensure O/U 2.5 for all matches + O/U 1.5 ---
    # Some matches on Betgr8 default to a different spread (e.g. 3.5)
    # so we explicitly switch the global Goals header to 2.5, then 1.5.
    try:
        total_url = base_url + MARKET_TABS["Total"]
        logger.info(f"[{league_name}] Navigating to Total tab for O/U 2.5 + 1.5 passes")
        await page.goto(total_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(WAIT_SECONDS)

        # O/U 2.5 explicit pass (catches matches that defaulted to 3.5 etc.)
        if await _switch_goals_header(page, "2.5"):
            ou25_matches = await _extract_matches_from_tab(page, "Total")
            for m in ou25_matches:
                key = (m["home"].lower().strip(), m["away"].lower().strip())
                if key in matches_by_key:
                    entry = matches_by_key[key]
                    if "O/U 2.5" not in entry["markets"]:
                        entry["markets"]["O/U 2.5"] = {
                            "Over": m["odds_over"],
                            "Under": m["odds_under"],
                        }
            logger.info(f"[{league_name}] O/U 2.5 pass extracted {len(ou25_matches)} matches")

        # O/U 1.5 pass (switch on same page, no re-navigate needed)
        if await _switch_goals_header(page, "1.5"):
            ou15_matches = await _extract_matches_from_tab(page, "Total")
            for m in ou15_matches:
                key = (m["home"].lower().strip(), m["away"].lower().strip())
                if key in matches_by_key:
                    entry = matches_by_key[key]
                    spread = m.get("spread", 1.5)
                    key_name = f"O/U {spread:g}"
                    entry["markets"][key_name] = {
                        "Over": m["odds_over"],
                        "Under": m["odds_under"],
                    }
            logger.info(f"[{league_name}] O/U 1.5 pass extracted {len(ou15_matches)} matches")
    except Exception as e:
        logger.warning(f"[{league_name}] O/U spread passes failed: {e}")

    results = list(matches_by_key.values())[:max_matches]
    logger.info(f"[{league_name}] Total merged matches: {len(results)}")
    return results


async def scrape_betgr8(max_matches: int = 100, days: int = 2) -> List[dict]:
    """Main entry point: launch browser, scrape all leagues, return matches."""
    all_matches = []
    seen = set()
    
    logger.info("=== Betgr8 Scraper Starting ===")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        for league_name, base_url in LEAGUE_URLS.items():
            if len(all_matches) >= max_matches:
                break
            
            remaining = max_matches - len(all_matches)
            
            try:
                league_matches = await _scrape_league(page, league_name, base_url, remaining)
                
                for m in league_matches:
                    ev = m["event"]
                    parts = ev.split(" - ", 1)
                    key = (parts[0].lower().strip(), parts[1].lower().strip()) if len(parts) == 2 else (ev.lower(), "")
                    if key not in seen:
                        seen.add(key)
                        all_matches.append(m)
                        
            except Exception as e:
                logger.error(f"[{league_name}] Scrape failed: {e}")
                continue
        
        await browser.close()
    
    logger.info(f"=== Betgr8 Scraper Complete: {len(all_matches)} matches ===")
    return all_matches


def format_output(matches: List[dict]) -> str:
    """Format scraped matches for display."""
    if not matches:
        return "No matches found."
    
    lines = []
    for m in matches:
        lines.append(f"\n{m['event']} ({m['league']})")
        for market_name, odds in m.get("markets", {}).items():
            odds_str = " | ".join(f"{k}: {v}" for k, v in odds.items())
            lines.append(f"  {market_name}: {odds_str}")
    
    return "\n".join(lines)


if __name__ == "__main__":
    matches = asyncio.run(scrape_betgr8(max_matches=50))
    logger.info(format_output(matches))
"""
Betgr8 Scraper — DOM-based extraction using Playwright.
Navigates to league competition pages, clicks through market tabs (1X2, Double Chance, Total),
and extracts match odds from the rendered DOM.

URL pattern: https://betgr8.com/ng/competition/{slug}/{id}/1
Market tabs change the URL suffix and query params.
"""
import asyncio
import json
import logging
import re
from playwright.async_api import async_playwright
from typing import Any, Dict, List, Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# ─── CONFIGURATION ─────────────────────────────────────────────────────────────
LEAGUE_URLS = {
    "Premier League": "https://betgr8.com/ng/competition/premier-league/1/1",
    "La Liga": "https://betgr8.com/ng/competition/laliga/131/1",
    "Serie A": "https://betgr8.com/ng/competition/serie-a/7/1",
    "Bundesliga": "https://betgr8.com/ng/competition/bundesliga/206/1",
    "Ligue 1": "https://betgr8.com/ng/competition/ligue-1/8/1",
    "Champions League": "https://betgr8.com/ng/competition/uefa-champions-league/474/1",
    "Europa League": "https://betgr8.com/ng/competition/uefa-europa-league/475/1",
    "Conference League": "https://betgr8.com/ng/competition/uefa-europa-conference-league/476/1",
}

# Market tab URL suffixes (appended after the base league URL)
# 1X2 is the default view, Double Chance and Total require extra path + query
MARKET_TABS = {
    "1X2": "",                              # default
    "Double Chance": "/10?marketCategoryId=16",
    "Total": "/17?marketCategoryId=16",
}

WAIT_SECONDS = 5  # seconds to wait for WebSocket data to render


# ─── EXTRACTION HELPERS ────────────────────────────────────────────────────────

async def _extract_matches_from_tab(page, market_type: str) -> List[dict]:
    """
    Extract match data from the currently displayed market tab.
    Uses page.eval_on_selector_all to read match link elements.
    
    Each match <a> with class h-[66px] contains:
      - Team names (home/away in separate spans)
      - Odds values in button elements
    """
    try:
        # Wait for match links to appear
        await page.wait_for_selector('a[class*="h-[66px]"]', timeout=15000)
        await asyncio.sleep(2)  # extra settle time
    except Exception:
        logger.warning(f"[{market_type}] No match links found on page")
        return []

    # Extract data from all match link elements
    raw = await page.evaluate("""() => {
        const links = document.querySelectorAll('a[class*="h-[66px]"]');
        const results = [];
        links.forEach(a => {
            const text = a.innerText.trim();
            results.push({
                text: text,
                href: a.href
            });
        });
        return results;
    }""")

    matches = []
    for item in raw:
        text = item.get("text", "")
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        
        if market_type == "1X2":
            parsed = _parse_1x2_row(lines)
        elif market_type == "Double Chance":
            parsed = _parse_dc_row(lines)
        elif market_type == "Total":
            parsed = _parse_total_row(lines)
        else:
            parsed = None
            
        if parsed:
            matches.append(parsed)

    logger.info(f"[{market_type}] Extracted {len(matches)} matches")
    return matches


def _parse_1x2_row(lines: List[str]) -> Optional[dict]:
    """Parse a 1X2 market row. Lines typically contain:
    home_team, away_team, time, N Markets, ID: N, odd1, odd2, odd3
    """
    if len(lines) < 4:
        return None
    
    home = lines[0]
    away = lines[1]
    
    # Find the three odds values (last 3 numeric values)
    odds = []
    for line in reversed(lines):
        try:
            val = float(line)
            odds.insert(0, val)
        except (ValueError, TypeError):
            pass
        if len(odds) >= 3:
            break
    
    if len(odds) < 3:
        return None
    
    # Extract start_time from line 2 (e.g. "22:00", "16:00")
    start_time = ""
    if len(lines) > 2:
        candidate = lines[2]
        if re.match(r"^\d{1,2}:\d{2}$", candidate):
            start_time = candidate

    return {
        "home": home,
        "away": away,
        "start_time": start_time,
        "odds_1": odds[0],
        "odds_x": odds[1],
        "odds_2": odds[2],
    }


def _parse_dc_row(lines: List[str]) -> Optional[dict]:
    """Parse a Double Chance market row. Columns: 1X, 12, X2"""
    if len(lines) < 4:
        return None
    
    home = lines[0]
    away = lines[1]
    
    start_time = ""
    if len(lines) > 2:
        candidate = lines[2]
        if re.match(r"^\d{1,2}:\d{2}$", candidate):
            start_time = candidate
    
    odds = []
    for line in reversed(lines):
        try:
            val = float(line)
            odds.insert(0, val)
        except (ValueError, TypeError):
            pass
        if len(odds) >= 3:
            break
    
    if len(odds) < 3:
        return None
    
    return {
        "home": home,
        "away": away,
        "start_time": start_time,
        "odds_1x": odds[0],
        "odds_12": odds[1],
        "odds_x2": odds[2],
    }


def _parse_total_row(lines: List[str]) -> Optional[dict]:
    """Parse a Total (Over/Under) market row.
    
    Betgr8 rows on the Total tab look like:
      home, away, time_or_status, 'N Markets', 'ID: N', spread, over, [old_over], under
    The spread may include a dropdown char (e.g. '2.5 v').
    Old odds sometimes appear as an extra number under the current Over value.
    """
    if len(lines) < 4:
        return None
    
    home = lines[0]
    away = lines[1]
    
    start_time = ""
    if len(lines) > 2:
        candidate = lines[2]
        if re.match(r"^\d{1,2}:\d{2}$", candidate):
            start_time = candidate
    
    # Collect all numeric values and the spread
    spread = None
    numeric_vals = []
    
    for line in lines[2:]:  # skip home/away
        # Clean dropdown indicators
        clean = line.replace("\u2304", "").replace("\u25be", "").replace("\u02c5", "").strip()
        # Also handle "2.5 v" pattern
        clean = re.sub(r"\s*[v\u02c5]\s*$", "", clean).strip()
        try:
            val = float(clean)
            if val in (0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5):
                if spread is None:
                    spread = val
                # else ignore duplicate spread values
            elif 1.0 <= val <= 100.0:
                numeric_vals.append(val)
        except (ValueError, TypeError):
            pass
    
    if len(numeric_vals) < 2:
        return None
    
    # Take the FIRST and LAST of the odds -- if there are 3 values
    # (over, old_over, under), we want index 0 and index -1.
    # If exactly 2 values, it's simply over and under.
    over_odd = numeric_vals[0]
    under_odd = numeric_vals[-1]
    
    return {
        "home": home,
        "away": away,
        "start_time": start_time,
        "spread": spread or 2.5,
        "odds_over": over_odd,
        "odds_under": under_odd,
    }




async def _switch_goals_header(page, target_spread: str = "1.5") -> bool:
    """Switch ALL matches on the Total tab to a different spread using the
    global 'Goals' column-header dropdown.

    The Total tab has date-group headers (Today, Tomorrow, etc.) each with
    a 'Goals v' column label.  The FIRST one acts as a global switch --
    clicking it opens a dropdown with 0.5 / 1.5 / 2.5 / 3.5 / ... options.
    Selecting a value re-renders every match row with that spread.

    Returns True if the switch succeeded.
    """
    try:
        # Find the clickable Goals header -- it is a <div> with
        # class containing 'cursor-pointer' that wraps a <span> with
        # class 'text-black text-xs' whose text is 'Goals'.
        goals_header = await page.query_selector(
            'div.cursor-pointer span.text-black.text-xs'
        )
        if not goals_header:
            # Fallback: look for any element with text "Goals" that is
            # inside an element with cursor-pointer
            goals_header = await page.evaluate("""() => {
                const spans = document.querySelectorAll('span');
                for (const s of spans) {
                    if (s.innerText.trim() === 'Goals') {
                        const parent = s.closest('[class*="cursor-pointer"]');
                        if (parent) return true;
                    }
                }
                return false;
            }""")
            if goals_header:
                await page.click('div.cursor-pointer:has(span.text-xs)')
            else:
                logger.info(f"[Total {target_spread}] No Goals header dropdown found")
                return False
        else:
            await goals_header.click()

        await asyncio.sleep(1.5)

        # Now find and click the target spread option in the dropdown.
        # Options appear as child elements of a dropdown/popover that
        # just appeared.  Each option shows a spread value like "1.5".
        option = await page.evaluate("""(target) => {
            const els = document.querySelectorAll('div, li, span, button');
            for (const el of els) {
                const t = el.innerText.trim();
                if (t === target && el.offsetParent !== null) {
                    const rect = el.getBoundingClientRect();
                    if (rect.width > 0 && rect.width < 200 && rect.height > 15 && rect.height < 60) {
                        el.click();
                        return true;
                    }
                }
            }
            return false;
        }""", target_spread)

        if not option:
            logger.info(f"[Total {target_spread}] Could not find '{target_spread}' in dropdown")
            await page.keyboard.press("Escape")
            return False

        await asyncio.sleep(WAIT_SECONDS)
        logger.info(f"[Total {target_spread}] Switched all matches to spread {target_spread}")
        return True

    except Exception as e:
        logger.warning(f"[Total {target_spread}] Goals header switch failed: {e}")
        return False


# ─── MAIN SCRAPING LOGIC ──────────────────────────────────────────────────────

async def _scrape_league(page, league_name: str, base_url: str, max_matches: int) -> List[dict]:
    """
    Scrape a single league: visit 1X2, Double Chance, and Total tabs.
    Merge odds by (home, away) team pair.
    """
    matches_by_key = {}
    
    for market_type, suffix in MARKET_TABS.items():
        url = base_url + suffix
        logger.info(f"[{league_name}] Navigating to {market_type}: {url}")
        
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(WAIT_SECONDS)
        except Exception as e:
            logger.error(f"[{league_name}] Failed to load {market_type}: {e}")
            continue
        
        tab_matches = await _extract_matches_from_tab(page, market_type)
        
        for m in tab_matches:
            key = (m["home"].lower().strip(), m["away"].lower().strip())
            
            if key not in matches_by_key:
                matches_by_key[key] = {
                    "event": f"{m['home']} - {m['away']}",
                    "league": league_name,
                    "start_time": m.get("start_time", ""),
                    "markets": {}
                }
            # Update start_time if we got one and don't have it yet
            if m.get("start_time") and not matches_by_key[key].get("start_time"):
                matches_by_key[key]["start_time"] = m["start_time"]
            
            entry = matches_by_key[key]
            
            if market_type == "1X2":
                entry["markets"]["1X2"] = {
                    "1": m["odds_1"],
                    "X": m["odds_x"],
                    "2": m["odds_2"],
                }
            elif market_type == "Double Chance":
                entry["markets"]["Double Chance"] = {
                    "1X": m["odds_1x"],
                    "12": m["odds_12"],
                    "X2": m["odds_x2"],
                }
            elif market_type == "Total":
                spread = m.get("spread", 2.5)
                key_name = f"O/U {spread:g}"
                entry["markets"][key_name] = {
                    "Over": m["odds_over"],
                    "Under": m["odds_under"],
                }

    # --- Second pass: try to get O/U 1.5 from Total tab ---
    try:
        total_url = base_url + MARKET_TABS["Total"]
        logger.info(f"[{league_name}] Navigating to Total tab for O/U 1.5 pass")
        await page.goto(total_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(WAIT_SECONDS)
        
        if await _switch_goals_header(page, "1.5"):
            ou15_matches = await _extract_matches_from_tab(page, "Total")
            for m in ou15_matches:
                key = (m["home"].lower().strip(), m["away"].lower().strip())
                if key in matches_by_key:
                    entry = matches_by_key[key]
                    spread = m.get("spread", 1.5)
                    key_name = f"O/U {spread:g}"
                    entry["markets"][key_name] = {
                        "Over": m["odds_over"],
                        "Under": m["odds_under"],
                    }
            logger.info(f"[{league_name}] O/U 1.5 pass extracted {len(ou15_matches)} matches")
    except Exception as e:
        logger.warning(f"[{league_name}] O/U 1.5 second pass failed: {e}")

    results = list(matches_by_key.values())[:max_matches]
    logger.info(f"[{league_name}] Total merged matches: {len(results)}")
    return results


async def scrape_betgr8(max_matches: int = 100, days: int = 2) -> List[dict]:
    """Main entry point: launch browser, scrape all leagues, return matches."""
    all_matches = []
    seen = set()
    
    logger.info("=== Betgr8 Scraper Starting ===")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        for league_name, base_url in LEAGUE_URLS.items():
            if len(all_matches) >= max_matches:
                break
            
            remaining = max_matches - len(all_matches)
            
            try:
                league_matches = await _scrape_league(page, league_name, base_url, remaining)
                
                for m in league_matches:
                    ev = m["event"]
                    parts = ev.split(" - ", 1)
                    key = (parts[0].lower().strip(), parts[1].lower().strip()) if len(parts) == 2 else (ev.lower(), "")
                    if key not in seen:
                        seen.add(key)
                        all_matches.append(m)
                        
            except Exception as e:
                logger.error(f"[{league_name}] Scrape failed: {e}")
                continue
        
        await browser.close()
    
    logger.info(f"=== Betgr8 Scraper Complete: {len(all_matches)} matches ===")
    return all_matches


def format_output(matches: List[dict]) -> str:
    """Format scraped matches for display."""
    if not matches:
        return "No matches found."
    
    lines = []
    for m in matches:
        lines.append(f"\n{m['event']} ({m['league']})")
        for market_name, odds in m.get("markets", {}).items():
            odds_str = " | ".join(f"{k}: {v}" for k, v in odds.items())
            lines.append(f"  {market_name}: {odds_str}")
    
    return "\n".join(lines)


if __name__ == "__main__":
    matches = asyncio.run(scrape_betgr8(max_matches=50))
    logger.info(format_output(matches))