"""
Betgr8 Scraper - DOM-based approach.
Navigates to league pages and extracts match/odds data from the rendered DOM.
The Betgr8 site loads events via WebSocket push, so we wait for DOM to render.
"""
import asyncio
import json
import logging
import re
from playwright.async_api import async_playwright
from typing import Any, Dict, List

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

LEAGUE_URLS = {
    "Premier League": "https://betgr8.com/ng/sport/football/england/premier-league",
    "La Liga": "https://betgr8.com/ng/sport/football/spain/la-liga",
    "Serie A": "https://betgr8.com/ng/sport/football/italy/serie-a",
    "Bundesliga": "https://betgr8.com/ng/sport/football/germany/bundesliga",
    "Ligue 1": "https://betgr8.com/ng/sport/football/france/ligue-1",
    "Champions League": "https://betgr8.com/ng/sport/football/champions-league",
    "Europa League": "https://betgr8.com/ng/sport/football/europa-league",
}


async def _extract_dom_matches(page, league_name: str) -> List[dict]:
    """Extract matches from the rendered DOM using JavaScript evaluation."""
    # Phase 1: Discovery - find what CSS classes and structure the page uses
    dom_info = await page.evaluate("""
    () => {
        const info = {
            title: document.title,
            url: window.location.href,
            bodyText: document.body ? document.body.innerText.substring(0, 3000) : '',
            allClasses: [],
            matchCandidates: [],
            oddsNumbers: [],
            htmlSample: '',
        };

        // Safely get class name from any element (handles SVG elements)
        function getClass(el) {
            return el.getAttribute('class') || '';
        }

        // Collect unique class names from all elements
        const classSet = new Set();
        const allEls = document.querySelectorAll('*');
        for (let i = 0; i < allEls.length && i < 5000; i++) {
            const cls = getClass(allEls[i]);
            if (cls) {
                cls.split(/\s+/).forEach(c => {
                    if (c.length > 2 && c.length < 60) classSet.add(c);
                });
            }
        }
        info.allClasses = Array.from(classSet).sort();

        // Find elements with event/match/team/odds-related classes
        const keywords = ['event', 'match', 'fixture', 'game', 'odds', 'market',
                         'team', 'competitor', 'participant', 'score', 'bet',
                         'selection', 'outcome', 'price', 'coeff'];
        const matchClasses = info.allClasses.filter(c => {
            const lower = c.toLowerCase();
            return keywords.some(k => lower.includes(k));
        });
        info.matchClasses = matchClasses;


        // For each match-related class, count elements
        const classCounts = {};
        matchClasses.forEach(cls => {
            const els = document.querySelectorAll('.' + CSS.escape(cls));
            classCounts[cls] = els.length;
        });
        info.classCounts = classCounts;

        // Find all elements containing odds-like numbers (e.g. 1.50, 2.35)
        const oddsRegex = /\b\d{1,3}\.\d{2}\b/g;
        const textNodes = document.body ? document.body.innerText : '';
        const oddsMatches = textNodes.match(oddsRegex);
        info.oddsCount = oddsMatches ? oddsMatches.length : 0;
        info.oddsSample = oddsMatches ? oddsMatches.slice(0, 30) : [];

        // Get a sample of the main content HTML (first match-like section)
        const mainContent = document.querySelector('main') ||
                           document.querySelector('[role="main"]') ||
                           document.querySelector('#app') ||
                           document.querySelector('#root') ||
                           document.body;
        if (mainContent) {
            info.htmlSample = mainContent.innerHTML.substring(0, 5000);
        }

        // Try to find repeating row/card structures (likely match rows)
        // Look for elements that repeat 5+ times with same class and contain numbers
        const candidates = [];
        matchClasses.forEach(cls => {
            if (classCounts[cls] >= 3 && classCounts[cls] <= 200) {
                const els = document.querySelectorAll('.' + CSS.escape(cls));
                const sample = els[0];
                candidates.push({
                    class: cls,
                    count: classCounts[cls],
                    sampleText: sample ? sample.innerText.substring(0, 200) : '',
                    sampleHTML: sample ? sample.outerHTML.substring(0, 500) : '',
                    childCount: sample ? sample.children.length : 0,
                });
            }
        });
        info.matchCandidates = candidates;

        return info;
    }
    """)


    # Log discovery results
    logger.info(f"[DOM] Page title: {dom_info.get('title', 'N/A')}")
    logger.info(f"[DOM] URL: {dom_info.get('url', 'N/A')}")
    logger.info(f"[DOM] Total unique classes: {len(dom_info.get('allClasses', []))}")
    logger.info(f"[DOM] Match-related classes: {dom_info.get('matchClasses', [])}")
    logger.info(f"[DOM] Class counts: {dom_info.get('classCounts', {})}")
    logger.info(f"[DOM] Odds-like numbers found: {dom_info.get('oddsCount', 0)}")
    logger.info(f"[DOM] Odds sample: {dom_info.get('oddsSample', [])}")

    candidates = dom_info.get('matchCandidates', [])
    logger.info(f"[DOM] Match candidates ({len(candidates)}):")
    for c in candidates[:15]:
        logger.info(f"[DOM]   .{c['class']} (count={c['count']}, children={c['childCount']})")
        logger.info(f"[DOM]     Text: {c['sampleText'][:150]}")
        logger.info(f"[DOM]     HTML: {c['sampleHTML'][:300]}")

    # Log body text sample for manual inspection
    body_text = dom_info.get('bodyText', '')
    logger.info(f"[DOM] Body text sample (first 2000 chars):")
    # Split into chunks of 500 to avoid log line truncation
    for i in range(0, min(len(body_text), 2000), 500):
        logger.info(f"[DOM] TEXT[{i}:{i+500}]: {body_text[i:i+500]}")

    # Log HTML sample
    html_sample = dom_info.get('htmlSample', '')
    logger.info(f"[DOM] HTML sample length: {len(html_sample)}")
    for i in range(0, min(len(html_sample), 3000), 500):
        logger.info(f"[DOM] HTML[{i}:{i+500}]: {html_sample[i:i+500]}")

    return []  # Discovery phase - return empty for now


