"""
Betslip Checker — gets REAL bonus and potential win amounts.

• SportyBet: Uses Playwright to add selections to the actual betslip,
  then reads the displayed bonus and potential win.
• Bet9ja: Uses their documented formula (0% <5 sel, +5%/sel from 5, max 170%).
"""
import asyncio
from sportybet_scraper import TOURNAMENT_URLS

# ── JS: Click a specific match's odds button on SportyBet ──────────
JS_SB_CLICK_ODDS = """
({home, away, index}) => {
    const rows = document.querySelectorAll('.match-row');
    for (const row of rows) {
        const h = row.querySelector('.home-team')?.textContent?.trim() || '';
        const a = row.querySelector('.away-team')?.textContent?.trim() || '';
        if (h === home && a === away) {
            const odds = row.querySelectorAll('.m-outcome-odds');
            if (odds[index]) {
                odds[index].click();
                return {clicked: true, odds: odds[index].textContent.trim()};
            }
        }
    }
    return {clicked: false};
}
"""

# ── JS: Clear SportyBet betslip ────────────────────────────────────
JS_SB_CLEAR_BETSLIP = """
() => {
    // Click "Remove All" link
    const spans = document.querySelectorAll('span');
    for (const s of spans) {
        if (s.textContent.trim() === 'Remove All') {
            s.click();
            return true;
        }
    }
    // Fallback: click all individual X buttons
    const closeButtons = document.querySelectorAll('.m-bet-item .m-close, .m-icon-delete');
    closeButtons.forEach(b => b.click());
    return closeButtons.length > 0;
}
"""

# ── JS: Switch to "Multiple" tab in SportyBet betslip ──────────────
JS_SB_CLICK_MULTIPLE_TAB = """
() => {
    const tabs = document.querySelectorAll('.m-tab-item, [class*="tab"]');
    for (const tab of tabs) {
        if (tab.textContent.trim() === 'Multiple') {
            tab.click();
            return true;
        }
    }
    return false;
}
"""

# ── JS: Set stake in SportyBet betslip ──────────────────────────────
JS_SB_SET_STAKE = """
(stake) => {
    const inputs = document.querySelectorAll('input.m-input');
    for (const inp of inputs) {
        if (inp.placeholder && inp.placeholder.includes('min')) {
            // Clear and set new value using native input setter
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            nativeInputValueSetter.call(inp, stake.toString());
            inp.dispatchEvent(new Event('input', { bubbles: true }));
            inp.dispatchEvent(new Event('change', { bubbles: true }));
            return true;
        }
    }
    return false;
}
"""

# ── JS: Read SportyBet betslip values ──────────────────────────────
JS_SB_READ_BETSLIP = """
() => {
    const result = {};
    // Method 1: structured labels
    const labels = document.querySelectorAll('.m-label');
    for (const label of labels) {
        const text = label.textContent.trim();
        const nextEl = label.nextElementSibling;
        if (!nextEl) continue;
        const val = nextEl.textContent.trim().replace(/,/g, '');
        if (text === 'Odds' || text.includes('Odds')) result.odds = val;
        if (text === 'Total Stake') result.total_stake = val;
        if (text === 'Max bonus' || text.includes('bonus') || text.includes('Bonus')) result.max_bonus = val;
    }
    const potWinLabel = [...labels].find(l => l.textContent.includes('Potential Win'));
    if (potWinLabel) {
        const potWinVal = potWinLabel.nextElementSibling;
        if (potWinVal) result.potential_win = potWinVal.textContent.trim().replace(/,/g, '');
    }
    // Method 2: fallback - scan all text in betslip panel
    if (!result.odds || result.odds === '0') {
        const panel = document.querySelector('.m-bet-slip, .m-betslip, [class*="betslip"], [class*="bet-slip"]');
        if (panel) {
            const allText = panel.innerText || '';
            const oddsMatch = allText.match(/(?:Total\s*Odds|Odds)[:\s]*([\d,.]+)/i);
            if (oddsMatch) result.odds = oddsMatch[1].replace(/,/g, '');
            const bonusMatch = allText.match(/(?:Max\s*bonus|Bonus)[:\s]*([\d,.]+)/i);
            if (bonusMatch) result.max_bonus = bonusMatch[1].replace(/,/g, '');
            const winMatch = allText.match(/(?:Potential\s*Win|Est\.?\s*Win)[:\s]*([\d,.]+)/i);
            if (winMatch) result.potential_win = winMatch[1].replace(/,/g, '');
        }
    }
    // Count selections
    const selections = document.querySelectorAll('.m-bet-item, [class*="bet-item"]');
    result.selection_count = selections.length;
    return result;
}
"""

