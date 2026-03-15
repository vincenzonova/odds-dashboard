"""
Live Betslip Scraper - Playwright-based live betslip verification.

For each bookmaker, navigates to their website, searches for specific events,
adds them to the betslip, and reads back the actual bonus % and potential winnings.

Uses a SEPARATE browser context to avoid interfering with normal odds scraping.
"""

import asyncio
import logging
import re
from typing import List, Dict, Optional
from difflib import SequenceMatcher
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

logger = logging.getLogger(__name__)

# ── Bookmaker base URLs ──────────────────────────────────────────────
SPORTYBET_BASE = "https://www.sportybet.com/ng"
BET9JA_BASE = "https://web.bet9ja.com"
MSPORT_BASE = "https://www.msport.com/ng"
BETGR8_BASE = "https://www.betgr8.com"

# Timeout for each bookmaker scrape (seconds)
BETSLIP_TIMEOUT = 120


def _fuzzy_match(a: str, b: str) -> float:
    """Return similarity ratio between two team names."""
    a = a.lower().strip()
    b = b.lower().strip()
    if a == b:
        return 1.0
    # Try removing common suffixes
    for suffix in [" fc", " sc", " cf"]:
        a = a.replace(suffix, "")
        b = b.replace(suffix, "")
    return SequenceMatcher(None, a, b).ratio()


def _best_team_match(target: str, candidates: list) -> Optional[str]:
    """Find the best fuzzy match for a team name."""
    best = None
    best_score = 0.0
    for c in candidates:
        score = _fuzzy_match(target, c)
        if score > best_score:
            best_score = score
            best = c
    return best if best_score >= 0.6 else None


# ── JS snippets for reading betslip data ─────────────────────────────

# SportyBet: reads betslip panel at bottom of page
JS_SPORTYBET_READ_BETSLIP = """
() => {
    const betslip = document.querySelector('.betslip-content, .m-betslip, [class*="betslip"]');
    if (!betslip) return {error: 'No betslip found'};
    
    // Count selections
    const items = betslip.querySelectorAll('.betslip-item, .m-bet-item, [class*="bet-item"]');
    const count = items.length;
    
    // Get total odds
    const oddsEl = betslip.querySelector('[class*="total-odds"], [class*="totalOdds"], .total-val');
    const totalOdds = oddsEl ? parseFloat(oddsEl.textContent.replace(/[^0-9.]/g, '')) : null;
    
    // Get bonus info
    const bonusEl = betslip.querySelector('[class*="bonus"], [class*="Bonus"]');
    const bonusText = bonusEl ? bonusEl.textContent : '';
    const bonusMatch = bonusText.match(/(\d+\.?\d*)%/);
    const bonusPercent = bonusMatch ? parseFloat(bonusMatch[1]) : 0;
    
    // Get potential win
    const winEl = betslip.querySelector('[class*="potential"], [class*="win"], [class*="payout"], .est-winning');
    const potentialWin = winEl ? parseFloat(winEl.textContent.replace(/[^0-9.]/g, '')) : null;
    
    // Get stake
    const stakeEl = betslip.querySelector('input[class*="stake"], input[type="number"], input[class*="amount"]');
    const stake = stakeEl ? parseFloat(stakeEl.value) : null;
    
    return {count, totalOdds, bonusPercent, potentialWin, stake};
}
"""

# Bet9ja: reads betslip/coupon panel
JS_BET9JA_READ_BETSLIP = """
() => {
    const betslip = document.querySelector('.coupon-container, .betslip, [class*="betslip"], [class*="coupon"]');
    if (!betslip) return {error: 'No betslip found'};
    
    const items = betslip.querySelectorAll('.coupon-event, .bet-item, [class*="selection"]');
    const count = items.length;
    
    const oddsEl = betslip.querySelector('[class*="total-odds"], [class*="totalOdds"]');
    const totalOdds = oddsEl ? parseFloat(oddsEl.textContent.replace(/[^0-9.]/g, '')) : null;
    
    const bonusEl = betslip.querySelector('[class*="bonus"], [class*="Bonus"]');
    const bonusText = bonusEl ? bonusEl.textContent : '';
    const bonusMatch = bonusText.match(/(\d+\.?\d*)%/);
    const bonusPercent = bonusMatch ? parseFloat(bonusMatch[1]) : 0;
    
    const winEl = betslip.querySelector('[class*="potential"], [class*="win"], [class*="payout"]');
    const potentialWin = winEl ? parseFloat(winEl.textContent.replace(/[^0-9.]/g, '')) : null;
    
    const stakeEl = betslip.querySelector('input[class*="stake"], input[type="number"]');
    const stake = stakeEl ? parseFloat(stakeEl.value) : null;
    
    return {count, totalOdds, bonusPercent, potentialWin, stake};
}
"""

