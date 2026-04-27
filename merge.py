"""
merge.py — Team matching and odds merging logic.

Extracted from main.py to keep the core merge/match pipeline
separate from the FastAPI app, scrapers, and auth.

Public API:
    TEAM_ALIASES     — dict mapping variant names to canonical names
    SIGN_SWAP_MAP    — dict for swapping odds signs when team order reverses
    _normalize_team  — normalise a team name for matching
    _team_sim        — similarity score between two team names
    fuzzy_match_event — decide whether two events are the same match
    merge_odds       — merge raw scraper data into unified rows
"""

from difflib import SequenceMatcher
import logging
import logging, re

logger = logging.getLogger(__name__)

SIGN_SWAP_MAP = {"1": "2", "2": "1", "X": "X", "1X": "X2", "X2": "1X", "12": "12", "Over": "Over", "Under": "Under"}

# Comprehensive team name aliases for major European leagues

TEAM_ALIASES = {
    # English Premier League & Championship
    "manchester united": "manchester utd",
    "man utd": "manchester utd",
    "man united": "manchester utd",
    "tottenham hotspur": "tottenham",
    "spurs": "tottenham",
    "wolverhampton wanderers": "wolverhampton",
    "wolves": "wolverhampton",
    "manchester city": "manchester city",
    "man city": "manchester city",
    "brighton and hove albion": "brighton",
    "brighton & hove albion": "brighton",
    "brighton hove": "brighton",
    "brighton hove albion": "brighton",
    "west ham united": "west ham",
    "west ham utd": "west ham",
    "leicester city": "leicester",
    "newcastle united": "newcastle",
    "newcastle utd": "newcastle",
    "crystal palace": "crystal palace",
    "fulham fc": "fulham",
    "aston villa": "aston villa",
    "brentford fc": "brentford",
    "luton town": "luton",
    "ipswich town": "ipswich",
    "nottingham forest": "nottingham",
    "nott'm forest": "nottingham",
    "nott forest": "nottingham",
    "nottm forest": "nottingham",
    "nott. forest": "nottingham",
    "leeds united": "leeds utd",
    "leeds": "leeds utd",
    "sunderland afc": "sunderland",
    "afc sunderland": "sunderland",
    "burnley fc": "burnley",
    "everton fc": "everton",
    "chelsea fc": "chelsea",
    "liverpool fc": "liverpool",
    "arsenal fc": "arsenal",
    "bournemouth afc": "bournemouth",
    "southampton fc": "southampton",

    # Spanish La Liga
    "atletico de madrid": "atletico madrid",
    "atletico madrid": "atletico madrid",
    "atl. madrid": "atletico madrid",
    "fc barcelona": "barcelona",
    "barcelona": "barcelona",
    "real madrid": "real madrid",
    "real sociedad": "real sociedad",
    "r. sociedad": "real sociedad",
    "villarreal cf": "villarreal",
    "villarreal": "villarreal",
    "sevilla fc": "sevilla",
    "sevilla": "sevilla",
    "real betis": "betis",
    "betis": "betis",
    "rc celta": "celta",
    "celta vigo": "celta",
    "rayo vallecano": "rayo vallecano",
    "rayo": "rayo vallecano",
    "athletic bilbao": "ath bilbao",
    "athletic club": "ath bilbao",
    "ath. bilbao": "ath bilbao",
    "ud almeria": "almeria",
    "almeria": "almeria",
    "cf osasuna": "osasuna",
    "osasuna": "osasuna",
    "getafe cf": "getafe",
    "getafe": "getafe",
    "sd huesca": "huesca",
    "huesca": "huesca",
    "real oviedo": "oviedo",
    "oviedo": "oviedo",
    "eibar sd": "eibar",
    "eibar": "eibar",
    "elche cf": "elche",
    "elche": "elche",
    "ponferradina": "ponferradina",
    "cd leganes": "leganes",
    "leganes": "leganes",
    "cd alcorcon": "alcorcon",
    "alcorcon": "alcorcon",

    # Italian Serie A
    "fc internazionale": "inter",
    "inter milan": "inter",
    "internazionale": "inter",
    "inter": "inter",
    "ac milan": "milan",
    "ac milano": "milan",
    "milan": "milan",
    "as roma": "roma",
    "roma": "roma",
    "ss lazio": "lazio",
    "lazio": "lazio",
    "ssc napoli": "napoli",
    "napoli": "napoli",
    "uc sampdoria": "sampdoria",
    "sampdoria": "sampdoria",
    "genoa cfc": "genoa",
    "genoa": "genoa",
    "hellas verona": "verona",
    "verona": "verona",
    "us sassuolo": "sassuolo",
    "sassuolo": "sassuolo",
    "acf fiorentina": "fiorentina",
    "fiorentina": "fiorentina",
    "cagliari calcio": "cagliari",
    "cagliari": "cagliari",
    "parma calcio": "parma",
    "parma": "parma",
    "uc reggiana": "reggiana",
    "reggiana": "reggiana",
    "spezia calcio": "spezia",
    "spezia": "spezia",
    "pisa sporting club": "pisa",
    "pisa": "pisa",
    "frosinone calcio": "frosinone",
    "frosinone": "frosinone",
    "benevento calcio": "benevento",
    "benevento": "benevento",
    "udinese calcio": "udinese",
    "udinese": "udinese",
    "us sassuolo": "sassuolo",
    "sassuolo calcio": "sassuolo",
    "sassuolo": "sassuolo",
    "genoa cfc": "genoa",
    "genoa": "genoa",
    "como 1907": "como",
    "como": "como",
    "venezia fc": "venezia",
    "venezia": "venezia",
    "monza": "monza",
    "ac monza": "monza",
    "us lecce": "lecce",
    "lecce": "lecce",
    "empoli fc": "empoli",
    "empoli": "empoli",
    "torino fc": "torino",
    "torino": "torino",

    # German Bundesliga
    "fc bayern": "bayern",
    "bayern munich": "bayern",
    "bayern munchen": "bayern",
    "bayern": "bayern",
    "borussia dortmund": "dortmund",
    "b. dortmund": "dortmund",
    "bvb": "dortmund",
    "dortmund": "dortmund",
    "borussia monchengladbach": "gladbach",
    "borussia m'gladbach": "gladbach",
    "b. monchengladbach": "gladbach",
    "b. m'gladbach": "gladbach",
    "m'gladbach": "gladbach",
    "monchengladbach": "gladbach",
    "gladbach": "gladbach",
    "rb leipzig": "leipzig",
    "rasenballsport leipzig": "leipzig",
    "leipzig": "leipzig",
    "bayer leverkusen": "leverkusen",
    "bayer 04 leverkusen": "leverkusen",
    "leverkusen": "leverkusen",
    "vfb stuttgart": "stuttgart",
    "stuttgart": "stuttgart",
    "eintracht frankfurt": "e. frankfurt",
    "ein. frankfurt": "e. frankfurt",
    "e. frankfurt": "e. frankfurt",
    "1. fc heidenheim": "heidenheim",
    "fc heidenheim": "heidenheim",
    "heidenheim": "heidenheim",
    "tsg hoffenheim": "hoffenheim",
    "1899 hoffenheim": "hoffenheim",
    "hoffenheim": "hoffenheim",
    "vfl wolfsburg": "wolfsburg",
    "wolfsburg": "wolfsburg",
    "fc augsburg": "augsburg",
    "augsburg": "augsburg",
    "1. fc union berlin": "union berlin",
    "fc union berlin": "union berlin",
    "union berlin": "union berlin",
    "werder bremen": "werder bremen",
    "sv werder bremen": "werder bremen",
    "1. fsv mainz 05": "mainz",
    "mainz 05": "mainz",
    "mainz": "mainz",
    "fc st. pauli": "st. pauli",
    "st. pauli": "st. pauli",
    "holstein kiel": "holstein kiel",
    "sc freiburg": "freiburg",
    "freiburg": "freiburg",
    "vfl bochum": "bochum",
    "bochum": "bochum",

    # French Ligue 1
    "paris saint-germain": "psg",
    "paris saint germain": "psg",
    "paris sg": "psg",
    "psg": "psg",
    "olympique marseille": "marseille",
    "ol. marseille": "marseille",
    "marseille": "marseille",
    "olympique lyon": "lyon",
    "olympique lyonnais": "lyon",
    "ol. lyon": "lyon",
    "lyon": "lyon",
    "as monaco": "monaco",
    "fc monaco": "monaco",
    "monaco": "monaco",
    "rc lens": "lens",
    "lens": "lens",
    "losc lille": "lille",
    "lille osc": "lille",
    "lille": "lille",
    "stade rennais": "rennes",
    "rennes": "rennes",
    "ogc nice": "nice",
    "nice": "nice",
    "stade brestois": "brest",
    "stade brest": "brest",
    "brest": "brest",
    "montpellier hsc": "montpellier",
    "montpellier": "montpellier",
    "toulouse fc": "toulouse",
    "toulouse": "toulouse",
    "fc lorient": "lorient",
    "lorient": "lorient",
    "fc metz": "metz",
    "metz": "metz",
    "aj auxerre": "auxerre",
    "auxerre": "auxerre",
    "angers sco": "angers",
    "angers": "angers",
    "le havre ac": "le havre",
    "le havre": "le havre",
    "stade de reims": "reims",
    "reims": "reims",
    "as saint-etienne": "saint-etienne",
    "as st-etienne": "saint-etienne",
    "saint-etienne": "saint-etienne",
    "rc strasbourg": "strasbourg",
    "strasbourg": "strasbourg",
    "fc nantes": "nantes",
    "nantes": "nantes",
    "clermont foot": "clermont",
    "clermont": "clermont",
    # -- Bundesliga full names (Sportradar/MSport format) --
    "fc bayern münchen": "bayern",
    "fc bayern munchen": "bayern",
    "bayern münchen": "bayern",
    "bayern munchen": "bayern",
    "vfl wolfsburg": "wolfsburg",
    "1. fc union berlin": "union berlin",
    "fc union berlin": "union berlin",
    "1 fc union berlin": "union berlin",
    "1. fc heidenheim": "heidenheim",
    "1. fc heidenheim 1846": "heidenheim",
    "fc heidenheim": "heidenheim",
    "1 fc heidenheim": "heidenheim",
    "bayer 04 leverkusen": "leverkusen",
    "bayer leverkusen": "leverkusen",
    "sv werder bremen": "werder bremen",
    "werder bremen": "werder bremen",
    "sc freiburg": "freiburg",
    "tsg hoffenheim": "hoffenheim",
    "tsg 1899 hoffenheim": "hoffenheim",
    "vfb stuttgart": "stuttgart",
    "1. fc köln": "koln",
    "1. fc koln": "koln",
    "1 fc koln": "koln",
    "fc köln": "koln",
    "fc koln": "koln",
    "fc augsburg": "augsburg",
    "sv darmstadt 98": "darmstadt",
    "sv darmstadt": "darmstadt",
    "1. fsv mainz 05": "mainz",
    "1. fsv mainz": "mainz",
    "fsv mainz": "mainz",
    "fsv mainz 05": "mainz",
    "vfl bochum": "bochum",
    "vfl bochum 1848": "bochum",
    "eintracht frankfurt": "frankfurt",
    "e. frankfurt": "frankfurt",
    # -- English teams full names --
    "brighton & hove albion": "brighton",
    "brighton and hove albion": "brighton",
    "brighton hove albion": "brighton",
    "afc bournemouth": "bournemouth",
    "bournemouth afc": "bournemouth",
    "wolverhampton wanderers": "wolverhampton",
    "wolverhampton": "wolverhampton",
    # -- La Liga full names --
    "rcd mallorca": "mallorca",
    "real mallorca": "mallorca",
    "elche cf": "elche",
    "rcd espanyol": "espanyol",
    "cd leganes": "leganes",
    "cd leganés": "leganes",
    # -- Serie A full names --
    "hellas verona fc": "verona",
    "hellas verona": "verona",
    "uc sampdoria": "sampdoria",
    "us sassuolo": "sassuolo",
    "sassuolo calcio": "sassuolo",
    "empoli fc": "empoli",
    "us salernitana": "salernitana",
    "cagliari calcio": "cagliari",
    # -- Ligue 1 full names --
    "stade de reims": "reims",
    "stade reims": "reims",
    "stade rennais": "rennes",
    "stade rennais fc": "rennes",
    "fc nantes": "nantes",
    "rc strasbourg": "strasbourg",
    "rc strasbourg alsace": "strasbourg",
    "rc lens": "lens",
    "fc lorient": "lorient",
    "fc metz": "metz",
    "toulouse fc": "toulouse",
    "le havre ac": "le havre",
    # Additional aliases for cross-bookmaker matching (YaJuego, MSport variations)
    "nottingham forest": "nottingham",
    "nott'm forest": "nottingham",
    "nottm forest": "nottingham",
    "nott forest": "nottingham",
    "nott. forest": "nottingham",
    "wolves": "wolverhampton",
    "wolverhampton wanderers": "wolverhampton",
    "wolverhampton": "wolverhampton",
    "spurs": "tottenham",
    "tottenham hotspur": "tottenham",
    "tottenham": "tottenham",
    "west ham": "west ham",
    "west ham united": "west ham",
    "west ham utd": "west ham",
    "newcastle": "newcastle",
    "newcastle united": "newcastle",
    "newcastle utd": "newcastle",
    "aston villa": "aston villa",
    "crystal palace": "crystal palace",
    "man utd": "manchester utd",
    "man united": "manchester utd",
    "manchester united": "manchester utd",
    "man city": "manchester city",
    "manchester city": "manchester city",
    "inter": "inter",
    "inter milan": "inter",
    "internazionale": "inter",
    "fc inter": "inter",
    "fc internazionale": "inter",
    "ac milan": "milan",
    "milan": "milan",
    "atletico madrid": "atletico madrid",
    "atletico de madrid": "atletico madrid",
    "atl. madrid": "atletico madrid",
    "atl madrid": "atletico madrid",
    "club atletico de madrid": "atletico madrid",
    "rb leipzig": "leipzig",
    "rasenballsport leipzig": "leipzig",
    "rbl": "leipzig",
    "paris saint-germain": "psg",
    "paris saint germain": "psg",
    "paris sg": "psg",
    "psg": "psg",
    "borussia dortmund": "dortmund",
    "b. dortmund": "dortmund",
    "bvb dortmund": "dortmund",
    "bayern munich": "bayern",
    "bayern munchen": "bayern",
    "fc bayern munich": "bayern",
    "fc bayern munchen": "bayern",
    "fc bayern münchen": "bayern",

}

