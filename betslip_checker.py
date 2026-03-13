"""
Betslip Checker & Return Calculator for 5 Bookmakers
Supports: Bet9ja, SportyBet, BetKing, MSport, Betano
"""

import re
from datetime import datetime
from typing import List, Dict, Any, Optional


# ============================================================================
# BET9JA CALCULATIONS (EXISTING - UNCHANGED)
# ============================================================================

def calculate_bet9ja_bonus(num_selections: int, min_odds_met: bool = True) -> float:
    """
    Bet9ja bonus: 0% for <3, 5% for 3, 10% for 4, 15% for 5+
    Min odds per selection: 1.20
    """
    if not min_odds_met or num_selections < 3:
        return 0.0

    if num_selections == 3:
        return 5.0
    elif num_selections == 4:
        return 10.0
    else:  # 5+
        return 15.0


def calculate_bet9ja_returns(selections: List[Dict], stake: float = 100.0) -> Dict[str, Any]:
    """
    Calculate Bet9ja returns using their documented bonus structure.
    Min qualifying odds per selection: 1.20
    """
    if not selections:
        return {
            "odds": 0.0,
            "base_win": 0.0,
            "bonus_percent": 0.0,
            "bonus_amount": 0.0,
            "potential_win": 0.0,
            "source": "calculated",
            "error": "No selections provided",
        }

    try:
        # Extract Bet9ja odds and validate
        odds_list = []
        for selection in selections:
            odds_str = selection.get("bet9ja", "â")
            if odds_str == "â":
                return {
                    "odds": 0.0,
                    "base_win": 0.0,
                    "bonus_percent": 0.0,
                    "bonus_amount": 0.0,
                    "potential_win": 0.0,
                    "source": "calculated",
                    "error": f"Missing Bet9ja odds for {selection.get('event', 'unknown')}",
                }

            try:
                odds = float(odds_str)
                if odds < 1.20:
                    return {
                        "odds": 0.0,
                        "base_win": 0.0,
                        "bonus_percent": 0.0,
                        "bonus_amount": 0.0,
                        "potential_win": 0.0,
                        "source": "calculated",
                        "error": f"Odds {odds} below minimum 1.20 for {selection.get('event')}",
                    }
                odds_list.append(odds)
            except (ValueError, TypeError):
                return {
                    "odds": 0.0,
                    "base_win": 0.0,
                    "bonus_percent": 0.0,
                    "bonus_amount": 0.0,
                    "potential_win": 0.0,
                    "source": "calculated",
                    "error": f"Invalid odds format: {odds_str}",
                }

        # Calculate combined odds
        combined_odds = 1.0
        for odds in odds_list:
            combined_odds *= odds

        # Calculate base win
        base_win = stake * combined_odds

        # Calculate bonus
        bonus_percent = calculate_bet9ja_bonus(len(selections), min_odds_met=True)
        bonus_amount = base_win * bonus_percent / 100.0

        return {
            "odds": round(combined_odds, 4),
            "base_win": round(base_win, 2),
            "bonus_percent": bonus_percent,
            "bonus_amount": round(bonus_amount, 2),
            "potential_win": round(base_win + bonus_amount, 2),
            "source": "calculated",
        }

    except Exception as e:
        return {
            "odds": 0.0,
            "base_win": 0.0,
            "bonus_percent": 0.0,
            "bonus_amount": 0.0,
            "potential_win": 0.0,
            "source": "calculated",
            "error": str(e),
        }


# ============================================================================
# SPORTYBET CALCULATIONS (EXISTING - UNCHANGED)
# ============================================================================

def calculate_sportybet_bonus(num_selections: int, min_odds_met: bool = True) -> float:
    """
    SportyBet bonus varies by number of selections.
    Min odds per selection: 1.20
    Bonus table:
    2->10%, 3->15%, 4->20%, 5->25%, 6->30%, 7->35%, 8->40%,
    9->45%, 10->50%, 11->55%, 12->60%, 13->65%, 14->70%, 15+->75%
    """
    if not min_odds_met or num_selections < 2:
        return 0.0

    bonus_table = {
        2: 10.0,
        3: 15.0,
        4: 20.0,
        5: 25.0,
        6: 30.0,
        7: 35.0,
        8: 40.0,
        9: 45.0,
        10: 50.0,
        11: 55.0,
        12: 60.0,
        13: 65.0,
        14: 70.0,
    }

    return bonus_table.get(num_selections, 75.0)


