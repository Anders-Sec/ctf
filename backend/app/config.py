"""Application settings, loaded from the environment.

Settings are validated at import time so a missing or malformed variable fails the
process on boot rather than at the first request that happens to need it.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "staging", "prod"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = "local"
    app_version: str = "dev"
    log_level: str = "INFO"

    database_url: str = Field(..., description="Driver-neutral postgres URL")
    redis_url: str = Field(...)

    # NoDecode: without it pydantic-settings tries to JSON-decode the raw env
    # value before any validator sees it, and a comma-separated list is not JSON.
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "prod"

    @property
    def async_database_url(self) -> str:
        """The app talks to Postgres over asyncpg."""
        return _with_driver(self.database_url, "postgresql+asyncpg")

    @property
    def sync_database_url(self) -> str:
        """Alembic runs migrations over a sync driver."""
        return _with_driver(self.database_url, "postgresql+psycopg")


def _with_driver(url: str, driver: str) -> str:
    """Swap whatever scheme DATABASE_URL carries for an explicit driver.

    DATABASE_URL is stored driver-neutral (``postgresql://...``) so one value can
    serve both the async app and sync migrations.
    """
    _, separator, remainder = url.partition("://")
    if not separator:
        raise ValueError("DATABASE_URL must include a scheme, e.g. postgresql://")
    return f"{driver}://{remainder}"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
