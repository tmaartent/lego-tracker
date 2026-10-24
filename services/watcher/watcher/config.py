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