# ── JS: Click odds on Bet9ja ───────────────────────────────────────
JS_B9_CLICK_ODDS = """
({home, away, index}) => {
    // Find all sports-table rows
    const tables = document.querySelectorAll('.sports-table');
    for (const table of tables) {
        const homeEl = table.querySelector('.sports-table__home');
        const awayEl = table.querySelector('.sports-table__away');
        if (!homeEl || !awayEl) continue;
        const h = homeEl.textContent.trim();
        const a = awayEl.textContent.trim();
        if (h === home && a === away) {
            // First odds-list is 1X2
            const oddsList = table.querySelector('.sports-table__odds-list');
            if (!oddsList) continue;
            const items = oddsList.querySelectorAll('.sports-table__odds-item');
            if (items[index]) {
                items[index].click();
                return {clicked: true, odds: items[index].textContent.trim()};
            }
        }
    }
    return {clicked: false};
}
"""

# ── JS: Clear Bet9ja betslip ──────────────────────────────────────
JS_B9_CLEAR_BETSLIP = """
() => {
    const clearBtns = document.querySelectorAll('.basket-preset-values__item, button');
    for (const btn of clearBtns) {
        if (btn.textContent.trim() === 'Clear') {
            btn.click();
            return true;
        }
    }
    return false;
}
"""

# ── JS: Set stake on Bet9ja ────────────────────────────────────────
JS_B9_SET_STAKE = """
(stake) => {
    // Click the quick-stake 100 button
    const btns = document.querySelectorAll('.basket-preset-values__item');
    for (const btn of btns) {
        if (btn.textContent.trim() === stake.toString()) {
            btn.click();
            return true;
        }
    }
    // Fallback: set input directly
    const inputs = document.querySelectorAll('input.input');
    for (const inp of inputs) {
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value'
        ).set;
        nativeInputValueSetter.call(inp, stake.toString());
        inp.dispatchEvent(new Event('input', { bubbles: true }));
        inp.dispatchEvent(new Event('change', { bubbles: true }));
        return true;
    }
    return false;
}
"""

# ── JS: Read Bet9ja betslip values ─────────────────────────────────
JS_B9_READ_BETSLIP = """
() => {
    const result = {};
    // Total Odds
    const oddsEl = document.querySelector('strong.txt-primary');
    if (oddsEl) result.odds = oddsEl.textContent.trim().replace(/,/g, '');

    // Find Total Stake and Potential Win
    const tableRows = document.querySelectorAll('.table-f');
    for (const row of tableRows) {
        const text = row.textContent.trim();
        if (text.includes('Total Stake')) {
            const valEl = row.querySelector('.txt-r span') || row.querySelector('.txt-r');
            if (valEl) result.total_stake = valEl.textContent.trim().replace(/,/g, '');
        }
        if (text.includes('Potential Win')) {
            const valEl = row.querySelector('.txt-r strong') || row.querySelector('.txt-r');
            if (valEl) result.potential_win = valEl.textContent.trim().replace(/,/g, '');
        }
        if (text.includes('Bonus') || text.includes('bonus') || text.includes('Boost') || text.includes('boost')) {
            const valEl = row.querySelector('.txt-r') || row.querySelector('strong');
            if (valEl) result.bonus = valEl.textContent.trim().replace(/,/g, '');
        }
    }
    return result;
}
"""