async def _scrape_league(browser, league_name: str, url: str, seen: set,
                         max_matches: int, current_count: int) -> List[dict]:
    """Navigate to a league page and extract match data from DOM."""
    logger.info(f"[Scraper] Loading {league_name} from {url}")

    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    page = await context.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for the page to fully render (WebSocket data arrives after load)
        logger.info(f"[Scraper] Waiting 15s for WebSocket data to load...")
        await asyncio.sleep(15)

        # Try waiting for specific selectors that might indicate data loaded
        try:
            await page.wait_for_selector('[class*="event"], [class*="match"], [class*="fixture"], [class*="game"]', timeout=10000)
            logger.info(f"[Scraper] Found event/match elements on page")
        except Exception:
            logger.info(f"[Scraper] No event/match selectors found, proceeding with DOM discovery anyway")

        # Extract DOM data
        logger.info(f"[Scraper] Extracting DOM data for {league_name}")
        results = await _extract_dom_matches(page, league_name)

        logger.info(f"[Scraper] {league_name}: found {len(results)} matches")
        return results

    except Exception as e:
        logger.error(f"[Scraper] Error scraping {league_name}: {e}", exc_info=True)
        return []
    finally:
        await context.close()


async def scrape_betgr8(max_matches: int = 100) -> List[dict]:
    """Main entry point for Betgr8 scraping."""
    logger.info(f"Starting Betgr8 scraper (target: {max_matches} matches)")

    all_matches = []
    seen = set()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        try:
            # Only scrape first 2 leagues in discovery phase
            for league_name, url in list(LEAGUE_URLS.items())[:2]:
                if len(all_matches) >= max_matches:
                    break
                league_matches = await _scrape_league(
                    browser, league_name, url, seen, max_matches, len(all_matches)
                )
                all_matches.extend(league_matches)
        finally:
            await browser.close()

    logger.info(f"[Scraper] Betgr8 completed: {len(all_matches)} events (timeout was 300s)")
    return all_matches


def format_output(matches: List[dict]) -> Dict[str, Any]:
    """Format scraped data into the standard format expected by main.py."""
    events = []
    for m in matches:
        event = {
            "event_name": m.get("event", "Unknown"),
            "league": m.get("league", "Unknown"),
            "markets": m.get("markets", {}),
        }
        events.append(event)

    return {
        "bookmaker": "betgr8",
        "events": events,
    }
