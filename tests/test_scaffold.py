"""Scaffold smoke tests: the package must be importable."""

import hashlib
import struct
from pathlib import Path

import tsurv

_EMBLEM_MD5: str = "a280036dec31fee2a913db4e13fa04e7"
"""Pinned bytes of the hand-drawn block-pixel T (gen_shell.py retired)."""


def test_package_imports() -> None:
    """The tsurv package imports and exposes the expected version."""
    assert tsurv.__version__ == "0.1.0"


def test_emblem_asset_is_pinned() -> None:
    """The hand-drawn emblem survives: 96x96 RGBA with the pinned bytes."""
    emblem = Path(__file__).resolve().parent.parent / "assets" / "emblem.png"
    raw = emblem.read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", raw[16:24])
    assert (width, height) == (96, 96)
    assert hashlib.md5(raw, usedforsecurity=False).hexdigest() == _EMBLEM_MD5