# MSport: reads betslip panel
JS_MSPORT_READ_BETSLIP = """
() => {
    const betslip = document.querySelector('[class*="betslip"], [class*="bet-slip"], .slip-body');
    if (!betslip) return {error: 'No betslip found'};
    
    const items = betslip.querySelectorAll('[class*="slip-item"], [class*="bet-item"]');
    const count = items.length;
    
    const oddsEl = betslip.querySelector('[class*="total-odds"], [class*="totalOdds"]');
    const totalOdds = oddsEl ? parseFloat(oddsEl.textContent.replace(/[^0-9.]/g, '')) : null;
    
    const bonusEl = betslip.querySelector('[class*="bonus"], [class*="Bonus"]');
    const bonusText = bonusEl ? bonusEl.textContent : '';
    const bonusMatch = bonusText.match(/(\d+\.?\d*)%/);
    const bonusPercent = bonusMatch ? parseFloat(bonusMatch[1]) : 0;
    
    const winEl = betslip.querySelector('[class*="potential"], [class*="win"], [class*="payout"]');
    const potentialWin = winEl ? parseFloat(winEl.textContent.replace(/[^0-9.]/g, '')) : null;
    
    return {count, totalOdds, bonusPercent, potentialWin};
}
"""

# Betgr8: reads betslip panel
JS_BETGR8_READ_BETSLIP = """
() => {
    const betslip = document.querySelector('[class*="betslip"], [class*="bet-slip"], [class*="coupon"]');
    if (!betslip) return {error: 'No betslip found'};
    
    const items = betslip.querySelectorAll('[class*="slip-item"], [class*="bet-item"], [class*="selection"]');
    const count = items.length;
    
    const oddsEl = betslip.querySelector('[class*="total-odds"], [class*="totalOdds"]');
    const totalOdds = oddsEl ? parseFloat(oddsEl.textContent.replace(/[^0-9.]/g, '')) : null;
    
    const bonusEl = betslip.querySelector('[class*="bonus"], [class*="Bonus"]');
    const bonusText = bonusEl ? bonusEl.textContent : '';
    const bonusMatch = bonusText.match(/(\d+\.?\d*)%/);
    const bonusPercent = bonusMatch ? parseFloat(bonusMatch[1]) : 0;
    
    const winEl = betslip.querySelector('[class*="potential"], [class*="win"], [class*="payout"]');
    const potentialWin = winEl ? parseFloat(winEl.textContent.replace(/[^0-9.]/g, '')) : null;
    
    return {count, totalOdds, bonusPercent, potentialWin};
}
"""


# ── Core scraping functions ──────────────────────────────────────────

async def _create_browser_context(playwright) -> tuple:
    """Create an isolated browser + context for betslip scraping."""
    browser = await playwright.chromium.launch(
        headless=True,
        args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
    )
    context = await browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    return browser, context