def _sportybet_formula_fallback(selections: List[Dict], stake: float = 100.0) -> Dict[str, Any]:
    """
    Calculate SportyBet returns using their documented bonus structure.
    Min qualifying odds per selection: 1.20
    """
    if not selections:
        return {
            "odds": 0.0,
            "base_win": 0.0,
            "bonus_percent": 0.0,
            "bonus_amount": 0.0,
            "potential_win": 0.0,
            "source": "calculated",
            "error": "No selections provided",
        }

    try:
        # Extract SportyBet odds and validate
        odds_list = []
        for selection in selections:
            odds_str = selection.get("sportybet", "â")
            if odds_str == "â":
                return {
                    "odds": 0.0,
                    "base_win": 0.0,
                    "bonus_percent": 0.0,
                    "bonus_amount": 0.0,
                    "potential_win": 0.0,
                    "source": "calculated",
                    "error": f"Missing SportyBet odds for {selection.get('event', 'unknown')}",
                }

            try:
                odds = float(odds_str)
                if odds < 1.20:
                    return {
                        "odds": 0.0,
                        "base_win": 0.0,
                        "bonus_percent": 0.0,
                        "bonus_amount": 0.0,
                        "potential_win": 0.0,
                        "source": "calculated",
                        "error": f"Odds {odds} below minimum 1.20 for {selection.get('event')}",
                    }
                odds_list.append(odds)
            except (ValueError, TypeError):
                return {
                    "odds": 0.0,
                    "base_win": 0.0,
                    "bonus_percent": 0.0,
                    "bonus_amount": 0.0,
                    "potential_win": 0.0,
                    "source": "calculated",
                    "error": f"Invalid odds format: {odds_str}",
                }

        # Calculate combined odds
        combined_odds = 1.0
        for odds in odds_list:
            combined_odds *= odds

        # Calculate base win
        base_win = stake * combined_odds

        # Calculate bonus
        bonus_percent = calculate_sportybet_bonus(len(selections), min_odds_met=True)
        bonus_amount = base_win * bonus_percent / 100.0

        return {
            "odds": round(combined_odds, 4),
            "base_win": round(base_win, 2),
            "bonus_percent": bonus_percent,
            "bonus_amount": round(bonus_amount, 2),
            "potential_win": round(base_win + bonus_amount, 2),
            "source": "calculated",
        }

    except Exception as e:
        return {
            "odds": 0.0,
            "base_win": 0.0,
            "bonus_percent": 0.0,
            "bonus_amount": 0.0,
            "potential_win": 0.0,
            "source": "calculated",
            "error": str(e),
        }


# ============================================================================
# BETKING CALCULATIONS (NEW)
# ============================================================================

def calculate_betking_bonus(num_selections: int, min_odds_met: bool = True) -> float:
    """
    BetKing bonus: 0% for <5, starts at 5% for 5 selections, increases by 5% per selection
    Max 300% at 40+ selections.
    Min odds per selection: 1.35
    Bonus table:
    5->5%, 6->10%, 7->15%, 8->20%, 9->25%, 10->30%, 11->35%,
    12->40%, 13->45%, 14->50%, 15->55%, ..., 40+->300%
    """
    if not min_odds_met or num_selections < 5:
        return 0.0

    # Formula: (selections - 4) * 5, capped at 300%
    bonus_percent = (num_selections - 4) * 5.0
    return min(bonus_percent, 300.0)


