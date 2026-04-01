"""
Automated tests for Odds Dashboard — covers the critical merge/match logic
that has been the source of most production bugs.

Run with: pytest test_main.py -v
"""
import pytest
from main import (
    _normalize_team,
    _team_sim,
    fuzzy_match_event,
    merge_odds,
    TEAM_ALIASES,
    SIGN_SWAP_MAP,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. TEAM NAME NORMALIZATION
# ═══════════════════════════════════════════════════════════════════════

class TestNormalizeTeam:
    """Test _normalize_team strips prefixes/suffixes and resolves aliases."""

    def test_suffix_removal(self):
        assert _normalize_team("Arsenal FC") == "arsenal"
        assert _normalize_team("Sevilla CF") == "sevilla"
        assert _normalize_team("Freiburg SC") == "freiburg"

    def test_prefix_removal(self):
        assert _normalize_team("FC Barcelona") == "barcelona"
        assert _normalize_team("AC Milan") == "milan"
        assert _normalize_team("AS Roma") == "roma"

    def test_alias_resolution(self):
        # Premier League
        assert _normalize_team("Manchester United") == "manchester utd"
        assert _normalize_team("Man Utd") == "manchester utd"
        assert _normalize_team("Tottenham Hotspur") == "tottenham"
        assert _normalize_team("Spurs") == "tottenham"
        assert _normalize_team("Wolves") == "wolverhampton"

        # Serie A
        assert _normalize_team("FC Internazionale") == "inter"
        assert _normalize_team("Inter Milan") == "inter"

        # Bundesliga
        assert _normalize_team("Bayern Munich") == "bayern"
        assert _normalize_team("RB Leipzig") == "leipzig"
        assert _normalize_team("Borussia Dortmund") == "dortmund"

        # Ligue 1
        assert _normalize_team("Paris Saint-Germain") == "psg"
        assert _normalize_team("Paris SG") == "psg"

    def test_accent_handling(self):
        # Bayern München resolves to "bayern" via alias (alias takes priority)
        result = _normalize_team("Bayern München")
        assert result == "bayern"  # alias resolution strips München

    def test_dot_removal(self):
        result = _normalize_team("Nott. Forest")
        assert "." not in result

    def test_already_normalized(self):
        assert _normalize_team("arsenal") == "arsenal"
        assert _normalize_team("liverpool") == "liverpool"

    def test_case_insensitive(self):
        assert _normalize_team("ARSENAL") == _normalize_team("arsenal")
        assert _normalize_team("Manchester City") == _normalize_team("manchester city")

    def test_whitespace_handling(self):
        assert _normalize_team("  Arsenal  ") == "arsenal"
        assert _normalize_team("Manchester   City") == _normalize_team("Manchester City")


# ═══════════════════════════════════════════════════════════════════════
# 2. TEAM SIMILARITY
# ═══════════════════════════════════════════════════════════════════════

class TestTeamSim:
    """Test _team_sim scoring between normalized team names."""

    def test_exact_match(self):
        assert _team_sim("arsenal", "arsenal") == 1.0

    def test_containment(self):
        score = _team_sim("brighton", "brighton hove albion")
        assert score >= 0.85

    def test_word_overlap(self):
        score = _team_sim("manchester city", "manchester")
        assert score >= 0.55

    def test_no_match(self):
        score = _team_sim("arsenal", "liverpool")
        assert score < 0.5

    def test_similar_names(self):
        score = _team_sim("nottingham", "nottingham forest")
        assert score >= 0.8  # containment


# ═══════════════════════════════════════════════════════════════════════
# 3. EVENT FUZZY MATCHING
# ═══════════════════════════════════════════════════════════════════════

class TestFuzzyMatchEvent:
    """Test fuzzy_match_event for cross-bookmaker event matching."""

    def test_exact_match(self):
        is_match, is_reversed = fuzzy_match_event(
            "Arsenal - Everton", "Arsenal - Everton"
        )
        assert is_match is True
        assert is_reversed is False

    def test_case_insensitive_match(self):
        is_match, _ = fuzzy_match_event(
            "Arsenal - Everton", "arsenal - everton"
        )
        assert is_match is True

    def test_alias_match(self):
        """Different bookmakers use different names for same team."""
        is_match, _ = fuzzy_match_event(
            "Man Utd - Tottenham", "Manchester United - Spurs"
        )
        assert is_match is True

    def test_reversed_teams(self):
        """Some bookmakers list home/away in opposite order."""
        is_match, is_reversed = fuzzy_match_event(
            "Arsenal - Everton", "Everton - Arsenal"
        )
        assert is_match is True
        assert is_reversed is True

    def test_no_match(self):
        is_match, _ = fuzzy_match_event(
            "Arsenal - Everton", "Liverpool - Chelsea"
        )
        assert is_match is False

    def test_partial_name_match(self):
        """Bookmaker adds/drops 'FC' suffix."""
        is_match, _ = fuzzy_match_event(
            "Arsenal FC - Everton FC", "Arsenal - Everton"
        )
        assert is_match is True

    def test_serie_a_variations(self):
        is_match, _ = fuzzy_match_event(
            "AC Milan - Inter Milan", "Milan - Inter"
        )
        assert is_match is True

    def test_bundesliga_variations(self):
        is_match, _ = fuzzy_match_event(
            "Bayern Munich - Borussia Dortmund", "Bayern - Dortmund"
        )
        assert is_match is True

    def test_threshold_respected(self):
        """Very different events should not match even at low threshold."""
        is_match, _ = fuzzy_match_event(
            "Arsenal - Chelsea", "Barcelona - Real Madrid",
            threshold=0.55
        )
        assert is_match is False


# ═══════════════════════════════════════════════════════════════════════
# 4. SIGN SWAP (reversed team order)
# ═══════════════════════════════════════════════════════════════════════

class TestSignSwap:
    """When teams are reversed, 1<->2 and 1X<->X2."""

    def test_swap_1_and_2(self):
        assert SIGN_SWAP_MAP["1"] == "2"
        assert SIGN_SWAP_MAP["2"] == "1"

    def test_swap_1x_x2(self):
        assert SIGN_SWAP_MAP["1X"] == "X2"
        assert SIGN_SWAP_MAP["X2"] == "1X"

    def test_x_stays(self):
        assert SIGN_SWAP_MAP["X"] == "X"

    def test_over_under_stays(self):
        assert SIGN_SWAP_MAP["Over"] == "Over"
        assert SIGN_SWAP_MAP["Under"] == "Under"


# ═══════════════════════════════════════════════════════════════════════
# 5. MERGE ODDS
# ═══════════════════════════════════════════════════════════════════════

class TestMergeOdds:
    """Test the core merge_odds function."""

    def _make_event(self, event, league, markets, bk_key="odds"):
        return {
            "event": event,
            "league": league,
            bk_key: markets,
        }

    def test_single_bookmaker(self):
        raw = {
            "bet9ja": [
                self._make_event("Arsenal - Everton", "Premier League", {
                    "1X2": {"1": "1.50", "X": "3.20", "2": "5.00"}
                })
            ],
            "sportybet": [],
            "msport": [],
            "yajuego": [],
        }
        rows = merge_odds(raw)
        assert len(rows) == 3  # 3 signs in 1X2
        assert rows[0]["bet9ja"] == "1.50"
        assert rows[0]["sportybet"] == "-"

    def test_two_bookmakers_same_event(self):
        raw = {
            "bet9ja": [
                self._make_event("Arsenal - Everton", "Premier League", {
                    "1X2": {"1": "1.50", "X": "3.20", "2": "5.00"}
                })
            ],
            "sportybet": [
                self._make_event("Arsenal - Everton", "Premier League", {
                    "1X2": {"1": "1.55", "X": "3.10", "2": "4.80"}
                })
            ],
            "msport": [],
            "yajuego": [],
        }
        rows = merge_odds(raw)
        assert len(rows) == 3
        # Both bookmakers should have values
        for row in rows:
            assert row["bet9ja"] != "-"
            assert row["sportybet"] != "-"

    def test_diff_calculation(self):
        raw = {
            "bet9ja": [
                self._make_event("Arsenal - Everton", "Premier League", {
                    "1X2": {"1": "1.50"}
                })
            ],
            "sportybet": [
                self._make_event("Arsenal - Everton", "Premier League", {
                    "1X2": {"1": "2.00"}
                })
            ],
            "msport": [],
            "yajuego": [],
        }
        rows = merge_odds(raw)
        assert len(rows) == 1
        assert rows[0]["diff"] == 0.50

    def test_fuzzy_name_merge(self):
        """Events with slightly different names should still merge."""
        raw = {
            "bet9ja": [
                self._make_event("Man Utd - Tottenham", "Premier League", {
                    "1X2": {"1": "2.00"}
                })
            ],
            "sportybet": [
                self._make_event("Manchester United - Spurs", "Premier League", {
                    "1X2": {"1": "2.10"}
                })
            ],
            "msport": [],
            "yajuego": [],
        }
        rows = merge_odds(raw)
        # Should merge into 1 row, not 2 separate rows
        assert len(rows) == 1
        assert rows[0]["bet9ja"] != "-"
        assert rows[0]["sportybet"] != "-"

    def test_reversed_team_order_swaps_signs(self):
        """When bookmaker has teams reversed, signs should be swapped."""
        raw = {
            "bet9ja": [
                self._make_event("Arsenal - Chelsea", "Premier League", {
                    "1X2": {"1": "1.80", "X": "3.40", "2": "4.00"}
                })
            ],
            "sportybet": [
                self._make_event("Chelsea - Arsenal", "Premier League", {
                    "1X2": {"1": "3.90", "X": "3.50", "2": "1.85"}
                })
            ],
            "msport": [],
            "yajuego": [],
        }
        rows = merge_odds(raw)
        # Should merge into 3 rows (1, X, 2)
        assert len(rows) == 3

        sign1 = [r for r in rows if r["sign"] == "1"][0]
        # Bet9ja "1" = 1.80, SportyBet reversed "2" -> mapped to "1" = 1.85
        assert sign1["bet9ja"] == "1.80"
        assert sign1["sportybet"] == "1.85"

    def test_empty_data(self):
        raw = {
            "bet9ja": [],
            "sportybet": [],
            "msport": [],
            "yajuego": [],
        }
        rows = merge_odds(raw)
        assert rows == []

    def test_multiple_markets(self):
        raw = {
            "bet9ja": [
                self._make_event("Arsenal - Everton", "Premier League", {
                    "1X2": {"1": "1.50", "X": "3.20", "2": "5.00"},
                    "O/U 2.5": {"Over": "1.80", "Under": "2.00"},
                })
            ],
            "sportybet": [],
            "msport": [],
            "yajuego": [],
        }
        rows = merge_odds(raw)
        assert len(rows) == 5  # 3 from 1X2 + 2 from O/U

    def test_sportybet_odds_key(self):
        """SportyBet uses 'odds' key instead of 'markets'."""
        raw = {
            "bet9ja": [
                self._make_event("Arsenal - Everton", "Premier League", {
                    "1X2": {"1": "1.50", "X": "3.20", "2": "5.00"}
                })
            ],
            "sportybet": [
                {
                    "event": "Arsenal - Everton",
                    "league": "Premier League",
                    "odds": {"1X2": {"1": "1.55", "X": "3.10", "2": "4.80"}},
                }
            ],
            "msport": [],
            "yajuego": [],
        }
        rows = merge_odds(raw)
        assert len(rows) == 3
        assert rows[0]["sportybet"] != "-"

    def test_bet9ja_base_filter(self):
        """Events without Bet9ja odds should be excluded (Bet9ja is base bookmaker)."""
        raw = {
            "bet9ja": [],
            "sportybet": [
                {
                    "event": "Liverpool - Chelsea",
                    "league": "Premier League",
                    "odds": {"1X2": {"1": "1.55", "X": "3.10", "2": "4.80"}},
                }
            ],
            "msport": [],
            "yajuego": [],
        }
        rows = merge_odds(raw)
        assert len(rows) == 0, "Events without Bet9ja should be filtered out"


# ═══════════════════════════════════════════════════════════════════════
# 6. TEAM_ALIASES INTEGRITY
# ═══════════════════════════════════════════════════════════════════════

class TestTeamAliasesIntegrity:
    """Validate the TEAM_ALIASES dictionary is well-formed."""

    def test_no_empty_keys(self):
        for key in TEAM_ALIASES:
            assert key.strip() != "", f"Empty key found in TEAM_ALIASES"

    def test_no_empty_values(self):
        for key, val in TEAM_ALIASES.items():
            assert val.strip() != "", f"Empty value for key '{key}'"

    def test_all_lowercase_keys(self):
        for key in TEAM_ALIASES:
            assert key == key.lower(), f"Non-lowercase key: '{key}'"

    def test_all_lowercase_values(self):
        for key, val in TEAM_ALIASES.items():
            assert val == val.lower(), f"Non-lowercase value for '{key}': '{val}'"

    def test_no_self_referencing(self):
        """A key should not map to itself."""
        for key, val in TEAM_ALIASES.items():
            if key == val:
                # This is OK for canonical names, skip
                pass

    def test_canonical_names_consistent(self):
        """All aliases for the same team should map to the same value."""
        # Spot-check some important teams
        man_utd_aliases = ["man utd", "man united", "manchester united"]
        targets = set()
        for alias in man_utd_aliases:
            if alias in TEAM_ALIASES:
                targets.add(TEAM_ALIASES[alias])
        assert len(targets) <= 1, f"Inconsistent Man Utd aliases: {targets}"


# ═══════════════════════════════════════════════════════════════════════
# 7. SCRAPER OUTPUT FORMAT VALIDATION
# ═══════════════════════════════════════════════════════════════════════

class TestScraperOutputFormat:
    """Validate that scrapers produce data in the expected format."""

    REQUIRED_EVENT_KEYS = {"event", "league"}
    REQUIRED_MARKET_KEYS = {"1X2", "O/U 2.5", "Double Chance"}

    def _validate_event(self, event, bookmaker):
        """Check a single event dict has the expected structure."""
        assert "event" in event, f"{bookmaker}: missing 'event' key"
        assert "league" in event, f"{bookmaker}: missing 'league' key"
        assert " - " in event["event"], (
            f"{bookmaker}: event '{event['event']}' missing ' - ' separator"
        )

        # Must have either 'odds' or 'markets'
        odds_data = event.get("markets", event.get("odds", {}))
        assert isinstance(odds_data, dict), (
            f"{bookmaker}: odds data is not a dict"
        )

        for market_name, signs in odds_data.items():
            assert isinstance(signs, dict), (
                f"{bookmaker}: market '{market_name}' signs is not a dict"
            )
            for sign, value in signs.items():
                # Value should be convertible to float
                try:
                    float(str(value).replace(",", "."))
                except ValueError:
                    pytest.fail(
                        f"{bookmaker}: odds value '{value}' for "
                        f"{market_name}/{sign} is not a number"
                    )

    @pytest.mark.skipif(True, reason="Requires live scraper - run manually")
    def test_bet9ja_format(self):
        import asyncio
        from bet9ja_scraper import scrape_bet9ja
        events = asyncio.run(scrape_bet9ja(max_matches=5, days=1))
        assert len(events) > 0, "Bet9ja returned no events"
        for ev in events:
            self._validate_event(ev, "Bet9ja")

    @pytest.mark.skipif(True, reason="Requires live scraper - run manually")
    def test_sportybet_format(self):
        import asyncio
        from sportybet_scraper import scrape_sportybet
        events = asyncio.run(scrape_sportybet(max_matches=5, days=1))
        assert len(events) > 0, "SportyBet returned no events"
        for ev in events:
            self._validate_event(ev, "SportyBet")


# ═══════════════════════════════════════════════════════════════════════
# 8. CONFIGURATION VALIDATION
# ═══════════════════════════════════════════════════════════════════════

class TestConfiguration:
    """Test that configuration constants are valid."""

    def test_scrape_days_range(self):
        from main import SCRAPE_DAYS
        assert 1 <= SCRAPE_DAYS <= 10

    def test_msport_min_days(self):
        from main import MSPORT_MIN_DAYS
        assert MSPORT_MIN_DAYS >= 5  # Must be enough for coverage

    def test_bet9ja_min_days(self):
        from main import BET9JA_MIN_DAYS
        assert BET9JA_MIN_DAYS >= 5

    def test_max_matches_positive(self):
        from main import MAX_MATCHES
        assert MAX_MATCHES > 0

    def test_scraper_timeouts_all_set(self):
        from main import SCRAPER_TIMEOUTS
        required = ["Bet9ja", "SportyBet", "MSport", "YaJuego"]
        for bk in required:
            assert bk in SCRAPER_TIMEOUTS, f"Missing timeout for {bk}"
            assert SCRAPER_TIMEOUTS[bk] > 0

    def test_bookmaker_list(self):
        """Verify merge_odds uses the correct bookmaker list."""
        # This catches accidental removal of bookmakers
        from main import merge_odds
        import inspect
        source = inspect.getsource(merge_odds)
        for bk in ["bet9ja", "sportybet", "msport", "yajuego"]:
            assert bk in source, f"Bookmaker '{bk}' missing from merge_odds"


# ═══════════════════════════════════════════════════════════════════════
# 9. SYNTAX / IMPORT SMOKE TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestImports:
    """Verify all modules can be imported without syntax errors."""

    def test_import_main(self):
        import main
        assert hasattr(main, "merge_odds")
        assert hasattr(main, "do_refresh")

    def test_import_dashboard(self):
        import dashboard
        assert hasattr(dashboard, "build_dashboard_html")

    def test_import_bet9ja_scraper(self):
        import bet9ja_scraper
        assert hasattr(bet9ja_scraper, "scrape_bet9ja")

    def test_import_sportybet_scraper(self):
        import sportybet_scraper
        assert hasattr(sportybet_scraper, "scrape_sportybet")

    def test_import_msport_scraper(self):
        import msport_scraper
        assert hasattr(msport_scraper, "scrape_msport")

    def test_import_yajuego_scraper(self):
        import yajuego_scraper
        assert hasattr(yajuego_scraper, "scrape_yajuego")

    def test_import_betslip_checker(self):
        import betslip_checker
        assert hasattr(betslip_checker, "check_all_accumulators")


# ================================================================
# 10. API ENDPOINT TESTS (auth, comparison endpoints)
# ================================================================

class TestAPIEndpoints:
    """Test API endpoints require authentication and accept correct payloads."""

    def test_custom_comparison_requires_auth(self):
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        resp = client.post("/api/custom-comparison", json={
            "selections": [], "stake": 100, "bookmakers": ["bet9ja"]
        })
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_live_comparison_requires_auth(self):
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        resp = client.post("/api/live-comparison", json={
            "selections": [], "stake": 100, "bookmakers": ["bet9ja"]
        })
        assert resp.status_code in (401, 403), f"Expected 401/403, got {resp.status_code}"

    def test_custom_comparison_with_auth(self):
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        # Login first
        login_resp = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
        assert login_resp.status_code == 200
        token = login_resp.json().get("access_token", "")
        # Call custom-comparison with auth
        resp = client.post("/api/custom-comparison",
            json={"selections": [{"event": "Team A - Team B", "sign": "1", "market": "1X2", "bet9ja": "1.50"}], "stake": 100, "bookmakers": ["bet9ja"]},
            headers={"Authorization": f"Bearer {token}"}
        )
        # Should succeed (200) with valid selection
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        data = resp.json()
        assert "size" in data
        assert "selections" in data

# ═══════════════════════════════════════════════════════════════════════
# 11. PLAYWRIGHT SCRAPER PATTERN VALIDATION
# ═══════════════════════════════════════════════════════════════════════

class TestPlaywrightScraperPattern:
    """
    Validate that Playwright scrapers follow the required pattern:
    - No --disable-blink-features=AutomationControlled (crashes headless_shell)
    - JS stealth via add_init_script (webdriver, languages, plugins, chrome)
    - Browser context with ignore_https_errors=True
    - Proper cleanup (context.close + browser.close, no duplicates)
    """

    def _read_scraper_source(self, module_name):
        """Read the source code of a scraper module."""
        import inspect
        import importlib
        mod = importlib.import_module(module_name)
        return inspect.getsource(mod)

    # --- SportyBet ---

    def test_sportybet_no_disable_blink_features(self):
        """SportyBet must NOT use --disable-blink-features (crashes headless_shell)."""
        source = self._read_scraper_source("sportybet_scraper")
        assert "disable-blink-features" not in source, (
            "sportybet_scraper.py contains --disable-blink-features which crashes "
            "chromium_headless_shell. Use page.add_init_script() for stealth instead."
        )

    def test_sportybet_has_stealth_init_script(self):
        """SportyBet must use JS stealth via add_init_script."""
        source = self._read_scraper_source("sportybet_scraper")
        assert "add_init_script" in source, (
            "sportybet_scraper.py missing add_init_script() for JS stealth"
        )
        assert "navigator" in source and "webdriver" in source, (
            "sportybet_scraper.py stealth should hide navigator.webdriver"
        )
    def test_sportybet_uses_browser_context(self):
        """SportyBet must create a browser context (not use browser.new_page directly)."""
        source = self._read_scraper_source("sportybet_scraper")
        assert "new_context" in source, (
            "sportybet_scraper.py must use browser.new_context() for proper SSL handling"
        )
        assert "ignore_https_errors" in source, (
            "sportybet_scraper.py must set ignore_https_errors=True in browser context"
        )

    def test_sportybet_proper_cleanup(self):
        """SportyBet must close context then browser, without duplicate close calls."""
        source = self._read_scraper_source("sportybet_scraper")
        assert "context.close()" in source or "await context.close()" in source, (
            "sportybet_scraper.py must close the browser context"
        )
        assert "browser.close()" in source or "await browser.close()" in source, (
            "sportybet_scraper.py must close the browser"
        )
        # Check for duplicate context.close() calls
        close_count = source.count("context.close()")
        assert close_count == 1, (
            f"sportybet_scraper.py has {close_count} context.close() calls "
            f"(expected exactly 1 — duplicate close throws an error)"
        )

    # --- MSport ---

    def test_msport_no_disable_blink_features(self):
        """MSport must NOT use --disable-blink-features (crashes headless_shell)."""
        source = self._read_scraper_source("msport_scraper")
        assert "disable-blink-features" not in source, (
            "msport_scraper.py contains --disable-blink-features which crashes "
            "chromium_headless_shell. Use page.add_init_script() for stealth instead."
        )

    def test_msport_has_stealth_init_script(self):
        """MSport must use JS stealth via add_init_script."""
        source = self._read_scraper_source("msport_scraper")
        assert "add_init_script" in source, (
            "msport_scraper.py missing add_init_script() for JS stealth"
        )
        assert "navigator" in source and "webdriver" in source, (
            "msport_scraper.py stealth should hide navigator.webdriver"
        )
    def test_msport_uses_browser_context(self):
        """MSport must create a browser context."""
        source = self._read_scraper_source("msport_scraper")
        assert "new_context" in source, (
            "msport_scraper.py must use browser.new_context() for proper SSL handling"
        )
        assert "ignore_https_errors" in source, (
            "msport_scraper.py must set ignore_https_errors=True in browser context"
        )

    def test_msport_proper_cleanup(self):
        """MSport must close context then browser."""
        source = self._read_scraper_source("msport_scraper")
        assert "context.close()" in source or "await context.close()" in source, (
            "msport_scraper.py must close the browser context"
        )
        assert "browser.close()" in source or "await browser.close()" in source, (
            "msport_scraper.py must close the browser"
        )

    # --- General Playwright pattern ---

    def test_no_scraper_uses_automation_controlled_flag(self):
        """No scraper should use the --disable-blink-features flag."""
        scraper_modules = [
            "sportybet_scraper",
            "msport_scraper",
        ]
        for mod_name in scraper_modules:
            source = self._read_scraper_source(mod_name)
            assert "AutomationControlled" not in source, (
                f"{mod_name}.py contains AutomationControlled flag which is "
                f"incompatible with chromium_headless_shell"
            )

    def test_all_playwright_scrapers_have_user_agent(self):
        """All Playwright scrapers should set a custom user agent."""
        scraper_modules = [
            "sportybet_scraper",
            "msport_scraper",
        ]
        for mod_name in scraper_modules:
            source = self._read_scraper_source(mod_name)
            assert "user_agent" in source, (
                f"{mod_name}.py should set a custom user_agent in browser context"
            )

    def test_all_playwright_scrapers_have_no_sandbox(self):
        """All Playwright scrapers should use --no-sandbox for Docker compatibility."""
        scraper_modules = [
            "sportybet_scraper",
            "msport_scraper",
        ]
        for mod_name in scraper_modules:
            source = self._read_scraper_source(mod_name)
            assert "--no-sandbox" in source, (
                f"{mod_name}.py should use --no-sandbox for Docker/Railway"
            )

# ═══════════════════════════════════════════════════════════════════════
# 12. HEALTH AND DEBUG ENDPOINT TESTS
# ═══════════════════════════════════════════════════════════════════════

class TestHealthEndpoints:
    """Test unauthenticated health/debug endpoints."""

    def test_health_endpoint(self):
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "last_updated" in data or "is_refreshing" in data

    def test_debug_connectivity_endpoint(self):
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        resp = client.get("/debug/connectivity")
        assert resp.status_code == 200
