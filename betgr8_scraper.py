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
    matches = []

    # First, log the DOM structure to understand what's rendered
    dom_info = await page.evaluate("""
    () => {
        const info = {
            title: document.title,
            bodyClasses: document.body.className,
            // Find all elements that might contain match data
            allClasses: [],
            matchCandidates: [],
            textSamples: [],
        };

        // Collect unique class names from the page
        const allEls = document.querySelectorAll('*');
        const classSet = new Set();
        for (let i = 0; i < Math.min(allEls.length, 5000); i++) {
            const cls = allEls[i].className;
            if (typeof cls === 'string' && cls.length > 0 && cls.length < 100) {
                cls.split(/\\s+/).forEach(c => classSet.add(c));
            }
        }
        info.allClasses = [...classSet].sort().slice(0, 200);

        // Look for elements containing 'vs', '-', team-like patterns
        const textEls = document.querySelectorAll('[class*=event], [class*=match], [class*=game], [class*=fixture], [class*=team], [class*=competitor], [class*=participant], [class*=odd], [class*=market], [class*=bet], [class*=selection], [class*=price], [class*=coeff]');
        info.matchCandidates = [];
        for (let i = 0; i < Math.min(textEls.length, 50); i++) {
            info.matchCandidates.push({
                tag: textEls[i].tagName,
                cls: textEls[i].className.substring(0, 100),
                text: textEls[i].textContent.substring(0, 200).trim(),
                childCount: textEls[i].children.length,
            });
        }

        // Also get text content samples from the main content area
        const mainContent = document.querySelector('main, #app, #root, [class*=content], [class*=sport], [class*=sportsbook]');
        if (mainContent) {
            info.mainContentTag = mainContent.tagName;
            info.mainContentClass = mainContent.className.substring(0, 100);
            // Get direct children info
            info.mainChildren = [];
            for (let i = 0; i < Math.min(mainContent.children.length, 20); i++) {
                const child = mainContent.children[i];
                info.mainChildren.push({
                    tag: child.tagName,
                    cls: child.className.substring(0, 100),
                    text: child.textContent.substring(0, 150).trim(),
                });
            }
        }

        // Look for any elements with numeric content that look like odds (1.xx - 99.xx)
        const allText = document.body.innerText;
        const oddsPattern = /\\b\\d{1,2}\\.\\d{2}\\b/g;
        const oddsMatches = allText.match(oddsPattern);
        info.oddsFound = oddsMatches ? oddsMatches.length : 0;
        info.oddsSamples = oddsMatches ? oddsMatches.slice(0, 20) : [];

        // Get total text length
        info.totalTextLength = allText.length;
        info.textSample = allText.substring(0, 500);

        return info;
    }
    """)

    logger.info(f"[DOM] Page title: {dom_info.get('title')}")
    logger.info(f"[DOM] Total text length: {dom_info.get('totalTextLength')}")
    logger.info(f"[DOM] Odds-like numbers found: {dom_info.get('oddsFound')}")
    logger.info(f"[DOM] Odds samples: {dom_info.get('oddsSamples', [])[:10]}")
    logger.debug(f"[DOM] Text sample (500 chars): {dom_info.get('textSample', '')[:500]}")

    # Log class names that might be relevant
    classes = dom_info.get('allClasses', [])
    relevant_cls = [c for c in classes if any(kw in c.lower() for kw in ['event', 'match', 'game', 'team', 'odd', 'market', 'bet', 'price', 'fixture', 'competitor', 'score', 'coeff', 'selection'])]
    logger.info(f"[DOM] Relevant CSS classes: {relevant_cls[:50]}")

    # Log match candidates
    candidates = dom_info.get('matchCandidates', [])
    logger.info(f"[DOM] Match candidate elements: {len(candidates)}")
    for i, c in enumerate(candidates[:10]):
        logger.debug(f"[DOM] Candidate #{i}: <{c['tag']} class='{c['cls']}'> children={c['childCount']} text='{c['text'][:100]}'") 

    # Log main content children
    main_children = dom_info.get('mainChildren', [])
    if main_children:
        logger.info(f"[DOM] Main content: <{dom_info.get('mainContentTag')} class='{dom_info.get('mainContentClass')}'>")
        for i, ch in enumerate(main_children[:10]):
            logger.debug(f"[DOM] MainChild #{i}: <{ch['tag']} class='{ch['cls']}'> text='{ch['text'][:80]}'") 

    return matches


async def _scrape_league(browser, league_name: str, url: str, seen: set,
                        max_matches: int, current_count: int) -> List[dict]:
    results = []
    page = await browser.new_page()

    # Block heavy resources
    await page.route("**/*.{png,jpg,jpeg,gif,webp,woff,woff2,svg}",
                     lambda r: r.abort())

    logger.info(f"[Scraper] Loading {league_name} from {url}")
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        logger.error(f"[Scraper] Failed to load {league_name}: {e}")
        await page.close()
        return results

    # Wait for page to render - events come via WebSocket push
    logger.info(f"[Scraper] Waiting 15s for WebSocket data to arrive...")
    await page.wait_for_timeout(15000)

    # Try to wait for specific selectors that might contain events
    for selector in ['[class*=event]', '[class*=match]', '[class*=fixture]', '[class*=game-card]', '[class*=coupon]']:
        try:
            await page.wait_for_selector(selector, timeout=3000)
            logger.info(f"[Scraper] Found selector: {selector}")
            break
        except:
            pass

    # Extract match data from DOM
    logger.info(f"[Scraper] Extracting DOM data for {league_name}")
    results = await _extract_dom_matches(page, league_name)

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
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )

        # Only scrape first 2 leagues in this discovery phase
        for league_name, url in list(LEAGUE_URLS.items())[:2]:
            if len(results) >= max_matches:
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

    logger.info(f"Scraping complete - {len(results)} matches total")
    return results


def format_output(matches: List[dict]) -> List[dict]:
    formatted = []
    for match in matches:
        formatted.append({
            "event": match.get("event", ""),
            "league": match.get("league", ""),
            "markets": match.get("markets", {}),
        })
    return formatted


if __name__ == "__main__":
    data = asyncio.run(scrape_betgr8(max_matches=20))
    output = format_output(data)
    print(json.dumps(output, indent=2))
