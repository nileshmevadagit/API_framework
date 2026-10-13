"""RequestSpec: an immutable description of one HTTP request.

Middleware and pagination never mutate a spec. They call ``clone(**overrides)``
and pass the copy on, so a retry or a next page is always a fresh value.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, field_validator, model_validator

HTTPMethod = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
Pairs = tuple[tuple[str, str], ...]


class RequestSpec(BaseModel):
    """One request, fully described and frozen.

    ``url`` is the filled-in URL (IDs and query values included). ``url_template``
    is the endpoint's pattern, such as ``/users/{user}/repos``. Logs and metrics use
    the template so cardinality stays low and IDs do not leak. It defaults to ``url``
    and is kept across ``clone()`` unless you pass a new one.

    ``params`` and ``headers`` are stored as tuples of pairs so the spec stays
    hashable and cannot be edited in place. Pass a mapping and it is converted.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    method: HTTPMethod
    url: str
    url_template: str = ""
    params: Pairs = ()
    headers: Pairs = ()
    content: bytes | None = None
    json_body: JsonValue = None

    @model_validator(mode="before")
    @classmethod
    def _default_template(cls, data: object) -> object:
        if isinstance(data, dict) and not data.get("url_template"):
            data = {**data, "url_template": data.get("url", "")}
        return data

    @field_validator("method", mode="before")
    @classmethod
    def _upper_method(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("params", "headers", mode="before")
    @classmethod
    def _mapping_to_pairs(cls, value: object) -> object:
        if isinstance(value, Mapping):
            return tuple((str(key), str(val)) for key, val in value.items())
        return value

    def clone(self, **overrides: object) -> RequestSpec:
        """Return a copy with ``overrides`` applied. The original is untouched."""
        data: dict[str, object] = {name: getattr(self, name) for name in type(self).model_fields}
        data.update(overrides)
        return type(self).model_validate(data)