def calculate_betking_returns(selections: List[Dict], stake: float = 100.0) -> Dict[str, Any]:
    """
    Calculate BetKing returns using their documented bonus structure.
    Min qualifying odds per selection: 1.35
    """
    if not selections:
        return {
            "odds": 0.0,
            "base_win": 0.0,
            "bonus_percent": 0.0,
            "bonus_amount": 0.0,
            "potential_win": 0.0,
            "source": "calculated",
            "error": "No selections provided",
        }

    try:
        # Extract BetKing odds and validate
        odds_list = []
        for selection in selections:
            odds_str = selection.get("betking", "â")
            if odds_str == "â":
                return {
                    "odds": 0.0,
                    "base_win": 0.0,
                    "bonus_percent": 0.0,
                    "bonus_amount": 0.0,
                    "potential_win": 0.0,
                    "source": "calculated",
                    "error": f"Missing BetKing odds for {selection.get('event', 'unknown')}",
                }

            try:
                odds = float(odds_str)
                if odds < 1.35:
                    return {
                        "odds": 0.0,
                        "base_win": 0.0,
                        "bonus_percent": 0.0,
                        "bonus_amount": 0.0,
                        "potential_win": 0.0,
                        "source": "calculated",
                        "error": f"Odds {odds} below minimum 1.35 for {selection.get('event')}",
                    }
                odds_list.append(odds)
            except (ValueError, TypeError):
                return {
                    "odds": 0.0,
                    "base_win": 0.0,
                    "bonus_percent": 0.0,
                    "bonus_amount": 0.0,
                    "potential_win": 0.0,
                    "source": "calculated",
                    "error": f"Invalid odds format: {odds_str}",
                }

        # Calculate combined odds
        combined_odds = 1.0
        for odds in odds_list:
            combined_odds *= odds

        # Calculate base win
        base_win = stake * combined_odds

        # Calculate bonus
        bonus_percent = calculate_betking_bonus(len(selections), min_odds_met=True)
        bonus_amount = base_win * bonus_percent / 100.0

        return {
            "odds": round(combined_odds, 4),
            "base_win": round(base_win, 2),
            "bonus_percent": bonus_percent,
            "bonus_amount": round(bonus_amount, 2),
            "potential_win": round(base_win + bonus_amount, 2),
            "source": "calculated",
        }

    except Exception as e:
        return {
            "odds": 0.0,
            "base_win": 0.0,
            "bonus_percent": 0.0,
            "bonus_amount": 0.0,
            "potential_win": 0.0,
            "source": "calculated",
            "error": str(e),
        }


# ============================================================================
# MSPORT CALCULATIONS (NEW)
# ============================================================================

def calculate_msport_bonus(num_selections: int, min_odds_met: bool = True) -> float:
    """
    MSport bonus uses interpolation table.
    Min odds per selection: 1.20
    Bonus table:
    4->5%, 5->7%, 6->10%, 7->12%, 8->15%, 9->20%, 10->33%,
    11->35%, 12->40%, 13->45%, 14->50%, 15->55%, 16->60%,
    17->65%, 18->70%, 19->75%, 20->80%, 21->90%, 22->100%,
    23->110%, 24->120%, 25->130%, 26->140%, 27->150%, 28->160%,
    29->170%, 30+->180%
    """
    if not min_odds_met or num_selections < 4:
        return 0.0

    bonus_table = {
        4: 5.0,
        5: 7.0,
        6: 10.0,
        7: 12.0,
        8: 15.0,
        9: 20.0,
        10: 33.0,
        11: 35.0,
        12: 40.0,
        13: 45.0,
        14: 50.0,
        15: 55.0,
        16: 60.0,
        17: 65.0,
        18: 70.0,
        19: 75.0,
        20: 80.0,
        21: 90.0,
        22: 100.0,
        23: 110.0,
        24: 120.0,
        25: 130.0,
        26: 140.0,
        27: 150.0,
        28: 160.0,
        29: 170.0,
    }

    return bonus_table.get(num_selections, 180.0)


