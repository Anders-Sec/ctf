"""Application settings, loaded from the environment.

Settings are validated at import time so a missing or malformed variable fails the
process on boot rather than at the first request that happens to need it.
"""

from functools import lru_cache
from pathlib import Path
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
    # (The `assistant_extraction` signal was removed by spec 033. It counted
    # integrity findings, and on a prompt-injection ladder every player is
    # attempting extraction because that is the challenge — the signal would
    # have recorded two hundred people doing what they were asked to do.)

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

    # --- Terms of use (spec 035) ---------------------------------------------
    #: The System AI's terms of use. A path rather than embedded copy so the
    #: wording can go through management review and be revised without a
    #: rebuild — and so a ConfigMap can be mounted over it later without a
    #: migration. The file's hash is the version, so any edit re-gates everyone.
    ai_terms_path: str = str(Path(__file__).resolve().parent / "content" / "system-ai-terms.md")

    # --- The ladder (spec 033) ----------------------------------------------
    #: What the System AI is allowed to say it knows about the event. The prompt's
    #: TRUTH RULE binds it to exactly this and forbids inventing anything else —
    #: early versions invented scoreboards, point values and floor contents.
    #: Dynamic event facts are the next spec's business.
    ai_event_name: str = "the Crawl"
    ai_event_facts: str = ""
    #: Turns the ladder off without turning the chat off. The System AI then has
    #: no flag to defend at any level, so this is not a way to run the assistant
    #: "safely" — it is a way to take six challenges off the board.
    ai_ladder_enabled: bool = True

    # --- Guardrails (spec 011, amended by 033) -------------------------------
    #: Layer A — the flag guardrail — was **removed** by spec 033. In the ladder
    #: the flag reaching the player is the win condition, so a filter that stops
    #: it makes every level unwinnable. What replaces it: the per-level gates,
    #: the decoy filter at every level, and the structural guarantee that no
    #: answer value is ever placed in a prompt.
    #:
    #: Layer B — real-world safety — is untouched and runs on every reply at
    #: every level. Protection level governs flag secrecy only.
    ai_safety_filter_enabled: bool = True
    #: Optional extra wordlist for the conduct rules (spec 036), as
    #: ``category: word`` lines. Not committed: this repository is public, and
    #: the terms that matter most are the ones nobody wants to read in a diff.
    #: Absent is fine — the built-in list still applies.
    ai_wordlist_path: str | None = None
    #: The judge is a second model call on an already-flagged reply. Off until
    #: the log shows how the deterministic layer behaves: the same uncensored 8B
    #: judging its own output is a weak control to trust with suppression.
    ai_safety_judge_enabled: bool = False
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
    #: Grace left on a shared container once its owner has solved every challenge
    #: it serves (spec 046). Not an immediate teardown: the expiry loop already
    #: destroys correctly, and a few minutes means the container does not vanish
    #: out from under a teammate still reading what they just solved.
    instance_completion_grace_seconds: int = 300
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
    #: Hours to add to a stored UTC timestamp to get the hour players actually
    #: experienced. The event runs in one place, so "01:00" in an achievement
    #: has to mean 01:00 there rather than 01:00 UTC (spec 029).
    event_utc_offset_hours: int = 0

    # --- Daily puzzles (spec 044) --------------------------------------------
    #: Where the Wordle guess list lives. Null uses the list bundled in the
    #: image (`app/data/wordle_words_5.txt`, ~1,000 common words). Pointing this
    #: at a mounted file is how the list is grown without a code change, which
    #: matters because an author cannot know in advance which ordinary word a
    #: player will try and be refused.
    wordle_word_list_path: str | None = None

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
