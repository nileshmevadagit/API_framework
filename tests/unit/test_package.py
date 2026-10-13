from __future__ import annotations

import apiframework


def test_version_is_exposed() -> None:
    assert isinstance(apiframework.__version__, str)
    assert apiframework.__version__
