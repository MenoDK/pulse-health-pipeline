"""Validated configuration, read once at startup.

The defaults are for a laptop. Any `APP_ENV` that is not a development one (so `production`, but also `prod` and
`staging`: a typo must not switch the checks off) refuses the defaults that must never reach a real deployment: the
demonstration API key, the demonstration pseudonymisation key, and the lab.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEMO_API_KEY = "change-me"
DEMO_PSEUDONYM_KEY = "demo-pseudonym-key-do-not-use-in-production"
DEVELOPMENT_ENVS = frozenset({"development", "dev", "local", "test"})


class ConfigError(ValueError):
    """The configuration cannot be used. The message says which setting and why."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    lab_mode: bool = False
    site_dir: str = ""

    api_key: str = DEMO_API_KEY
    database_url: str = "postgresql://pulse:pulse@localhost:15440/pulse"
    redis_url: str = "redis://localhost:16395/0"

    # Pseudonymisation: a keyed hash of every direct identifier, so the analytic layer never holds one.
    pseudonym_key: str = DEMO_PSEUDONYM_KEY
    pseudonym_key_id: str = "k1"

    # The source system (a registry) and the national gateway the pipeline reports to.
    registry_url: str = "http://localhost:9100"
    registry_timeout_seconds: float = 10.0
    sync_page_size: int = Field(default=200, ge=1, le=5000)

    gateway_url: str = "https://localhost:9443"
    gateway_token_url: str = ""  # empty: <gateway_url>/oauth/token
    gateway_client_id: str = "pulse-demo"
    gateway_client_secret: str = "pulse-demo-secret"  # noqa: S105  (a placeholder for the stand-in gateway)
    gateway_ca_file: str = ""
    gateway_cert_file: str = ""
    gateway_key_file: str = ""
    gateway_timeout_seconds: float = Field(default=5.0, gt=0)
    token_margin_seconds: int = Field(default=60, ge=0)

    # The transmission queue.
    queue_max_attempts: int = Field(default=10, ge=1)
    queue_lease_seconds: int = Field(default=120, ge=1)
    queue_batch: int = Field(default=50, ge=1, le=1000)
    queue_backoff_base_seconds: int = Field(default=30, ge=1)
    queue_backoff_cap_seconds: int = Field(default=21_600, ge=1)

    # Search.
    embedding_dim: int = 256
    search_rrf_k: int = Field(default=60, ge=1)

    # Stand-ins (the source and the gateway used by compose and the lab).
    standin_control: bool = False

    @model_validator(mode="after")
    def _production_guard(self) -> Self:
        if self.app_env.strip().lower() in DEVELOPMENT_ENVS:
            return self
        problems = []
        if self.api_key == DEMO_API_KEY or len(self.api_key) < 24:
            problems.append("API_KEY is the demonstration value or shorter than 24 characters")
        if self.pseudonym_key == DEMO_PSEUDONYM_KEY or len(self.pseudonym_key) < 32:
            problems.append("PSEUDONYM_KEY is the demonstration value or shorter than 32 characters")
        if self.lab_mode:
            problems.append("LAB_MODE is on: the lab can move time and break the gateway, and has no login")
        if self.standin_control:
            problems.append("STANDIN_CONTROL is on")
        if problems:
            raise ConfigError("refusing to start in production: " + "; ".join(problems))
        return self

    @property
    def sqlalchemy_url(self) -> str:
        """The psycopg 3 driver, whatever scheme the operator wrote."""
        url = self.database_url
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix) :]
        return url

    @property
    def token_url(self) -> str:
        return self.gateway_token_url or self.gateway_url.rstrip("/") + "/oauth/token"


@lru_cache
def get_settings() -> Settings:
    return Settings()