# ── Bet9ja League page URLs ────────────────────────────────────────
BET9JA_LEAGUE_URLS = {
    "Premier League": "https://sports.bet9ja.com/popularCoupons/0/englandpremierleague/492",
    "La Liga": "https://sports.bet9ja.com/popularCoupons/0/spainlaliga/570",
    "Serie A": "https://sports.bet9ja.com/popularCoupons/0/italyseriea/538",
    "Bundesliga": "https://sports.bet9ja.com/popularCoupons/0/germanybundesliga/506",
    "Ligue 1": "https://sports.bet9ja.com/popularCoupons/0/franceligue1/498",
    "Champions League": "https://sports.bet9ja.com/popularCoupons/0/uefachampionsleague/480",
    "Europa League": "https://sports.bet9ja.com/popularCoupons/0/uefaeuropaleague/486",
    "Conference League": "https://sports.bet9ja.com/popularCoupons/0/uefaeuropaconferenceleague/180935",
}

SIGN_TO_INDEX = {"1": 0, "X": 1, "2": 2}


# ── Bet9ja bonus formula (documented: 170% Multiple Boost) ─────────
def calculate_bet9ja_bonus(num_selections: int, min_odds_met: bool = True) -> float:
    """
    Bet9ja's documented bonus: 0% for <5 selections, +5% per selection from 5 onwards.
    Max 170% at 38+ selections. All selections must have odds >= 1.20.
    Returns bonus percentage.
    """
    if not min_odds_met or num_selections < 5:
        return 0.0
    pct = (num_selections - 4) * 5  # 5->5%, 6->10%, 10->30%, 15->55%, 20->80%, 38->170%
    return min(pct, 170.0)

def calculate_bet9ja_returns(selections: list[dict], stake: float = 100) -> dict:
    """
    Calculate Bet9ja returns using their documented formula.
    selections: list of {odds: float}
    Returns: {odds, base_win, bonus_percent, bonus_amount, potential_win}
    """
    if not selections:
        return {"odds": 0, "base_win": 0, "bonus_percent": 0, "bonus_amount": 0, "potential_win": 0}

    combined_odds = 1.0
    qualifying_count = 0
    for sel in selections:
        odds = sel.get("bet9ja", sel.get("odds", 1.0))
        if isinstance(odds, str):
            odds = float(odds)
        combined_odds *= odds
        # Best Price events are excluded from Multiple Boost bonus
        if odds >= 1.20 and not sel.get("best_price", False):
            qualifying_count += 1

    base_win = stake * combined_odds
    bonus_pct = calculate_bet9ja_bonus(qualifying_count, qualifying_count > 0)
    bonus_amount = base_win * (bonus_pct / 100)
    potential_win = base_win + bonus_amount

    return {
        "odds": round(combined_odds, 2),
        "base_win": round(base_win, 2),
        "bonus_percent": bonus_pct,
        "bonus_amount": round(bonus_amount, 2),
        "potential_win": round(potential_win, 2),
    }


