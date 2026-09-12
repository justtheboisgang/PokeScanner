"""Central configuration.

All secrets and tunables come from the environment / `.env` (R5: no credentials
in code). Cascade factors are deliberately kept configurable so they can be
re-calibrated empirically without a code change (§6).
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- Database ---
    database_url: str = Field(
        default="postgresql+psycopg://poke:poke@localhost:5432/pokescanner",
        alias="DATABASE_URL",
    )

    # --- SoldComps ---
    soldcomps_api_key: str = Field(default="", alias="SOLDCOMPS_API_KEY")
    soldcomps_base_url: str = Field(
        default="https://api.sold-comps.com", alias="SOLDCOMPS_BASE_URL"
    )
    soldcomps_ebay_site: str = Field(default="ebay.de", alias="SOLDCOMPS_EBAY_SITE")
    soldcomps_credit_source: str = Field(
        default="subscription-only", alias="SOLDCOMPS_CREDIT_SOURCE"
    )
    soldcomps_use_cookies: bool = Field(default=False, alias="SOLDCOMPS_USE_COOKIES")
    soldcomps_ebay_cookies: str = Field(default="", alias="SOLDCOMPS_EBAY_COOKIES")
    soldcomps_cookie_min_interval: float = Field(
        default=3.0, alias="SOLDCOMPS_COOKIE_MIN_INTERVAL"
    )
    soldcomps_max_requests_per_minute: int = Field(
        default=55, alias="SOLDCOMPS_MAX_REQUESTS_PER_MINUTE"
    )

    # --- TCGdex ---
    tcgdex_base_url: str = Field(
        default="https://api.tcgdex.net/v2", alias="TCGDEX_BASE_URL"
    )
    tcgdex_primary_lang: str = Field(default="de", alias="TCGDEX_PRIMARY_LANG")

    # --- Reference value cascade (§6) ---
    cascade_min_sample_size: int = Field(default=5, alias="CASCADE_MIN_SAMPLE_SIZE")
    cascade_window_days: int = Field(default=90, alias="CASCADE_WINDOW_DAYS")
    cascade_condition_factor: Decimal = Field(
        default=Decimal("0.6"), alias="CASCADE_CONDITION_FACTOR"
    )
    cascade_language_factor: Decimal = Field(
        default=Decimal("0.8"), alias="CASCADE_LANGUAGE_FACTOR"
    )

    # --- Alert / buy thresholds (§7) ---
    alert_min_profit_eur: Decimal = Field(
        default=Decimal("20"), alias="ALERT_MIN_PROFIT_EUR"
    )
    buy_threshold_shipping_eur: Decimal = Field(
        default=Decimal("30"), alias="BUY_THRESHOLD_SHIPPING_EUR"
    )
    buy_threshold_pickup_eur: Decimal = Field(
        default=Decimal("80"), alias="BUY_THRESHOLD_PICKUP_EUR"
    )
    single_card_lookup_threshold_eur: Decimal = Field(
        default=Decimal("15"), alias="SINGLE_CARD_LOOKUP_THRESHOLD_EUR"
    )

    # --- Discord (Phase 2) ---
    discord_webhook_url: str = Field(default="", alias="DISCORD_WEBHOOK_URL")


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
