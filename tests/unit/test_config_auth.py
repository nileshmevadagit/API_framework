"""Config for auth, retries and rate limits. Secrets must be references and never print."""

from __future__ import annotations

from typing import Any

import pytest

from apiframework.config import ApiKeyAuth, BearerAuth, parse_config
from apiframework.errors import ConfigError

BASE = "https://api.test/v1"
ENV = {"TOKEN": "tok-123", "KEY": "key-456", "U": "user", "P": "pass", "ID": "cid", "S": "csec"}


def _api(**extra: Any) -> dict[str, Any]:
    return {"apis": {"demo": {"base_url": BASE, **extra}}}


def test_bearer_token_is_resolved_and_hidden_in_repr() -> None:
    cfg = parse_config(_api(auth={"type": "bearer", "token": "${TOKEN}"}), env=ENV)
    auth = cfg.api("demo").auth
    assert isinstance(auth, BearerAuth)
    assert auth.token.get_secret_value() == "tok-123"
    assert "tok-123" not in repr(cfg)


def test_literal_secret_is_refused_by_name() -> None:
    with pytest.raises(ConfigError, match="token: must reference an environment variable"):
        parse_config(_api(auth={"type": "bearer", "token": "ghp_literal"}), env=ENV)


def test_missing_environment_variable_for_auth_is_named() -> None:
    with pytest.raises(ConfigError, match="NOPE"):
        parse_config(_api(auth={"type": "bearer", "token": "${NOPE}"}), env=ENV)


def test_api_key_defaults_to_header_location() -> None:
    cfg = parse_config(_api(auth={"type": "api_key", "name": "X-Key", "value": "${KEY}"}), env=ENV)
    auth = cfg.api("demo").auth
    assert isinstance(auth, ApiKeyAuth)
    assert auth.location == "header"


def test_unknown_auth_type_is_rejected() -> None:
    with pytest.raises(ConfigError):
        parse_config(_api(auth={"type": "magic", "token": "${TOKEN}"}), env=ENV)


def test_oauth2_needs_absolute_token_url() -> None:
    with pytest.raises(ConfigError, match="token_url"):
        parse_config(
            _api(
                auth={
                    "type": "oauth2",
                    "token_url": "/token",
                    "client_id": "${ID}",
                    "client_secret": "${S}",
                }
            ),
            env=ENV,
        )


def test_oauth2_secrets_are_hidden() -> None:
    cfg = parse_config(
        _api(
            auth={
                "type": "oauth2",
                "token_url": "https://auth.test/token",
                "client_id": "${ID}",
                "client_secret": "${S}",
            }
        ),
        env=ENV,
    )
    text = repr(cfg)
    assert "csec" not in text
    assert "cid" not in text


def test_retry_defaults_apply_and_can_be_overridden_per_api() -> None:
    cfg = parse_config(
        {
            "defaults": {"retry": {"max_attempts": 6}},
            "apis": {
                "a": {"base_url": BASE},
                "b": {"base_url": BASE, "retry": {"max_attempts": 2}},
            },
        },
        env=ENV,
    )
    assert cfg.api("a").retry.max_attempts == 6
    assert cfg.api("b").retry.max_attempts == 2


def test_retry_attempts_must_be_at_least_one() -> None:
    with pytest.raises(ConfigError):
        parse_config({"defaults": {"retry": {"max_attempts": 0}}, "apis": {}}, env=ENV)


def test_rate_limits_parse_and_default_to_raise() -> None:
    cfg = parse_config(
        _api(rate_limits=[{"window": "hour", "limit": 5000}, {"window": "second", "limit": 10}]),
        env=ENV,
    )
    limits = cfg.api("demo").rate_limits
    assert [(lim.window, lim.limit, lim.on_exhausted) for lim in limits] == [
        ("hour", 5000, "raise"),
        ("second", 10, "raise"),
    ]


def test_unknown_rate_window_is_rejected() -> None:
    with pytest.raises(ConfigError):
        parse_config(_api(rate_limits=[{"window": "minute", "limit": 5}]), env=ENV)
