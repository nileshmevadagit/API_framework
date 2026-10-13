from __future__ import annotations

import sys
from typing import Any

import pytest

from apiframework.config import Config, ProxyConfig, TLSConfig, load_config, parse_config
from apiframework.errors import ConfigError

ENV = {"API_KEY": "from-env", "PROXY_PASS": "p4ss", "TOKEN": "tok"}


def _config(**api: Any) -> dict[str, Any]:
    return {"apis": {"demo": {"base_url": "https://api.test/v1", **api}}}


def test_defaults_fill_in_when_api_has_no_override() -> None:
    cfg = parse_config(
        {"defaults": {"timeout": {"connect": 2}}, **_config()},
        env=ENV,
    )
    resolved = cfg.api("demo")
    assert resolved.timeout.connect == 2
    assert resolved.timeout.read == 30  # untouched default
    assert resolved.base_url == "https://api.test/v1"


def test_api_section_replaces_default_section_as_a_whole() -> None:
    cfg = parse_config(
        {
            "defaults": {"timeout": {"connect": 2, "read": 9}},
            **_config(timeout={"connect": 7}),
        },
        env=ENV,
    )
    timeout = cfg.api("demo").timeout
    assert timeout.connect == 7
    assert timeout.read == 30  # not inherited from defaults: the section replaced it


def test_unknown_api_name_is_a_config_error() -> None:
    cfg = parse_config(_config(), env=ENV)
    with pytest.raises(ConfigError, match="no API named 'other'"):
        cfg.api("other")


def test_unknown_key_is_rejected_so_typos_fail_loudly() -> None:
    with pytest.raises(ConfigError, match="Extra inputs"):
        parse_config(_config(base_ur="https://typo"), env=ENV)


def test_timeouts_must_be_positive() -> None:
    with pytest.raises(ConfigError, match="greater than 0"):
        parse_config(_config(timeout={"read": 0}), env=ENV)


def test_header_reference_is_expanded_from_environment() -> None:
    cfg = parse_config(_config(headers={"X-Api-Key": "${API_KEY}"}), env=ENV)
    assert cfg.api("demo").headers == {"X-Api-Key": "from-env"}


def test_pasted_key_in_header_is_rejected() -> None:
    with pytest.raises(ConfigError, match="pasted secret"):
        parse_config(_config(headers={"X-Note": "Bearer ghp_0123456789abcdefghij"}))


def test_literal_value_in_credential_header_is_rejected() -> None:
    with pytest.raises(ConfigError, match="must reference an environment variable"):
        parse_config(_config(headers={"X-Api-Key": "abc"}), env=ENV)


def test_missing_environment_variable_is_reported_by_name() -> None:
    with pytest.raises(ConfigError, match="NOT_SET"):
        parse_config(_config(headers={"X-Api-Key": "${NOT_SET}"}), env=ENV)


def test_proxy_password_is_expanded_from_environment() -> None:
    cfg = parse_config(
        _config(proxy={"url": "http://user:${PROXY_PASS}@proxy.corp:8080"}),
        env=ENV,
    )
    assert cfg.api("demo").proxy.url == "http://user:p4ss@proxy.corp:8080"


def test_literal_proxy_password_is_rejected() -> None:
    with pytest.raises(ConfigError, match="ENV_VAR"):
        parse_config(_config(proxy={"url": "http://user:hunter2@proxy.corp:8080"}), env=ENV)


def test_proxy_scheme_must_be_known() -> None:
    with pytest.raises(ConfigError, match="unsupported scheme"):
        parse_config(_config(proxy={"url": "ftp://proxy.corp:21"}), env=ENV)


@pytest.mark.parametrize("base_url", ["api.test/v1", "ftp://api.test", "https://"])
def test_base_url_must_be_absolute_http(base_url: str) -> None:
    with pytest.raises(ConfigError, match="base_url"):
        parse_config({"apis": {"demo": {"base_url": base_url}}}, env=ENV)


def test_client_key_needs_client_cert() -> None:
    with pytest.raises(ConfigError, match="client_key needs client_cert"):
        TLSConfig(client_key="/keys/client.key")


def test_ca_bundle_conflicts_with_verify_false() -> None:
    with pytest.raises(ConfigError, match="no effect"):
        TLSConfig(verify=False, ca_bundle="/certs/ca.pem")


def test_proxy_defaults_do_not_read_environment_proxies() -> None:
    assert ProxyConfig().trust_env is False


def test_config_error_is_not_wrapped_when_built_directly() -> None:
    # Validators raise ConfigError itself, so direct construction surfaces it too.
    with pytest.raises(ConfigError, match="pasted secret"):
        Config.model_validate(
            {"apis": {"demo": {"base_url": "https://x.test", "headers": {"A": "ghp_abc"}}}}
        )


def test_load_config_reads_yaml(tmp_path: Any) -> None:
    path = tmp_path / "job.yaml"
    path.write_text(
        "defaults:\n"
        "  timeout: {connect: 3}\n"
        "apis:\n"
        "  demo:\n"
        "    base_url: https://api.test/v1\n"
        "    headers: {X-Api-Key: '${API_KEY}'}\n",
        encoding="utf-8",
    )
    cfg = load_config(path, env=ENV)
    resolved = cfg.api("demo")
    assert resolved.timeout.connect == 3
    assert resolved.headers == {"X-Api-Key": "from-env"}


def test_load_config_rejects_non_mapping_yaml(tmp_path: Any) -> None:
    path = tmp_path / "job.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="top level must be a mapping"):
        load_config(path, env=ENV)


def test_yaml_missing_points_at_the_extra(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "job.yaml"
    path.write_text("apis: {}\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "yaml", None)  # makes `import yaml` raise ImportError
    with pytest.raises(ImportError, match=r"apiframework\[yaml\]"):
        load_config(path, env=ENV)
