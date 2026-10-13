"""Configuration models. YAML and plain Python both load into these.

Settings can be set once in ``defaults`` and overridden per API. An API's ``timeout``,
``proxy`` or ``tls`` section replaces the default section as a whole; it is not merged
field by field.

Secrets are written as ``${ENV_VAR}``. The environment comes from the validation
context (``parse_config(data, env=...)``), defaulting to ``os.environ``. Validators
raise ``ConfigError`` directly so it reaches the caller unwrapped.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from apiframework.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Mapping

from apiframework.secrets import (
    expand_refs,
    reject_literal_name_value,
    reject_literal_secret,
    reject_literal_userinfo,
)


def _env(info: ValidationInfo) -> Mapping[str, str]:
    context: Any = info.context
    if isinstance(context, dict) and "env" in context:
        env: Mapping[str, str] = context["env"]
        return env
    return os.environ


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Timeouts(_Model):
    """Seconds. Always set, so a stalled server cannot hang a worker."""

    connect: float = Field(default=5.0, gt=0)
    read: float = Field(default=30.0, gt=0)
    write: float = Field(default=30.0, gt=0)
    pool: float = Field(default=5.0, gt=0)


class ProxyConfig(_Model):
    """Forward proxy. ``url`` may reference ``${VAR}`` for its credentials."""

    url: str | None = None
    no_proxy: tuple[str, ...] = ()
    trust_env: bool = False

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is None:
            return None
        reject_literal_userinfo(value, where="proxy.url")
        scheme = urlsplit(value).scheme
        if scheme not in ("http", "https", "socks5", "socks5h"):
            raise ConfigError(f"proxy.url: unsupported scheme {scheme!r}")
        return expand_refs(value, _env(info), where="proxy.url")


class TLSConfig(_Model):
    """Certificate checking and client certificates, for corporate proxies and mTLS."""

    verify: bool = True
    ca_bundle: str | None = None
    client_cert: str | None = None
    client_key: str | None = None

    @model_validator(mode="after")
    def _check_combinations(self) -> TLSConfig:
        if not self.verify and self.ca_bundle:
            raise ConfigError("tls: ca_bundle has no effect when verify is false")
        if self.client_key and not self.client_cert:
            raise ConfigError("tls: client_key needs client_cert")
        return self


class Defaults(_Model):
    timeout: Timeouts = Field(default_factory=Timeouts)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    tls: TLSConfig = Field(default_factory=TLSConfig)


class ApiConfig(_Model):
    base_url: str
    headers: dict[str, str] = Field(default_factory=dict)
    timeout: Timeouts | None = None
    proxy: ProxyConfig | None = None
    tls: TLSConfig | None = None

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str, info: ValidationInfo) -> str:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ConfigError(f"base_url must be an absolute http(s) URL, got {value!r}")
        reject_literal_userinfo(value, where="base_url")
        return expand_refs(value, _env(info), where="base_url")

    @field_validator("headers")
    @classmethod
    def _check_headers(cls, value: dict[str, str], info: ValidationInfo) -> dict[str, str]:
        env = _env(info)
        checked: dict[str, str] = {}
        for name, raw in value.items():
            where = f"headers.{name}"
            reject_literal_name_value(name, raw, where=where)
            reject_literal_secret(raw, where=where)
            checked[name] = expand_refs(raw, env, where=where)
        return checked


class Config(_Model):
    defaults: Defaults = Field(default_factory=Defaults)
    apis: dict[str, ApiConfig] = Field(default_factory=dict)

    def api(self, name: str) -> ResolvedApi:
        """Return API ``name`` with defaults filled in. Raises ``ConfigError`` if unknown."""
        if name not in self.apis:
            raise ConfigError(f"no API named {name!r} in config")
        raw = self.apis[name]
        return ResolvedApi(
            name=name,
            base_url=raw.base_url,
            headers=raw.headers,
            timeout=raw.timeout or self.defaults.timeout,
            proxy=raw.proxy or self.defaults.proxy,
            tls=raw.tls or self.defaults.tls,
        )


class ResolvedApi(_Model):
    """One API with every setting filled in. This is what a client is built from."""

    name: str
    base_url: str
    headers: dict[str, str]
    timeout: Timeouts
    proxy: ProxyConfig
    tls: TLSConfig


def parse_config(data: Mapping[str, Any], *, env: Mapping[str, str] | None = None) -> Config:
    """Validate a plain mapping into a ``Config``. Any invalid value raises ``ConfigError``."""
    context = {"env": env if env is not None else os.environ}
    try:
        return Config.model_validate(dict(data), context=context)
    except ValidationError as exc:
        first = exc.errors()[0]
        location = ".".join(str(part) for part in first["loc"]) or "config"
        raise ConfigError(f"{location}: {first['msg']}") from exc


def load_config(path: str | Path, *, env: Mapping[str, str] | None = None) -> Config:
    """Read a YAML file into a ``Config``. Needs the ``yaml`` extra."""
    # Imported here, not at module top: PyYAML is an optional extra.
    try:
        import yaml
    except ImportError as exc:
        raise ImportError("YAML config needs PyYAML: pip install apiframework[yaml]") from exc

    text = Path(path).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level must be a mapping")
    return parse_config(data, env=env)
