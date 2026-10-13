from __future__ import annotations

import pytest
from pydantic import ValidationError

from apiframework.request import RequestSpec


def test_method_is_normalised_to_upper_case() -> None:
    assert RequestSpec(method="get", url="https://x.test/a").method == "GET"


def test_unknown_method_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RequestSpec(method="TRACE", url="https://x.test/a")


def test_url_template_defaults_to_url() -> None:
    spec = RequestSpec(method="GET", url="https://x.test/users/42")
    assert spec.url_template == "https://x.test/users/42"


def test_explicit_url_template_is_kept() -> None:
    spec = RequestSpec(method="GET", url="https://x.test/users/42", url_template="/users/{id}")
    assert spec.url_template == "/users/{id}"


def test_mappings_become_ordered_pairs() -> None:
    spec = RequestSpec(
        method="GET",
        url="https://x.test/a",
        params={"page": 2, "per_page": "100"},
        headers={"Accept": "application/json"},
    )
    assert spec.params == (("page", "2"), ("per_page", "100"))
    assert spec.headers == (("Accept", "application/json"),)


def test_spec_is_frozen() -> None:
    spec = RequestSpec(method="GET", url="https://x.test/a")
    with pytest.raises(ValidationError):
        spec.url = "https://x.test/b"  # type: ignore[misc]  # testing the frozen guard


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        RequestSpec(method="GET", url="https://x.test/a", timeout=5)  # type: ignore[call-arg]


def test_clone_returns_new_spec_and_leaves_original_alone() -> None:
    original = RequestSpec(method="GET", url="https://x.test/a", params={"page": 1})
    copy = original.clone(params={"page": 2})
    assert copy is not original
    assert copy.params == (("page", "2"),)
    assert original.params == (("page", "1"),)


def test_clone_keeps_url_template_when_url_changes() -> None:
    original = RequestSpec(method="GET", url="https://x.test/users/1", url_template="/users/{id}")
    copy = original.clone(url="https://x.test/users/1?page=2")
    assert copy.url == "https://x.test/users/1?page=2"
    assert copy.url_template == "/users/{id}"


def test_clone_can_carry_body_and_content() -> None:
    original = RequestSpec(method="POST", url="https://x.test/a", json_body={"q": 1})
    assert original.clone(json_body={"q": 2}).json_body == {"q": 2}
    assert original.clone(content=b"raw").content == b"raw"


def test_clone_rejects_unknown_override() -> None:
    spec = RequestSpec(method="GET", url="https://x.test/a")
    with pytest.raises(ValidationError):
        spec.clone(timeout=5)
