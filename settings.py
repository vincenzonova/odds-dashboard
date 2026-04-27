"""
Application settings using pydantic-settings.
All configuration is driven by environment variables with sensible defaults.
"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Odds Dashboard configuration. Every field maps to an env var."""

    # --- App ---
    secret_key: str = "change-me-in-production"
    debug: bool = False

    # --- Scraping ---
    max_matches: int = 160
    scrape_days: int = 10
    msport_min_days: int = 10
    bet9ja_min_days: int = 10
    refresh_interval_minutes: int = 5
    default_scraper_timeout: int = 120
    gather_timeout_seconds: int = 600

    # --- Scraper-specific timeouts ---
    timeout_bet9ja: int = 60
    timeout_sportybet: int = 420
    timeout_msport: int = 600
    timeout_yajuego: int = 60
    timeout_betfair: int = 60

    # --- Database ---
    db_path: str = "odds_history.db"

    # --- Betslip service ---
    betslip_service_url: str = ""
    betslip_api_secret: str = "betslip-secret-key"

    # --- Server ---
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    model_config = {"env_prefix": "", "case_sensitive": False}

    @property
    def scraper_timeouts(self) -> dict[str, int]:
        return {
            "Bet9ja": self.timeout_bet9ja,
            "SportyBet": self.timeout_sportybet,
            "MSport": self.timeout_msport,
            "YaJuego": self.timeout_yajuego,
            "Betfair": self.timeout_betfair,
        }


settings = Settings()