def _normalize_team(name: str) -> str:
    """Normalize a team name for matching — aggressive normalization."""
    import re as _re
    n = name.lower().strip()
    # Remove common prefixes and suffixes (fc, sc, afc, cf, etc.)
    for suffix in [" fc", " cf", " sc", " ssc", " bc", " afc", " calcio", " 1907", " 1908", " 1899"]:
        if n.endswith(suffix):
            n = n[:-len(suffix)].strip()
    for prefix in ["fc ", "sc ", "afc ", "ac ", "as ", "ss ", "us ", "uc ", "rc ", "cd ", "sd ", "ud ", "rcd "]:
        if n.startswith(prefix):
            n = n[len(prefix):].strip()
    # Remove accents/diacritics approximation
    accent_map = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n", "ü": "u", "ö": "o", "ä": "a", "ç": "c", "è": "e", "ê": "e", "ë": "e", "à": "a", "â": "a", "î": "i", "ô": "o", "û": "u", "ï": "i"}
    n = "".join(accent_map.get(c, c) for c in n)
    # Remove dots, extra whitespace
    n = _re.sub(r"\.+", " ", n).strip()
    n = _re.sub(r"\s+", " ", n).strip()
    # Check aliases
    return TEAM_ALIASES.get(n, n)


def _team_sim(a: str, b: str) -> float:
    """Similarity between two normalized team names."""
    if a == b:
        return 1.0
    # Containment check (either direction)
    if a in b or b in a:
        return 0.88
    # Word overlap - any shared significant word is a strong signal
    wa = set(w for w in a.split() if len(w) > 2)
    wb = set(w for w in b.split() if len(w) > 2)
    if wa and wb:
        overlap = len(wa & wb)
        if overlap > 0:
            score = overlap / max(len(wa), len(wb))
            return max(score, 0.55)
    # Check if first N chars match (e.g. "nottingham" vs "nottingham forest")
    min_len = min(len(a), len(b))
    if min_len >= 5 and a[:min_len] == b[:min_len]:
        return 0.85
    # Character-level similarity as fallback
    return SequenceMatcher(None, a, b).ratio()

