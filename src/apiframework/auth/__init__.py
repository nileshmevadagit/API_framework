"""Auth handlers, and the factory that turns a config section into one."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apiframework.auth.base import AuthHandler
from apiframework.auth.custom import CustomAuth
from apiframework.auth.oauth2 import OAuth2Auth
from apiframework.auth.simple import ApiKeyAuth, BasicAuth, BearerAuth
from apiframework.config import ApiKeyAuth as ApiKeyConfig
from apiframework.config import BasicAuth as BasicConfig
from apiframework.config import BearerAuth as BearerConfig
from apiframework.config import OAuth2Auth as OAuth2Config

if TYPE_CHECKING:
    from apiframework.clock import Clock
    from apiframework.config import AuthConfig
    from apiframework.state import StateStore

__all__ = ["ApiKeyAuth", "AuthHandler", "BasicAuth", "BearerAuth", "CustomAuth", "OAuth2Auth"]


def build_auth(config: AuthConfig | None, *, clock: Clock, state: StateStore) -> AuthHandler | None:
    """Build the handler for a config section. ``None`` or ``type: none`` means no auth."""
    if config is None or config.type == "none":
        return None
    if isinstance(config, BearerConfig):
        return BearerAuth(config.token.get_secret_value())
    if isinstance(config, ApiKeyConfig):
        return ApiKeyAuth(config.name, config.value.get_secret_value(), config.location)
    if isinstance(config, BasicConfig):
        return BasicAuth(config.username.get_secret_value(), config.password.get_secret_value())
    if isinstance(config, OAuth2Config):
        return OAuth2Auth(
            token_url=config.token_url,
            client_id=config.client_id.get_secret_value(),
            client_secret=config.client_secret.get_secret_value(),
            scope=config.scope,
            refresh_margin=config.refresh_margin,
            clock=clock,
            state=state,
        )
    raise TypeError(f"unhandled auth config: {type(config).__name__}")