# ── SportyBet: Real betslip check via Playwright ───────────────────
async def check_sportybet_betslip(page, selections: list[dict], stake: float = 100) -> dict:
    """
    Add selections to SportyBet's real betslip and read actual bonus/win.

    selections: list of {
        league: str,        # e.g. "Premier League"
        sb_home: str,       # exact home team name as on SportyBet
        sb_away: str,       # exact away team name as on SportyBet
        sign: str,          # "1", "X", or "2"
        sportybet: float,   # expected odds value,
    }

    Returns: {odds, base_win, bonus_percent, bonus_amount, potential_win}
    """
    result = {
        "odds": 0, "base_win": 0, "bonus_percent": 0,
        "bonus_amount": 0, "potential_win": 0, "source": "betslip"
    }

    try:
        # Step 1: Clear any existing betslip
        await page.evaluate(JS_SB_CLEAR_BETSLIP)
        await page.wait_for_timeout(500)

        # Step 2: Group selections by league to minimize page navigations
        by_league = {}
        for sel in selections:
            league = sel.get("league", "")
            by_league.setdefault(league, []).append(sel)

        # Step 3: Navigate to each league and click odds
        clicked_count = 0
        for league, sels in by_league.items():
            url = TOURNAMENT_URLS.get(league)
            if not url:
                print(f"  [BetslipChecker] Unknown league: {league}")
                continue

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                await page.wait_for_selector(".match-row", timeout=15000)
            except Exception:
                print(f"  [BetslipChecker] No match rows on {league}")
                continue
            await page.wait_for_timeout(1000)

            for sel in sels:
                sign_index = SIGN_TO_INDEX.get(sel["sign"], 0)
                click_result = await page.evaluate(JS_SB_CLICK_ODDS, {
                    "home": sel["sb_home"],
                    "away": sel["sb_away"],
                    "index": sign_index,
                })
                if click_result and click_result.get("clicked"):
                    clicked_count += 1
                else:
                    print(f"  [BetslipChecker] Could not click {sel['sb_home']} vs {sel['sb_away']} sign={sel['sign']}")
                await page.wait_for_timeout(300)

        if clicked_count == 0:
            print("  [BetslipChecker] No selections were clicked, falling back to formula")
            return _sportybet_formula_fallback(selections, stake)

        # Step 4: Switch to Multiple tab if needed (appears when >1 selection)
        if clicked_count > 1:
            await page.evaluate(JS_SB_CLICK_MULTIPLE_TAB)
            await page.wait_for_timeout(500)

        # Step 5: Set stake
        await page.evaluate(JS_SB_SET_STAKE, stake)
        await page.wait_for_timeout(800)

        # Step 6: Read betslip values
        betslip = await page.evaluate(JS_SB_READ_BETSLIP)

        odds = _parse_float(betslip.get("odds", "0"))
        total_stake = _parse_float(betslip.get("total_stake", "0"))
        max_bonus = _parse_float(betslip.get("max_bonus", "0"))
        potential_win = _parse_float(betslip.get("potential_win", "0"))

        base_win = stake * odds if odds > 0 else 0
        bonus_pct = (max_bonus / base_win * 100) if base_win > 0 else 0

        result = {
            "odds": round(odds, 2),
            "base_win": round(base_win, 2),
            "bonus_percent": round(bonus_pct, 1),
            "bonus_amount": round(max_bonus, 2),
            "potential_win": round(potential_win, 2),
            "source": "betslip",
            "selections_clicked": clicked_count,
        }
        print(f"  [BetslipChecker] SportyBet betslip: {clicked_count} selections, "
              f"odds={odds}, bonus={max_bonus}, win={potential_win}")

    except Exception as e:
        print(f"  [BetslipChecker] SportyBet betslip check failed: {e}")
        return _sportybet_formula_fallback(selections, stake)

    return result


# ── Bet9ja: Real betslip check via Playwright (optional) ───────────
async def check_bet9ja_betslip(page, selections: list[dict], stake: float = 100) -> dict:
    """
    Add selections to Bet9ja's real betslip and read actual bonus/win.
    Falls back to formula if the website is unavailable.

    selections: list of {
        league: str,
        b9_home: str,       # exact home team name as on Bet9ja
        b9_away: str,       # exact away team name as on Bet9ja
        sign: str,          # "1", "X", or "2"
        bet9ja: float,      # expected odds value,
    }
    """
    try:
        # Step 1: Clear betslip
        await page.evaluate(JS_B9_CLEAR_BETSLIP)
        await page.wait_for_timeout(500)

        # Step 2: Group by league
        by_league = {}
        for sel in selections:
            league = sel.get("league", "")
            by_league.setdefault(league, []).append(sel)

        # Step 3: Navigate and click
        clicked_count = 0
        for league, sels in by_league.items():
            url = BET9JA_LEAGUE_URLS.get(league)
            if not url:
                continue

            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)  # Bet9ja loads slower

            for sel in sels:
                sign_index = SIGN_TO_INDEX.get(sel["sign"], 0)
                click_result = await page.evaluate(JS_B9_CLICK_ODDS, {
                    "home": sel["b9_home"],
                    "away": sel["b9_away"],
                    "index": sign_index,
                })
                if click_result and click_result.get("clicked"):
                    clicked_count += 1
                await page.wait_for_timeout(300)

        if clicked_count == 0:
            return calculate_bet9ja_returns(selections, stake)

        # Step 4: Click Multiple tab
        multiple_tabs = await page.query_selector_all('[class*="tab"]')
        for tab in multiple_tabs:
            text = await tab.inner_text()
            if "Multiple" in text:
                await tab.click()
                break
        await page.wait_for_timeout(500)

        # Step 5: Set stake
        await page.evaluate(JS_B9_SET_STAKE, stake)
        await page.wait_for_timeout(800)

        # Step 6: Read betslip
        betslip = await page.evaluate(JS_B9_READ_BETSLIP)

        odds = _parse_float(betslip.get("odds", "0"))
        potential_win = _parse_float(betslip.get("potential_win", "0"))
        total_stake = _parse_float(betslip.get("total_stake", "0"))
        bonus = _parse_float(betslip.get("bonus", "0"))

        base_win = stake * odds if odds > 0 else 0
        # If bonus not shown separately, derive from potential_win - base_win
        if bonus == 0 and potential_win > base_win:
            bonus = potential_win - base_win

        bonus_pct = (bonus / base_win * 100) if base_win > 0 else 0

        result = {
            "odds": round(odds, 2),
            "base_win": round(base_win, 2),
            "bonus_percent": round(bonus_pct, 1),
            "bonus_amount": round(bonus, 2),
            "potential_win": round(potential_win, 2),
            "source": "betslip",
            "selections_clicked": clicked_count,
        }
        print(f"  [BetslipChecker] Bet9ja betslip: {clicked_count} selections, "
              f"odds={odds}, bonus={bonus}, win={potential_win}")
        return result

    except Exception as e:
        print(f"  [BetslipChecker] Bet9ja betslip failed ({e}), using formula")
        return calculate_bet9ja_returns(selections, stake)


