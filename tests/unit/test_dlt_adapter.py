"""The dlt adapter wraps records as a dlt resource. dlt is a dev dependency here."""

from __future__ import annotations

import sys

import pytest

from apiframework.adapters.dlt import records_resource


def test_records_become_a_named_dlt_resource() -> None:
    resource = records_resource("posts", [{"id": 1}, {"id": 2}])
    assert resource.name == "posts"
    assert list(resource) == [{"id": 1}, {"id": 2}]


def test_missing_extra_names_the_install_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "dlt", None)
    with pytest.raises(ImportError, match=r"apiframework\[dlt\]"):
        records_resource("posts", [])
