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

    @field_validator("cookie_domain", mode="before")
    @classmethod
    def _blank_domain_is_host_only(cls, value: object) -> object:
        # An empty env value means "host-only", not a literal empty Domain.
        if isinstance(value, str) and not value.strip():
            return None
        return value

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

    # --- Artifact storage (spec 003) ----------------------------------------
    #: MinIO in-cluster. Any S3-compatible endpoint works.
    s3_endpoint_url: str | None = None
    s3_bucket: str = "ctf-artifacts"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"
    #: Hard cap on a single upload. Large enough for a VM image, small enough
    #: that one careless upload cannot fill the volume.
    max_artifact_bytes: int = 256 * 1024 * 1024

    @property
    def s3_configured(self) -> bool:
        return bool(self.s3_endpoint_url and self.s3_access_key and self.s3_secret_key)

    # --- Anti-cheat signals (spec 007) --------------------------------------
    #: A value used by more players than this is a common guess, not sharing.
    signal_shared_answer_max_players: int = 4
    #: Short strings are guesses; long ones are shared.
    signal_shared_answer_min_length: int = 8
    #: How close behind another party's solve counts as suspicious.
    signal_close_solve_seconds: int = 120
    signal_first_try_ratio: float = 0.9
    signal_first_try_min_solves: int = 5
    #: How near the end of the event a join counts as late recruitment.
    signal_late_recruit_hours: int = 2
    signal_late_recruit_min_solves: int = 5
    #: Off by default. Everyone at a work event shares a corporate NAT, so this
    #: matches the whole field and reads as damning to someone who does not
    #: know that.
    signal_shared_ip_enabled: bool = False
    #: A player with at least this many integrity flags becomes a signal on the
    #: spec 007 review page, so repeated extraction attempts surface alongside
    #: the other anti-cheat findings rather than only in the flag log.
    signal_assistant_extraction_min: int = 5

    # --- AI assistant (spec 010) --------------------------------------------
    #: The in-cluster `ai` Service, so this value survives the host address
    #: changing. A secret rather than a manifest value: the project rules keep
    #: the model's address out of a public repo.
    ai_base_url: str | None = None
    #: Sent on every call. Measured: LM Studio is not currently enforcing it,
    #: so the real control is restricting that port at the host.
    ai_api_key: str | None = None
    ai_model: str = ""
    ai_enabled: bool = True
    #: Measured latency is around a second; this catches a wedged host.
    ai_timeout_seconds: float = 30.0
    ai_max_tokens: int = 400
    ai_temperature: float = 0.7
    #: Matches the measured concurrency sweet spot of ~6.7 responses/sec.
    ai_max_concurrency: int = 8
    #: Turns of history replayed to the model. An 8B context degrades quietly
    #: before it errors, which is worse than erroring.
    ai_history_turns: int = 10
    ai_max_message_length: int = 2000
    ai_messages_per_minute: int = 6
    ai_messages_per_hour: int = 100
    #: Consecutive failures before the breaker opens, and how long it stays open.
    ai_breaker_threshold: int = 5
    ai_breaker_cooldown_seconds: int = 60

    # --- Guardrails (spec 011) ----------------------------------------------
    ai_integrity_filter_enabled: bool = True
    ai_safety_filter_enabled: bool = True
    #: The judge is a second model call on an already-flagged reply. Off until
    #: the log shows how the deterministic layer behaves: the same uncensored 8B
    #: judging its own output is a weak control to trust with suppression.
    ai_safety_judge_enabled: bool = False
    #: Shape of a flag. Every flag-shaped reply is deflected whether or not the
    #: value is real, which is what stops the deflection being a correctness
    #: oracle for a player who pastes a guess.
    ai_flag_pattern: str = r"[A-Za-z0-9_]{2,16}\{[^}]{1,120}\}"
    #: Answers shorter than this are not scanned. "1337" or a single English word
    #: would deflect good advice several times an hour and train players to
    #: distrust the assistant.
    ai_answer_scan_min_length: int = 8
    #: Rebuilt at most this often. A newly written answer is unscanned for up to
    #: this long, which the structural guarantee in 010 still covers.
    ai_answer_cache_seconds: int = 60
    #: Hosts belonging to the event. A target *outside* this list, named
    #: alongside attack language, is what distinguishes the crawl from the real
    #: world. Configuration, never source: real internal names must not enter
    #: this repository.
    ai_event_domains: Annotated[list[str], NoDecode] = Field(default_factory=list)
    #: Age past which a conversation is purged. Conversations are the most
    #: personal thing this platform stores.
    ai_retention_days: int = 30

    @field_validator("ai_event_domains", mode="before")
    @classmethod
    def _split_event_domains(cls, value: object) -> object:
        if isinstance(value, str):
            return [d.strip().lower().lstrip("@") for d in value.split(",") if d.strip()]
        return value

    # --- Live challenge containers (spec 009) --------------------------------
    #: The pre-created, isolated namespace instances run in (spec 008).
    kube_namespace: str = "ctf-instances"
    #: Where instance subdomains live: <name>.<domain>. Not a secret.
    instance_base_domain: str = "ctf-nm.org"
    #: The sandboxed runtime every instance uses. The platform session's exact
    #: RuntimeClass name; a wrong value fails the pod at scheduling.
    instance_runtime_class: str = "gvisor"
    #: How HTTP instances are exposed. "ingress" authorises at the edge and needs
    #: wildcard DNS; "nodeport" is the unauthorised fallback if that is absent.
    instance_http_mode: str = "ingress"
    #: Concurrent live instances one owner (party, or lone player) may hold.
    instance_max_per_owner: int = 2
    instance_default_ttl_seconds: int = 3600
    #: TTL granted by an extend, while under the cap.
    instance_extend_seconds: int = 1800
    #: The image-pull secret the platform copied into the instance namespace.
    instance_image_pull_secret: str = "ghcr-pull"
    #: The wildcard-cert secret in the instance namespace (cert-manager issues it).
    instance_tls_secret: str = "ctf-tls"
    #: Turns the whole feature off cleanly, like AI_ENABLED.
    instances_enabled: bool = False

    # --- Progression (specs 015, 018) ----------------------------------------
    #: The level curve base: level L is reached at cumulative XP base*L*(L-1).
    xp_level_base: int = 100
    #: Level 20 is the D&D cap, and on the planned economy it falls at ~90% of all
    #: content. XP past it still counts for rank; the level simply stops.
    player_level_cap: int = 20

    #: A challenge's XP is its difficulty modifier times this.
    xp_base: int = 10

    #: Ability score = 8 + sqrt(ability_xp / divisor), capped.
    ability_score_divisor: int = 28
    ability_score_cap: int = 20

    #: Skill level L costs base*(L-1)**1.25 XP.
    skill_level_base: int = 70
    skill_level_cap: int = 15

    # --- Classes (spec 016) --------------------------------------------------
    #: The overall level a player must reach before they may choose a class.
    #: Level 5 is ~11 solves, so nearly everyone who engages unlocks one; 016
    #: allows free re-speccing afterwards, so an early gate costs no accuracy.
    class_unlock_level: int = 5

    @property
    def instances_configured(self) -> bool:
        return bool(self.instances_enabled and self.kube_namespace)

    @property
    def ai_configured(self) -> bool:
        return bool(self.ai_enabled and self.ai_base_url and self.ai_model)

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