def _parse_float(val) -> float:
    """Safely parse a float from a string, handling commas and currency symbols."""
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).replace(",", "").replace("₦", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _sportybet_formula_fallback(selections: list[dict], stake: float = 100) -> dict:
    """Fallback formula for SportyBet when betslip check fails."""
    combined_odds = 1.0
    for sel in selections:
        odds = sel.get("sportybet", sel.get("odds", 1.0))
        if isinstance(odds, str):
            odds = float(odds)
        combined_odds *= odds

    base_win = stake * combined_odds

    # Approximate SportyBet bonus (estimated, marked as such)
    n = len(selections)
    approx_table = {
        2: 3, 3: 5, 4: 7, 5: 10, 6: 15, 7: 20, 8: 25, 9: 30,
        10: 35, 11: 40, 12: 50, 13: 60, 14: 70, 15: 80,
    }
    bonus_pct = approx_table.get(n, min(n * 5, 100)) if n >= 2 else 0
    bonus_amount = base_win * (bonus_pct / 100)

    return {
        "odds": round(combined_odds, 2),
        "base_win": round(base_win, 2),
        "bonus_percent": bonus_pct,
        "bonus_amount": round(bonus_amount, 2),
        "potential_win": round(base_win + bonus_amount, 2),
        "source": "estimate",
    }


# ── Main function: check all accumulators ──────────────────────────
async def check_all_accumulators(
    sb_page,
    b9_page,  # Can be None if Bet9ja website not available
    accumulators: list[dict],
    stake: float = 100,
) -> list[dict]:
    """
    For each accumulator, get real bonus/win from both bookmakers.

    accumulators: list of {
        size: int,
        selections: list of {
            event: str, sign: str,
            bet9ja: float, sportybet: float,
            league: str,
            sb_home: str, sb_away: str,
            b9_home: str, b9_away: str,
        }
    }

    Returns updated accumulators with real bet9ja/sportybet amounts.
    """
    results = []

    for i, acca in enumerate(accumulators):
        sels = acca["selections"]
        size = acca["size"]
        print(f"  [BetslipChecker] Checking accumulator #{i+1} ({size} selections)...")

        # SportyBet: real betslip
        sb_result = await check_sportybet_betslip(sb_page, sels, stake)

        # Bet9ja: real betslip if page available, otherwise formula
        if b9_page:
            b9_result = await check_bet9ja_betslip(b9_page, sels, stake)
        else:
            b9_result = calculate_bet9ja_returns(sels, stake)
            b9_result["source"] = "formula"

        results.append({
            "size": size,
            "selections": [
                {"event": s["event"], "sign": s["sign"], "bet9ja": s.get("bet9ja", 0), "sportybet": s.get("sportybet", 0)}
                for s in sels
            ],
            "bet9ja": b9_result,
            "sportybet": sb_result,
        })

    return results