async def scrape_sportybet_betslip(
    page: Page, selections: List[Dict], stake: float
) -> Dict:
    """
    Navigate SportyBet, add selections to betslip, read bonus + winnings.
    
    Each selection: {event, home, away, sign, market, odds}
    sign: "1" = home, "X" = draw, "2" = away
    """
    result = {"bookmaker": "sportybet", "status": "pending", "selections_found": 0}
    
    try:
        # Go to SportyBet football page
        await page.goto(f"{SPORTYBET_BASE}/sport/football", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        # Clear any existing betslip
        try:
            clear_btn = page.locator('[class*="clear"], [class*="remove-all"], [class*="delete-all"]')
            if await clear_btn.count() > 0:
                await clear_btn.first.click()
                await page.wait_for_timeout(1000)
        except Exception:
            pass
        
        found_count = 0
        for sel in selections:
            try:
                home = sel.get("home", sel.get("event", "").split(" - ")[0] if " - " in sel.get("event", "") else "")
                away = sel.get("away", sel.get("event", "").split(" - ")[1] if " - " in sel.get("event", "") else "")
                sign = sel.get("sign", "1")
                
                # Use search to find the event
                search_input = page.locator('input[placeholder*="Search"], input[class*="search"]')
                if await search_input.count() > 0:
                    await search_input.first.fill(home)
                    await page.wait_for_timeout(2000)
                    
                    # Look for the match row
                    match_rows = page.locator('.match-row, [class*="match-item"], [class*="event-row"]')
                    row_count = await match_rows.count()
                    
                    for i in range(min(row_count, 10)):
                        row_text = await match_rows.nth(i).text_content()
                        if row_text and _fuzzy_match(home, row_text.split("\n")[0] if "\n" in row_text else row_text) > 0.5:
                            # Found the match - click the right odds button
                            odds_buttons = match_rows.nth(i).locator('.m-outcome-odds, [class*="odds-btn"], [class*="outcome"]')
                            btn_count = await odds_buttons.count()
                            
                            # Map sign to button index (1=0, X=1, 2=2)
                            idx = {"1": 0, "X": 1, "2": 2}.get(sign.upper(), 0)
                            if idx < btn_count:
                                await odds_buttons.nth(idx).click()
                                await page.wait_for_timeout(1000)
                                found_count += 1
                            break
                    
                    # Clear search
                    await search_input.first.fill("")
                    await page.wait_for_timeout(500)
                    
            except Exception as e:
                logger.warning(f"SportyBet: failed to add selection {sel}: {e}")
        
        result["selections_found"] = found_count
        
        if found_count == 0:
            result["status"] = "no_selections_found"
            return result
        
        # Set stake amount
        try:
            stake_input = page.locator('input[class*="stake"], input[class*="amount"], input[type="number"]')
            if await stake_input.count() > 0:
                await stake_input.first.fill(str(int(stake)))
                await page.wait_for_timeout(1000)
        except Exception as e:
            logger.warning(f"SportyBet: could not set stake: {e}")
        
        # Read betslip data
        betslip_data = await page.evaluate(JS_SPORTYBET_READ_BETSLIP)
        
        if betslip_data and "error" not in betslip_data:
            result.update({
                "status": "success",
                "total_odds": betslip_data.get("totalOdds"),
                "bonus_percent": betslip_data.get("bonusPercent", 0),
                "potential_win": betslip_data.get("potentialWin"),
                "stake": stake,
            })
        else:
            result["status"] = "betslip_read_failed"
            result["error"] = betslip_data.get("error", "Unknown error")
            
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    
    return result


async def scrape_bet9ja_betslip(
    page: Page, selections: List[Dict], stake: float
) -> Dict:
    """Navigate Bet9ja, add selections to betslip, read bonus + winnings."""
    result = {"bookmaker": "bet9ja", "status": "pending", "selections_found": 0}
    
    try:
        await page.goto(f"{BET9JA_BASE}/Sport/Default.aspx", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        found_count = 0
        for sel in selections:
            try:
                home = sel.get("home", sel.get("event", "").split(" - ")[0] if " - " in sel.get("event", "") else "")
                sign = sel.get("sign", "1")
                
                # Bet9ja uses search
                search_input = page.locator('#searchInput, input[placeholder*="Search"], input[class*="search"]')
                if await search_input.count() > 0:
                    await search_input.first.fill(home)
                    await page.wait_for_timeout(2000)
                    
                    match_rows = page.locator('.EventRow, [class*="event-row"], [class*="match-row"]')
                    row_count = await match_rows.count()
                    
                    for i in range(min(row_count, 10)):
                        row_text = await match_rows.nth(i).text_content()
                        if row_text and _fuzzy_match(home, row_text) > 0.4:
                            odds_buttons = match_rows.nth(i).locator('.OddVal, [class*="odds"], [class*="outcome"]')
                            btn_count = await odds_buttons.count()
                            
                            idx = {"1": 0, "X": 1, "2": 2}.get(sign.upper(), 0)
                            if idx < btn_count:
                                await odds_buttons.nth(idx).click()
                                await page.wait_for_timeout(1000)
                                found_count += 1
                            break
                    
                    await search_input.first.fill("")
                    await page.wait_for_timeout(500)
                    
            except Exception as e:
                logger.warning(f"Bet9ja: failed to add selection {sel}: {e}")
        
        result["selections_found"] = found_count
        
        if found_count == 0:
            result["status"] = "no_selections_found"
            return result
        
        # Set stake
        try:
            stake_input = page.locator('input[class*="stake"], input[id*="stake"], input[type="number"]')
            if await stake_input.count() > 0:
                await stake_input.first.fill(str(int(stake)))
                await page.wait_for_timeout(1000)
        except Exception:
            pass
        
        betslip_data = await page.evaluate(JS_BET9JA_READ_BETSLIP)
        
        if betslip_data and "error" not in betslip_data:
            result.update({
                "status": "success",
                "total_odds": betslip_data.get("totalOdds"),
                "bonus_percent": betslip_data.get("bonusPercent", 0),
                "potential_win": betslip_data.get("potentialWin"),
                "stake": stake,
            })
        else:
            result["status"] = "betslip_read_failed"
            result["error"] = betslip_data.get("error", "Unknown error")
            
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    
    return result


async def scrape_msport_betslip(
    page: Page, selections: List[Dict], stake: float
) -> Dict:
    """Navigate MSport, add selections to betslip, read bonus + winnings."""
    result = {"bookmaker": "msport", "status": "pending", "selections_found": 0}
    
    try:
        await page.goto(f"{MSPORT_BASE}/sport/football", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        found_count = 0
        for sel in selections:
            try:
                home = sel.get("home", sel.get("event", "").split(" - ")[0] if " - " in sel.get("event", "") else "")
                sign = sel.get("sign", "1")
                
                search_input = page.locator('input[placeholder*="Search"], input[class*="search"]')
                if await search_input.count() > 0:
                    await search_input.first.fill(home)
                    await page.wait_for_timeout(2000)
                    
                    match_rows = page.locator('[class*="match-item"], [class*="event-row"], [class*="game-item"]')
                    row_count = await match_rows.count()
                    
                    for i in range(min(row_count, 10)):
                        row_text = await match_rows.nth(i).text_content()
                        if row_text and _fuzzy_match(home, row_text) > 0.4:
                            odds_buttons = match_rows.nth(i).locator('[class*="odds"], [class*="outcome"], button')
                            btn_count = await odds_buttons.count()
                            
                            idx = {"1": 0, "X": 1, "2": 2}.get(sign.upper(), 0)
                            if idx < btn_count:
                                await odds_buttons.nth(idx).click()
                                await page.wait_for_timeout(1000)
                                found_count += 1
                            break
                    
                    await search_input.first.fill("")
                    await page.wait_for_timeout(500)
                    
            except Exception as e:
                logger.warning(f"MSport: failed to add selection {sel}: {e}")
        
        result["selections_found"] = found_count
        
        if found_count == 0:
            result["status"] = "no_selections_found"
            return result
        
        try:
            stake_input = page.locator('input[class*="stake"], input[type="number"]')
            if await stake_input.count() > 0:
                await stake_input.first.fill(str(int(stake)))
                await page.wait_for_timeout(1000)
        except Exception:
            pass
        
        betslip_data = await page.evaluate(JS_MSPORT_READ_BETSLIP)
        
        if betslip_data and "error" not in betslip_data:
            result.update({
                "status": "success",
                "total_odds": betslip_data.get("totalOdds"),
                "bonus_percent": betslip_data.get("bonusPercent", 0),
                "potential_win": betslip_data.get("potentialWin"),
                "stake": stake,
            })
        else:
            result["status"] = "betslip_read_failed"
            result["error"] = betslip_data.get("error", "Unknown error")
            
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    
    return result


async def scrape_betgr8_betslip(
    page: Page, selections: List[Dict], stake: float
) -> Dict:
    """Navigate Betgr8, add selections to betslip, read bonus + winnings."""
    result = {"bookmaker": "betgr8", "status": "pending", "selections_found": 0}
    
    try:
        await page.goto(BETGR8_BASE, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)
        
        found_count = 0
        for sel in selections:
            try:
                home = sel.get("home", sel.get("event", "").split(" - ")[0] if " - " in sel.get("event", "") else "")
                sign = sel.get("sign", "1")
                
                search_input = page.locator('input[placeholder*="Search"], input[class*="search"]')
                if await search_input.count() > 0:
                    await search_input.first.fill(home)
                    await page.wait_for_timeout(2000)
                    
                    match_rows = page.locator('[class*="match"], [class*="event-row"], [class*="game"]')
                    row_count = await match_rows.count()
                    
                    for i in range(min(row_count, 10)):
                        row_text = await match_rows.nth(i).text_content()
                        if row_text and _fuzzy_match(home, row_text) > 0.4:
                            odds_buttons = match_rows.nth(i).locator('[class*="odds"], [class*="outcome"], button')
                            btn_count = await odds_buttons.count()
                            
                            idx = {"1": 0, "X": 1, "2": 2}.get(sign.upper(), 0)
                            if idx < btn_count:
                                await odds_buttons.nth(idx).click()
                                await page.wait_for_timeout(1000)
                                found_count += 1
                            break
                    
                    await search_input.first.fill("")
                    await page.wait_for_timeout(500)
                    
            except Exception as e:
                logger.warning(f"Betgr8: failed to add selection {sel}: {e}")
        
        result["selections_found"] = found_count
        
        if found_count == 0:
            result["status"] = "no_selections_found"
            return result
        
        betslip_data = await page.evaluate(JS_BETGR8_READ_BETSLIP)
        
        if betslip_data and "error" not in betslip_data:
            result.update({
                "status": "success",
                "total_odds": betslip_data.get("totalOdds"),
                "bonus_percent": betslip_data.get("bonusPercent", 0),
                "potential_win": betslip_data.get("potentialWin"),
                "stake": stake,
            })
        else:
            result["status"] = "betslip_read_failed"
            result["error"] = betslip_data.get("error", "Unknown error")
            
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    
    return result


# ── Dispatcher mapping ───────────────────────────────────────────────

BOOKMAKER_SCRAPERS = {
    "sportybet": scrape_sportybet_betslip,
    "bet9ja": scrape_bet9ja_betslip,
    "msport": scrape_msport_betslip,
    "betgr8": scrape_betgr8_betslip,
}


async def scrape_live_betslips(
    selections: List[Dict],
    stake: float = 100.0,
    bookmakers: List[str] = None,
) -> Dict[str, Dict]:
    """
    Main entry point: scrape live betslips for selected bookmakers.
    
    Uses a SEPARATE Playwright browser instance to avoid interfering
    with the normal odds scraping pipeline.
    
    Args:
        selections: List of dicts with event info (event, home, away, sign, market)
        stake: Bet stake amount
        bookmakers: List of bookmaker keys to scrape (default: all 4)
    
    Returns:
        Dict mapping bookmaker key to scrape result
    """
    if bookmakers is None:
        bookmakers = ["bet9ja", "sportybet", "msport", "betgr8"]
    
    results = {}
    
    async with async_playwright() as pw:
        browser, context = await _create_browser_context(pw)
        
        try:
            for bm in bookmakers:
                scraper_fn = BOOKMAKER_SCRAPERS.get(bm)
                if not scraper_fn:
                    results[bm] = {"bookmaker": bm, "status": "unknown_bookmaker"}
                    continue
                
                page = await context.new_page()
                try:
                    result = await asyncio.wait_for(
                        scraper_fn(page, selections, stake),
                        timeout=BETSLIP_TIMEOUT,
                    )
                    results[bm] = result
                except asyncio.TimeoutError:
                    results[bm] = {"bookmaker": bm, "status": "timeout"}
                except Exception as e:
                    results[bm] = {"bookmaker": bm, "status": "error", "error": str(e)}
                finally:
                    await page.close()
        finally:
            await context.close()
            await browser.close()
    
    return results