def fuzzy_match_event(event1: str, event2: str, threshold: float = 0.70) -> tuple:
    """
    Fuzzy matching for event names across bookmakers.
    Returns (is_match: bool, is_reversed: bool).
    is_reversed=True means event2 has teams in opposite order from event1.
    Team names are normalized before comparison.
    """
    e1 = event1.lower().strip()
    e2 = event2.lower().strip()
    if e1 == e2:
        return (True, False)

    # Split into home/away teams using " - " separator
    parts1 = [p.strip() for p in e1.split(" - ", 1)]
    parts2 = [p.strip() for p in e2.split(" - ", 1)]

    if len(parts1) != 2 or len(parts2) != 2:
        # Fallback to simple word overlap (can't detect reversal)
        words1 = set(e1.split())
        words2 = set(e2.split())
        if not words1 or not words2:
            return (False, False)
        overlap = len(words1 & words2) / max(len(words1), len(words2))
        return (overlap >= threshold, False)

    home1, away1 = parts1
    home2, away2 = parts2

    # Normalize teams
    home1_norm = _normalize_team(home1)
    away1_norm = _normalize_team(away1)
    home2_norm = _normalize_team(home2)
    away2_norm = _normalize_team(away2)

    # Try direct match: home1~home2, away1~away2
    if _team_sim(home1_norm, home2_norm) >= threshold and _team_sim(away1_norm, away2_norm) >= threshold:
        return (True, False)

    # Try reversed match: home1~away2, away1~home2
    if _team_sim(home1_norm, away2_norm) >= threshold and _team_sim(away1_norm, home2_norm) >= threshold:
        return (True, True)

    return (False, False)


