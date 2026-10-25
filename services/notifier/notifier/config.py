from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Read from NOTIFIER_* environment variables, e.g. NOTIFIER_TELEGRAM_BOT_TOKEN."""

    model_config = SettingsConfigDict(env_prefix="NOTIFIER_", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./notifier.db"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    # Without both of these, notifications are only logged.
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    # How long to wait before each retry of a failed send; after the last, the
    # message goes to the dead-letter queue.
    retry_delays_seconds: list[int] = [10, 60, 300]
