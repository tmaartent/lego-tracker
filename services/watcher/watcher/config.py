from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from WATCHER_* environment variables, e.g. WATCHER_DATABASE_URL."""

    model_config = SettingsConfigDict(env_prefix="WATCHER_", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./watcher.db"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    core_url: str = "http://localhost:8000"
    home_postcode: str = "3600"
    sources: list[str] = ["fake"]
    poll_interval_seconds: float = 300
    relay_interval_seconds: float = 1

    # eBay Browse API keys, from https://developer.ebay.com/my/keys
    ebay_client_id: str | None = None
    ebay_client_secret: SecretStr | None = None
    ebay_sandbox: bool = False
    ebay_marketplace: str = "EBAY_BE"
    # Only sellers in this country (e.g. "BE"); None means anyone who ships here.
    ebay_seller_country: str | None = None
    # One call per watched set per poll; eBay allows 5,000 calls a day.
    ebay_poll_interval_seconds: float = 900