def calculate_msport_returns(selections: List[Dict], stake: float = 100.0) -> Dict[str, Any]:
    """
    Calculate MSport returns using their documented bonus table.
    Min qualifying odds per selection: 1.20
    """
    if not selections:
        return {
            "odds": 0.0,
            "base_win": 0.0,
            "bonus_percent": 0.0,
            "bonus_amount": 0.0,
            "potential_win": 0.0,
            "source": "calculated",
            "error": "No selections provided",
        }

    try:
        # Extract MSport odds and validate
        odds_list = []
        for selection in selections:
            odds_str = selection.get("msport", "â")
            if odds_str == "â":
                return {
                    "odds": 0.0,
                    "base_win": 0.0,
                    "bonus_percent": 0.0,
                    "bonus_amount": 0.0,
                    "potential_win": 0.0,
                    "source": "calculated",
                    "error": f"Missing MSport odds for {selection.get('event', 'unknown')}",
                }

            try:
                odds = float(odds_str)
                if odds < 1.20:
                    return {
                        "odds": 0.0,
                        "base_win": 0.0,
                        "bonus_percent": 0.0,
                        "bonus_amount": 0.0,
                        "potential_win": 0.0,
                        "source": "calculated",
                        "error": f"Odds {odds} below minimum 1.20 for {selection.get('event')}",
                    }
                odds_list.append(odds)
            except (ValueError, TypeError):
                return {
                    "odds": 0.0,
                    "base_win": 0.0,
                    "bonus_percent": 0.0,
                    "bonus_amount": 0.0,
                    "potential_win": 0.0,
                    "source": "calculated",
                    "error": f"Invalid odds format: {odds_str}",
                }

        # Calculate combined odds
        combined_odds = 1.0
        for odds in odds_list:
            combined_odds *= odds

        # Calculate base win
        base_win = stake * combined_odds

        # Calculate bonus
        bonus_percent = calculate_msport_bonus(len(selections), min_odds_met=True)
        bonus_amount = base_win * bonus_percent / 100.0

        return {
            "odds": round(combined_odds, 4),
            "base_win": round(base_win, 2),
            "bonus_percent": bonus_percent,
            "bonus_amount": round(bonus_amount, 2),
            "potential_win": round(base_win + bonus_amount, 2),
            "source": "calculated",
        }

    except Exception as e:
        return {
            "odds": 0.0,
            "base_win": 0.0,
            "bonus_percent": 0.0,
            "bonus_amount": 0.0,
            "potential_win": 0.0,
            "source": "calculated",
            "error": str(e),
        }


# ============================================================================
# BETANO CALCULATIONS (NEW)
# ============================================================================

def calculate_betano_bonus(num_selections: int, min_odds_met: bool = True) -> float:
    """
    Betano bonus starts at 3% for 2 selections, max 70%.
    Min odds per selection: 1.20
    Bonus table:
    2->3%, 3->5%, 4->7%, 5->10%, 6->12%, 7->15%, 8->18%,
    9->22%, 10->25%, 11->30%, 12->35%, 13->40%, 14->45%,
    15->50%, 16->55%, 17->60%, 18->65%, 19->68%, 20+->70%
    """
    if not min_odds_met or num_selections < 2:
        return 0.0

    bonus_table = {
        2: 3.0,
        3: 5.0,
        4: 7.0,
        5: 10.0,
        6: 12.0,
        7: 15.0,
        8: 18.0,
        9: 22.0,
        10: 25.0,
        11: 30.0,
        12: 35.0,
        13: 40.0,
        14: 45.0,
        15: 50.0,
        16: 55.0,
        17: 60.0,
        18: 65.0,
        19: 68.0,
    }

    return bonus_table.get(num_selections, 70.0)


def calculate_betano_returns(selections: List[Dict], stake: float = 100.0) -> Dict[str, Any]:
    """
    Calculate Betano returns using their documented bonus table.
    Min qualifying odds per selection: 1.20
    """
    if not selections:
        return {
            "odds": 0.0,
            "base_win": 0.0,
            "bonus_percent": 0.0,
            "bonus_amount": 0.0,
            "potential_win": 0.0,
            "source": "calculated",
            "error": "No selections provided",
        }

    try:
        # Extract Betano odds and validate
        odds_list = []
        for selection in selections:
            odds_str = selection.get("betano", "â")
            if odds_str == "â":
                return {
                    "odds": 0.0,
                    "base_win": 0.0,
                    "bonus_percent": 0.0,
                    "bonus_amount": 0.0,
                    "potential_win": 0.0,
                    "source": "calculated",
                    "error": f"Missing Betano odds for {selection.get('event', 'unknown')}",
                }

            try:
                odds = float(odds_str)
                if odds < 1.20:
                    return {
                        "odds": 0.0,
                        "base_win": 0.0,
                        "bonus_percent": 0.0,
                        "bonus_amount": 0.0,
                        "potential_win": 0.0,
                        "source": "calculated",
                        "error": f"Odds {odds} below minimum 1.20 for {selection.get('event')}",
                    }
                odds_list.append(odds)
            except (ValueError, TypeError):
                return {
                    "odds": 0.0,
                    "base_win": 0.0,
                    "bonus_percent": 0.0,
                    "bonus_amount": 0.0,
                    "potential_win": 0.0,
                    "source": "calculated",
                    "error": f"Invalid odds format: {odds_str}",
                }

        # Calculate combined odds
        combined_odds = 1.0
        for odds in odds_list:
            combined_odds *= odds

        # Calculate base win
        base_win = stake * combined_odds

        # Calculate bonus
        bonus_percent = calculate_betano_bonus(len(selections), min_odds_met=True)
        bonus_amount = base_win * bonus_percent / 100.0

        return {
            "odds": round(combined_odds, 4),
            "base_win": round(base_win, 2),
            "bonus_percent": bonus_percent,
            "bonus_amount": round(bonus_amount, 2),
            "potential_win": round(base_win + bonus_amount, 2),
            "source": "calculated",
        }

    except Exception as e:
        return {
            "odds": 0.0,
            "base_win": 0.0,
            "bonus_percent": 0.0,
            "bonus_amount": 0.0,
            "potential_win": 0.0,
            "source": "calculated",
            "error": str(e),
        }


