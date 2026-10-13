"""The bottom of the middleware chain: sends one RequestSpec over httpx.

Timeouts, proxy routing and TLS come from a ``ResolvedApi``. Nothing here retries,
authenticates or limits; those are middleware layers above this one.
"""

from __future__ import annotations

import importlib.util
import logging
import ssl
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import httpx

from apiframework.errors import ConfigError

if TYPE_CHECKING:
    from apiframework.config import ProxyConfig, ResolvedApi, TLSConfig
    from apiframework.request import RequestSpec

logger = logging.getLogger("apiframework.transport")


class HTTPTransport:
    """Sends a ``RequestSpec`` and returns the raw ``httpx.Response``. Owns one connection pool."""

    def __init__(self, api: ResolvedApi) -> None:
        self._name = api.name
        _check_socks_available(api.proxy)
        ssl_context = _ssl_context(api.tls, api.name)
        self._client = httpx.AsyncClient(
            headers=api.headers,
            timeout=httpx.Timeout(
                connect=api.timeout.connect,
                read=api.timeout.read,
                write=api.timeout.write,
                pool=api.timeout.pool,
            ),
            verify=ssl_context,
            proxy=api.proxy.url,
            mounts=_no_proxy_mounts(api.proxy, ssl_context),
            trust_env=api.proxy.trust_env,
        )

    async def send(self, req: RequestSpec) -> httpx.Response:
        request = self._client.build_request(
            req.method,
            req.url,
            params=list(req.params) or None,
            headers=list(req.headers) or None,
            content=req.content,
            json=req.json_body,
        )
        return await self._client.send(request)

    async def aclose(self) -> None:
        await self._client.aclose()


def _check_socks_available(proxy: ProxyConfig) -> None:
    is_socks = bool(proxy.url) and urlsplit(proxy.url or "").scheme.startswith("socks")
    if is_socks and importlib.util.find_spec("socksio") is None:
        raise ImportError("SOCKS proxies need socksio: pip install apiframework[socks]")


def _ssl_context(tls: TLSConfig, name: str) -> ssl.SSLContext | bool:
    if not tls.verify:
        logger.warning("TLS certificate verification is disabled for API %r", name)
        return False
    try:
        context = ssl.create_default_context(cafile=tls.ca_bundle)
        if tls.client_cert:
            context.load_cert_chain(tls.client_cert, tls.client_key)
    except (OSError, ssl.SSLError) as exc:
        # The path is in the message; the key's contents never are.
        raise ConfigError(f"tls for API {name!r}: cannot load certificate files: {exc}") from exc
    return context


def _no_proxy_mounts(
    proxy: ProxyConfig, ssl_context: ssl.SSLContext | bool
) -> dict[str, httpx.AsyncBaseTransport]:
    """Route each ``no_proxy`` host, and its subdomains, directly instead of via the proxy."""
    mounts: dict[str, httpx.AsyncBaseTransport] = {}
    for entry in proxy.no_proxy:
        host = entry.lstrip("*.")
        mounts[f"all://{host}"] = httpx.AsyncHTTPTransport(verify=ssl_context, trust_env=False)
        mounts[f"all://*.{host}"] = httpx.AsyncHTTPTransport(verify=ssl_context, trust_env=False)
    return mounts
