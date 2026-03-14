"""
Betgr8 Scraper - DOM-based approach.
Navigates to league pages, waits for WebSocket data to render,
then extracts page text and HTML for parsing in Python.
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


async def _scrape_league(browser, league_name: str, url: str, seen: set,
                         max_matches: int, current_count: int) -> List[dict]:
    """Navigate to a league page and extract match data."""
    logger.info(f"[Scraper] Loading {league_name} from {url}")

    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    page = await context.new_page()

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Wait for WebSocket data to arrive and render
        logger.info(f"[Scraper] Waiting 15s for WebSocket data...")
        await asyncio.sleep(15)

        # Capture page text using Playwright's built-in method (safe, no JS eval issues)
        try:
            page_text = await page.inner_text("body")
        except Exception:
            page_text = ""
        logger.info(f"[DOM] Page text length: {len(page_text)}")

        # Log text in chunks for Railway log analysis
        for i in range(0, min(len(page_text), 3000), 400):
            chunk = page_text[i:i+400].replace("\n", " | ")
            logger.info(f"[DOM] TEXT[{i}]: {chunk}")

        # Capture page HTML using Playwright's built-in method
        try:
            page_html = await page.content()
        except Exception:
            page_html = ""
        logger.info(f"[DOM] HTML length: {len(page_html)}")

        # Extract class names from HTML using regex (no JS eval needed)
        all_classes = set(re.findall(r'class="([^"]*)"', page_html))
        flat_classes = set()
        for cls_str in all_classes:
            for c in cls_str.split():
                if len(c) > 2 and len(c) < 60:
                    flat_classes.add(c)

        # Find match/odds related classes
        keywords = ['event', 'match', 'fixture', 'game', 'odds', 'market',
                    'team', 'competitor', 'participant', 'score', 'bet',
                    'selection', 'outcome', 'price', 'coeff']
        match_classes = sorted([c for c in flat_classes
                               if any(k in c.lower() for k in keywords)])
        logger.info(f"[DOM] Total unique classes: {len(flat_classes)}")
        logger.info(f"[DOM] Match-related classes ({len(match_classes)}): {match_classes}")

        # Find odds-like numbers in page text
        odds_numbers = re.findall(r'\b\d{1,3}\.\d{2}\b', page_text)
        logger.info(f"[DOM] Odds-like numbers: {len(odds_numbers)} found")
        logger.info(f"[DOM] Odds sample: {odds_numbers[:30]}")

        # Log a sample of the HTML around odds-containing areas
        for pattern in ['event', 'match', 'fixture', 'odds', 'market']:
            idx = page_html.lower().find(pattern)
            if idx >= 0:
                start = max(0, idx - 100)
                end = min(len(page_html), idx + 400)
                sample = page_html[start:end].replace("\n", " ")
                logger.info(f"[DOM] HTML near '{pattern}' (pos {idx}): {sample}")

        return []  # Discovery phase - return empty for now

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
