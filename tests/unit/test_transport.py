from __future__ import annotations

import importlib.util
import logging
from typing import Any

import pytest

from apiframework.config import ProxyConfig, TLSConfig, parse_config
from apiframework.errors import ConfigError
from apiframework.transport import HTTPTransport, _no_proxy_mounts


def _api(**api: Any) -> Any:
    cfg = parse_config({"apis": {"demo": {"base_url": "https://api.test", **api}}}, env={})
    return cfg.api("demo")


def test_timeouts_are_always_set_from_config() -> None:
    transport = HTTPTransport(_api(timeout={"connect": 2, "read": 11, "write": 12, "pool": 13}))
    timeout = transport._client.timeout
    assert (timeout.connect, timeout.read, timeout.write, timeout.pool) == (2, 11, 12, 13)


def test_default_timeouts_are_not_none() -> None:
    timeout = HTTPTransport(_api())._client.timeout
    assert None not in (timeout.connect, timeout.read, timeout.write, timeout.pool)


def test_socks_proxy_without_socksio_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(ImportError, match=r"apiframework\[socks\]"):
        HTTPTransport(_api(proxy={"url": "socks5://proxy.corp:1080"}))


def test_missing_ca_bundle_is_a_config_error(tmp_path: Any) -> None:
    missing = tmp_path / "nope.pem"
    with pytest.raises(ConfigError, match="cannot load certificate files"):
        HTTPTransport(_api(tls={"ca_bundle": str(missing)}))


def test_verify_false_logs_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="apiframework.transport"):
        HTTPTransport(_api(tls={"verify": False}))
    assert any("verification is disabled" in r.getMessage() for r in caplog.records)


def test_no_proxy_host_and_subdomains_get_direct_mounts() -> None:
    proxy = ProxyConfig(url="http://proxy.corp:8080", no_proxy=("internal.corp", "*.lab.test"))
    mounts = _no_proxy_mounts(proxy, True)
    assert set(mounts) == {
        "all://internal.corp",
        "all://*.internal.corp",
        "all://lab.test",
        "all://*.lab.test",
    }


def test_no_proxy_mounts_do_not_share_transport_instances() -> None:
    mounts = _no_proxy_mounts(ProxyConfig(no_proxy=("a.test",)), True)
    values = list(mounts.values())
    assert values[0] is not values[1]


def test_tls_defaults_verify_certificates() -> None:
    assert TLSConfig().verify is True
