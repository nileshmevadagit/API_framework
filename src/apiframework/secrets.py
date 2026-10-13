"""Secret references: config may name a secret (``${ENV_VAR}``) but never contain one.

``expand_refs`` swaps references for environment values. ``reject_literal_secret``
refuses values that look like a pasted key, so a secret committed to YAML fails
at load time rather than in production.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from apiframework.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Mapping

REF_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

# Prefixes used by common providers. Matched case-sensitively.
_KNOWN_KEY_PREFIXES = ("ghp_", "gho_", "github_pat_", "sk_live_", "sk_test_", "sk-", "AKIA", "xox")

# Header and parameter names that usually carry a credential.
SENSITIVE_NAME = re.compile(r"auth|key|token|secret|password|cookie", re.IGNORECASE)


def expand_refs(value: str, env: Mapping[str, str], *, where: str) -> str:
    """Replace every ``${NAME}`` in ``value`` with ``env[NAME]``.

    ``where`` names the config field for the error message. The value itself is never
    included, since it may be half a secret.
    """

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in env:
            raise ConfigError(f"{where}: environment variable {name} is not set")
        return env[name]

    return REF_PATTERN.sub(_sub, value)


def strip_refs(value: str) -> str:
    """Remove references so the remaining text can be checked for literal secrets."""
    return REF_PATTERN.sub("", value)


def reject_literal_secret(value: str, *, where: str) -> None:
    """Raise ``ConfigError`` if ``value`` contains a literal secret.

    Checks the text left after references are removed, so ``Bearer ${TOKEN}`` passes
    and ``Bearer ghp_...`` does not.
    """
    if any(_looks_like_key(token) for token in strip_refs(value).split()):
        raise ConfigError(f"{where}: looks like a pasted secret; use ${{ENV_VAR}} instead")


def reject_literal_name_value(name: str, value: str, *, where: str) -> None:
    """Reject a credential-named field (e.g. ``X-Api-Key``) that holds a literal value."""
    if SENSITIVE_NAME.search(name) and value and not REF_PATTERN.search(value):
        raise ConfigError(f"{where}: {name!r} must reference an environment variable")


def reject_literal_userinfo(url: str, *, where: str) -> None:
    """Reject a URL whose password is written out instead of referenced."""
    password = urlsplit(strip_refs(url)).password
    if password:
        raise ConfigError(f"{where}: password in URL must be ${{ENV_VAR}}, not a literal")


def _looks_like_key(token: str) -> bool:
    if token.startswith(_KNOWN_KEY_PREFIXES):
        return True
    # Long opaque tokens with both letters and digits (for example hex or base64 blobs).
    return (
        len(token) >= 20
        and re.fullmatch(r"[A-Za-z0-9_\-.=+/]+", token) is not None
        and any(c.isdigit() for c in token)
        and any(c.isalpha() for c in token)
    )
