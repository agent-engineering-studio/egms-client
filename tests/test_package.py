from __future__ import annotations

import egms_client


def test_version_is_exposed() -> None:
    assert egms_client.__version__