# ============================================================================
# ACCUMULATOR ANALYSIS (EXISTING - EXPANDED FOR 5 BOOKMAKERS)
# ============================================================================

def check_all_accumulators(
    merged_rows: List[Dict],
    raw_bet9ja: List[Dict],
    min_diff: float = 0.05,
    min_size: int = 3,
    max_size: int = 15,
) -> List[Dict]:
    """
    Find best accumulators by analyzing all merged odds.
    Computes potential returns for all 5 bookmakers.
    """
    if not merged_rows:
        return []

    try:
        # Group rows by league and market for analysis
        accumulators = []

        # Simple strategy: find high-diff bets that form accumulators
        high_diff_rows = [
            row for row in merged_rows
            if row.get("diff", 0) >= min_diff and row.get("sign") in ["1", "X", "2"]
        ]

        if len(high_diff_rows) < min_size:
            return []

        # Create potential accumulators
        for i in range(min_size, min(max_size + 1, len(high_diff_rows) + 1)):
            selections = high_diff_rows[:i]

            accumulator = {
                "size": len(selections),
                "avg_diff": sum(r.get("diff", 0) for r in selections) / len(selections),
                "selections": selections,
                "returns": {
                    "bet9ja": calculate_bet9ja_returns(selections, 100.0),
                    "sportybet": _sportybet_formula_fallback(selections, 100.0),
                    "betking": calculate_betking_returns(selections, 100.0),
                    "msport": calculate_msport_returns(selections, 100.0),
                    "betano": calculate_betano_returns(selections, 100.0),
                },
            }

            accumulators.append(accumulator)

        return accumulators[:5]  # Return top 5 accumulators

    except Exception as e:
        return []


def extract_odds_from_betslip(betslip_text: str) -> Dict[str, Any]:
    """
    Extract odds and potential returns from betslip text.
    """
    try:
        # This would parse actual betslip HTML/text
        # Placeholder for now
        return {
            "extracted": False,
            "message": "Betslip parsing not implemented",
        }
    except Exception as e:
        return {
            "extracted": False,
            "error": str(e),
        }


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def format_currency(amount: float, currency: str = "NGN") -> str:
    """Format amount as currency string."""
    return f"{currency} {amount:,.2f}"


def format_odds(odds: float) -> str:
    """Format odds to 2 decimal places."""
    return f"{odds:.2f}"


def validate_selection(selection: Dict) -> tuple[bool, str]:
    """
    Validate a single selection dictionary.
    Returns (is_valid, error_message)
    """
    if not isinstance(selection, dict):
        return False, "Selection must be a dictionary"

    required_fields = ["event", "sign", "market"]
    for field in required_fields:
        if field not in selection:
            return False, f"Missing required field: {field}"

    if selection["sign"] not in ["1", "X", "2", "O", "U"]:
        return False, f"Invalid sign: {selection['sign']}"

    return True, ""


def validate_selections(selections: List[Dict]) -> tuple[bool, str]:
    """
    Validate a list of selections.
    Returns (is_valid, error_message)
    """
    if not selections:
        return False, "Selections list cannot be empty"

    if not isinstance(selections, list):
        return False, "Selections must be a list"

    for i, selection in enumerate(selections):
        is_valid, error = validate_selection(selection)
        if not is_valid:
            return False, f"Selection {i}: {error}"

    return True, ""
