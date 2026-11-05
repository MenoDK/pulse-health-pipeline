"""Configuration: validated at startup, and a production start refuses every demonstration default."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from pulse.config import DEMO_API_KEY, DEMO_PSEUDONYM_KEY, Settings

GOOD_API_KEY = "k" * 24
GOOD_PSEUDONYM_KEY = "p" * 32


def settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[call-arg]


def production(**overrides: Any) -> Settings:
    base: dict[str, Any] = {"app_env": "production", "api_key": GOOD_API_KEY, "pseudonym_key": GOOD_PSEUDONYM_KEY}
    return settings(**{**base, **overrides})


def test_the_defaults_are_a_working_laptop_configuration() -> None:
    s = settings()
    assert s.app_env == "development" and s.lab_mode is False
    assert s.api_key == DEMO_API_KEY and s.pseudonym_key == DEMO_PSEUDONYM_KEY


def test_a_production_configuration_with_real_secrets_starts() -> None:
    assert production().app_env == "production"


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"api_key": DEMO_API_KEY}, "API_KEY"),
        ({"api_key": "short"}, "API_KEY"),
        ({"api_key": "k" * 23}, "API_KEY"),
        ({"pseudonym_key": DEMO_PSEUDONYM_KEY}, "PSEUDONYM_KEY"),
        ({"pseudonym_key": "p" * 31}, "PSEUDONYM_KEY"),
        ({"lab_mode": True}, "LAB_MODE"),
        ({"standin_control": True}, "STANDIN_CONTROL"),
    ],
)
def test_production_refuses_each_demonstration_default_and_says_which(override: dict[str, Any], fragment: str) -> None:
    with pytest.raises(ValidationError, match=f"refusing to start in production.*{fragment}"):
        production(**override)


def test_every_problem_is_reported_at_once_not_one_per_restart() -> None:
    with pytest.raises(ValidationError) as raised:
        settings(app_env="production", lab_mode=True)  # demo api key, demo pseudonym key and the lab
    message = str(raised.value)
    assert all(word in message for word in ("API_KEY", "PSEUDONYM_KEY", "LAB_MODE"))


@pytest.mark.parametrize(
    "env", ["production", "Production", " PRODUCTION ", "prod", "staging", "live", "", "anything-else"]
)
def test_any_environment_that_is_not_a_development_one_is_guarded(env: str) -> None:
    """A typo in APP_ENV must not switch the checks off."""
    with pytest.raises(ValidationError, match="refusing to start in production"):
        settings(app_env=env)


@pytest.mark.parametrize("env", ["development", "dev", "local", "test", "Development", " DEV "])
def test_a_development_environment_may_use_the_defaults_and_the_lab(env: str) -> None:
    assert settings(app_env=env, lab_mode=True, standin_control=True).lab_mode is True


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@db:5432/x", "postgresql+psycopg://u:p@db:5432/x"),
        ("postgres://u:p@db/x", "postgresql+psycopg://u:p@db/x"),
        ("postgresql+psycopg://u:p@db/x", "postgresql+psycopg://u:p@db/x"),
    ],
)
def test_the_database_url_is_rewritten_for_the_driver_whatever_scheme_was_written(given: str, expected: str) -> None:
    assert settings(database_url=given).sqlalchemy_url == expected


def test_the_token_url_defaults_to_the_gateways_own_path_and_can_be_overridden() -> None:
    assert settings(gateway_url="https://gw.test:9443/").token_url == "https://gw.test:9443/oauth/token"
    assert (
        settings(gateway_url="https://gw.test", gateway_token_url="https://auth.test/t").token_url
        == "https://auth.test/t"
    )


@pytest.mark.parametrize(
    "override",
    [
        {"sync_page_size": 0},
        {"sync_page_size": 5001},
        {"queue_batch": 0},
        {"queue_max_attempts": 0},
        {"queue_lease_seconds": 0},
        {"gateway_timeout_seconds": 0},
        {"queue_backoff_base_seconds": 0},
        {"search_rrf_k": 0},
        {"token_margin_seconds": -1},
    ],
)
def test_numbers_that_would_break_the_pipeline_are_refused_at_startup(override: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        settings(**override)


def test_environment_variables_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUEUE_BATCH", "7")
    monkeypatch.setenv("LAB_MODE", "true")
    s = settings()
    assert s.queue_batch == 7 and s.lab_mode is True
