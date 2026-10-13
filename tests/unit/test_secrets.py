from __future__ import annotations

import pytest

from apiframework.errors import ConfigError
from apiframework.secrets import (
    expand_refs,
    reject_literal_name_value,
    reject_literal_secret,
    reject_literal_userinfo,
)


def test_expand_replaces_each_reference() -> None:
    env = {"USER": "alice", "PASS": "s3cret"}
    assert expand_refs("${USER}:${PASS}", env, where="x") == "alice:s3cret"


def test_missing_variable_names_the_variable_not_the_value() -> None:
    with pytest.raises(ConfigError, match="MISSING_TOKEN") as info:
        expand_refs("Bearer ${MISSING_TOKEN}", {}, where="headers.Authorization")
    assert "headers.Authorization" in str(info.value)


@pytest.mark.parametrize(
    "value",
    ["application/json", "2022-11-28", "Bearer ${TOKEN}", "plain text value"],
)
def test_ordinary_values_are_accepted(value: str) -> None:
    reject_literal_secret(value, where="x")


@pytest.mark.parametrize(
    "value",
    [
        "Bearer ghp_abcdefghijklmnopqrstuvwxyz0123456789",
        "AKIAIOSFODNN7EXAMPLE",
        "sk_live_51H8abcdef",
        "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5",
    ],
)
def test_pasted_keys_are_rejected(value: str) -> None:
    with pytest.raises(ConfigError, match="pasted secret"):
        reject_literal_secret(value, where="headers.Authorization")


def test_credential_named_header_needs_a_reference() -> None:
    with pytest.raises(ConfigError, match="must reference an environment variable"):
        reject_literal_name_value("X-Api-Key", "abc123", where="headers.X-Api-Key")


def test_credential_named_header_with_reference_is_fine() -> None:
    reject_literal_name_value("X-Api-Key", "${API_KEY}", where="headers.X-Api-Key")


def test_non_credential_header_may_hold_a_literal() -> None:
    reject_literal_name_value("Accept", "application/json", where="headers.Accept")


def test_literal_password_in_url_is_rejected() -> None:
    with pytest.raises(ConfigError, match="must be \\$\\{ENV_VAR\\}"):
        reject_literal_userinfo("http://user:hunter2@proxy.corp:8080", where="proxy.url")


def test_referenced_password_in_url_is_accepted() -> None:
    reject_literal_userinfo("http://user:${PROXY_PASS}@proxy.corp:8080", where="proxy.url")
