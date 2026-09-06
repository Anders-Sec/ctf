"""Application settings, loaded from the environment.

Settings are validated at import time so a missing or malformed variable fails the
process on boot rather than at the first request that happens to need it.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "staging", "prod"]

_DEV_JWT_SECRET = "dev-only-insecure-secret-change-me"


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

    # --- Sessions (spec 002) -------------------------------------------------
    #: Signs the access-token JWTs. Rotating it invalidates every live session,
    #: so it is supplied per environment and never defaulted in production.
    jwt_secret: str = Field(default=_DEV_JWT_SECRET)
    jwt_key_id: str = "k1"
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 7 * 24 * 60 * 60
    #: How long a user record may be served from Redis before Postgres is
    #: consulted again. Approvals, kicks and disables invalidate it explicitly,
    #: so this is only a backstop.
    user_cache_ttl_seconds: int = 60
    #: Cookies must be Secure everywhere the app is served over HTTPS. Only a
    #: local, plain-HTTP dev server has a reason to turn this off.
    cookie_secure: bool = True
    cookie_domain: str | None = None

    #: Where the SPA lives, for building magic links and post-login redirects.
    app_public_url: str = "http://localhost:4173"

    # --- Entra ID (spec 002) -------------------------------------------------
    entra_tenant_id: str | None = None
    entra_client_id: str | None = None
    entra_client_secret: str | None = None
    entra_redirect_uri: str | None = None
    #: Domains that must use the work-account button rather than a magic link.
    #: Configuration, not a constant, so the domain list never enters source
    #: control and can be corrected without a deploy.
    entra_enforced_email_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Outbound mail (spec 002) --------------------------------------------
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_token: str | None = None
    smtp_from: str | None = None
    smtp_use_tls: bool = True
    magic_link_ttl_seconds: int = 15 * 60

    @field_validator("entra_enforced_email_domains", mode="before")
    @classmethod
    def _split_domains(cls, value: object) -> object:
        if isinstance(value, str):
            return [d.strip().lower().lstrip("@") for d in value.split(",") if d.strip()]
        return value

    @property
    def entra_configured(self) -> bool:
        return all(
            (
                self.entra_tenant_id,
                self.entra_client_id,
                self.entra_client_secret,
                self.entra_redirect_uri,
            )
        )

    @property
    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_from)

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @model_validator(mode="after")
    def _check_production_secrets(self) -> "Settings":
        """A shared default signing key would let anyone mint an admin session."""
        if self.environment != "local":
            if self.jwt_secret == _DEV_JWT_SECRET:
                raise ValueError("JWT_SECRET must be set outside local development")
            if not self.cookie_secure:
                raise ValueError("COOKIE_SECURE must stay on outside local development")
        return self

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
