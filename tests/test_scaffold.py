"""Scaffold smoke tests: the package must be importable."""

import tsurv


def test_package_imports() -> None:
    """The tsurv package imports and exposes the expected version."""
    assert tsurv.__version__ == "0.1.0"