def merge_odds(raw_data: dict) -> list:
    """
    Merge odds from all 5 bookmakers using ANY available data.
    Uses a unified event index built from all bookmakers, with league-based grouping
    for faster and more accurate matching.
    """
    BOOKMAKERS = ["bet9ja", "sportybet", "msport", "yajuego", "betfair"]  # betking, betano & betgr8 PAUSED

    # Build league index: league -> {event_key -> event_data}
    league_index = {}

    for bk_name in BOOKMAKERS:
        for ev in raw_data.get(bk_name, []):
            league = ev.get("league", "")
            event_name = ev.get("event", "")
            if not event_name:
                continue

            # Initialize league if not present
            if league not in league_index:
                league_index[league] = {}

            # Try to find existing key via fuzzy match within same league
            matched_key = None
            is_reversed = False
            matched_league = league
            for existing_key in league_index[league]:
                existing_entry = league_index[league][existing_key]
                # Skip if this bookmaker already has odds in this entry
                if any(bk_name in bk_odds for mkt in existing_entry.get("markets", {}).values() for bk_odds in mkt.values()):
                    continue
                existing_event = existing_entry["event"]
                match_result = fuzzy_match_event(existing_event, event_name)
                if match_result[0]:  # is_match
                    matched_key = existing_key
                    is_reversed = match_result[1]
                    break

            # Cross-league fallback: if no match in same league, try all leagues
            # This catches cases where bookmakers categorize the same event differently
            if matched_key is None:
                for other_league in league_index:
                    if other_league == league:
                        continue
                    for existing_key in league_index[other_league]:
                        existing_entry = league_index[other_league][existing_key]
                        # Skip if this bookmaker already has odds in this entry
                        if any(bk_name in bk_odds for mkt in existing_entry.get("markets", {}).values() for bk_odds in mkt.values()):
                            continue
                        existing_event = existing_entry["event"]
                        match_result = fuzzy_match_event(existing_event, event_name, threshold=0.75)
                        if match_result[0]:
                            matched_key = existing_key
                            matched_league = other_league
                            is_reversed = match_result[1]
                            break
                    if matched_key is not None:
                        break

            if matched_key is None:
                matched_key = f"{league}|{event_name}"
                league_index[league][matched_key] = {
                    "league": league,
                    "event": event_name,
                    "markets": {},
                    "start_time": ev.get("start_time", ""),
                }
                matched_league = league  # New entry in current league
            else:
                logger.info(f"  [Merge] Matched '{event_name}' ({bk_name}) -> '{league_index[matched_league][matched_key]['event']}' league={matched_league} (reversed={is_reversed})")
            # Update start_time if this bookmaker has it and existing entry doesn't
            if ev.get("start_time") and not league_index[matched_league][matched_key].get("start_time"):
                league_index[matched_league][matched_key]["start_time"] = ev["start_time"]

            # Add this bookmaker's odds into the unified entry
            # SportyBet uses "odds" key, others use "markets"
            markets_data = ev.get("markets", ev.get("odds", {}))
            for market, signs in markets_data.items():
                if market not in league_index[matched_league][matched_key]["markets"]:
                    league_index[matched_league][matched_key]["markets"][market] = {}
                for sign, odds_str in signs.items():
                    # Swap sign if teams are in reversed order
                    actual_sign = SIGN_SWAP_MAP.get(sign, sign) if is_reversed else sign
                    if actual_sign not in league_index[matched_league][matched_key]["markets"][market]:
                        league_index[matched_league][matched_key]["markets"][market][actual_sign] = {}
                    try:
                        odds_val = float(str(odds_str).replace(",", "."))
                        league_index[matched_league][matched_key]["markets"][market][actual_sign][bk_name] = odds_val
                    except (ValueError, AttributeError, TypeError):
                        pass

    # Flatten the league index into rows
    merged_rows = []
    for league, entries in league_index.items():
        for key, entry in entries.items():
            # FILTER: Only show events that exist on Bet9ja (base bookmaker)
            has_bet9ja = any(
                "bet9ja" in bk_odds
                for signs in entry["markets"].values()
                for bk_odds in signs.values()
            )
            if not has_bet9ja:
                continue

            league = entry["league"]
            event_name = entry["event"]
            for market, signs in entry["markets"].items():
                for sign, bk_odds in signs.items():
                    row = {
                        "league": league,
                        "event": event_name,
                        "market": market,
                        "sign": sign,
                        "start_time": entry.get("start_time", ""),
                    }
                    all_odds_values = []
                    for bk_name in BOOKMAKERS:
                        if bk_name in bk_odds:
                            row[bk_name] = f"{bk_odds[bk_name]:.2f}"
                            all_odds_values.append(bk_odds[bk_name])
                        else:
                            row[bk_name] = "-"

                    # Calculate difference
                    if len(all_odds_values) >= 2:
                        row["diff"] = round(max(all_odds_values) - min(all_odds_values), 2)
                    else:
                        row["diff"] = 0.0

                    merged_rows.append(row)

    return merged_rows


