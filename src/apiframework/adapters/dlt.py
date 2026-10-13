"""Hand records to dlt, which handles loading. Needs the ``dlt`` extra.

apiframework extracts, dlt loads. Typical use::

    import dlt
    from apiframework.adapters.dlt import records_resource

    resource = records_resource("posts", client.iter_items(spec, strategy))
    dlt.pipeline("jsonplaceholder", destination="duckdb", dataset_name="raw").run(resource)

dlt needs a sync iterable, so pass records from ``Client.iter_items`` (the sync client), not
the async generator from ``AsyncClient``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from pydantic import JsonValue


def records_resource(name: str, records: Iterable[JsonValue]) -> Any:
    """Wrap ``records`` as a dlt resource called ``name``.

    The return type is dlt's ``DltResource``. It is left as ``Any`` so this module does not
    import dlt at load time.
    """
    try:
        import dlt
    except ImportError as exc:
        raise ImportError("the dlt adapter needs dlt: pip install apiframework[dlt]") from exc
    items: Iterator[Any] = iter(records)
    resource: Any = dlt.resource(items, name=name)
    return resource
