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

    # --- Apify (Kleinanzeigen, §4.4) ---
    apify_token: str = Field(default="", alias="APIFY_TOKEN")
    apify_base_url: str = Field(default="https://api.apify.com/v2", alias="APIFY_BASE_URL")
    apify_kleinanzeigen_actor: str = Field(
        default="", alias="APIFY_KLEINANZEIGEN_ACTOR"
    )
    # Cap items per query to bound Apify cost (Plan-Guthaben + Actor-Gebühren).
    apify_max_items_per_query: int = Field(
        default=40, alias="APIFY_MAX_ITEMS_PER_QUERY"
    )

    # --- Channels (Phase 5) ---
    kleinanzeigen_enabled: bool = Field(default=True, alias="KLEINANZEIGEN_ENABLED")
    willhaben_enabled: bool = Field(default=False, alias="WILLHABEN_ENABLED")
    apify_willhaben_actor: str = Field(default="", alias="APIFY_WILLHABEN_ACTOR")
    ebay_browse_enabled: bool = Field(default=False, alias="EBAY_BROWSE_ENABLED")
    ebay_client_id: str = Field(default="", alias="EBAY_CLIENT_ID")
    ebay_client_secret: str = Field(default="", alias="EBAY_CLIENT_SECRET")
    ebay_marketplace: str = Field(default="EBAY_DE", alias="EBAY_MARKETPLACE")
    ebay_oauth_url: str = Field(
        default="https://api.ebay.com/identity/v1/oauth2/token", alias="EBAY_OAUTH_URL"
    )
    ebay_browse_base_url: str = Field(
        default="https://api.ebay.com", alias="EBAY_BROWSE_BASE_URL"
    )
    ebay_browse_limit: int = Field(default=50, alias="EBAY_BROWSE_LIMIT")

    # --- Cost estimates per call (§9 Kosten) — EUR, default 0 (= nur Verbrauch,
    #     keine erfundene Kostenzahl, R3). Setzen, sobald echte Zahlen bekannt. ---
    cost_apify_per_run_eur: Decimal = Field(
        default=Decimal("0"), alias="COST_APIFY_PER_RUN_EUR"
    )
    cost_ebay_per_call_eur: Decimal = Field(
        default=Decimal("0"), alias="COST_EBAY_PER_CALL_EUR"
    )
    cost_vision_per_call_eur: Decimal = Field(
        default=Decimal("0"), alias="COST_VISION_PER_CALL_EUR"
    )

    # --- Cross-channel dedup (§5) ---
    dedup_image_hash_enabled: bool = Field(
        default=True, alias="DEDUP_IMAGE_HASH_ENABLED"
    )
    dedup_price_tolerance_eur: Decimal = Field(
        default=Decimal("5"), alias="DEDUP_PRICE_TOLERANCE_EUR"
    )

    # --- Alarm gate (Phase 2, §7) ---
    # No absolute price ceiling by default (R4). Set to enable one.
    alert_price_ceiling_eur: Decimal | None = Field(
        default=None, alias="ALERT_PRICE_CEILING_EUR"
    )
    # Listings without a price still fire ("VB"/leer ist bei Konvoluten Normalfall).
    alert_require_price: bool = Field(default=False, alias="ALERT_REQUIRE_PRICE")

    # --- Poll schedule (staggered, §11) ---
    scheduler_timezone: str = Field(default="Europe/Berlin", alias="SCHEDULER_TIMEZONE")
    poll_day_interval_minutes: int = Field(
        default=15, alias="POLL_DAY_INTERVAL_MINUTES"
    )
    poll_night_interval_minutes: int = Field(
        default=60, alias="POLL_NIGHT_INTERVAL_MINUTES"
    )
    poll_day_start_hour: int = Field(default=8, alias="POLL_DAY_START_HOUR")
    poll_day_end_hour: int = Field(default=23, alias="POLL_DAY_END_HOUR")

    # --- Enrichment (Phase 4, §11) — runs AFTER/parallel to the alarm, never in
    #     the critical path (§10). Vision hints only, never a verdict/price. ---
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    enrich_vision_enabled: bool = Field(default=True, alias="ENRICH_VISION_ENABLED")
    enrich_vision_model: str = Field(
        default="claude-opus-5", alias="ENRICH_VISION_MODEL"
    )
    # Hard cap on vision calls per poll to bound cost.
    enrich_vision_max_per_poll: int = Field(
        default=20, alias="ENRICH_VISION_MAX_PER_POLL"
    )
    # Max images sent per candidate to bound tokens.
    enrich_vision_max_images: int = Field(
        default=4, alias="ENRICH_VISION_MAX_IMAGES"
    )

    # --- Discord (§8) ---
    discord_webhook_url: str = Field(default="", alias="DISCORD_WEBHOOK_URL")


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
